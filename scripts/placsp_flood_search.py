"""Flood-contract search over PLACSP open-data feeds (FireWatch method adapted to floods).

Selection rule:  Keep = ( P ∪ ( S ∩ K ) ) ∖ N
  P = a primary (flood-specific) CPV code
  S = a secondary (broader) CPV code
  K = a positive keyword root in the contract title
  N = a negative keyword root in the title or contracting authority

Scope: contracts located in Valencia province (NUTS ES523), or whose contracting
authority sits in Valencia province, or whose authority is the CHJ.

Usage:
  python scripts/placsp_flood_search.py OUT_DIR FEED.zip|FEED.atom [...]

Writes OUT_DIR/kept.csv, OUT_DIR/excluded_negative.csv,
OUT_DIR/secondary_no_keyword.csv and OUT_DIR/summary.txt.
Standard library only.
"""
import csv
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- rule lists
# CPV codes checked against the EU Vocabularies CPV 2008 dataset (23 Nov 2026).
PRIMARY = {
    "45246000": "River regulation and flood control works",
    "45246100": "River-wall construction",
    "45246200": "Riverbank protection works",
    "45246400": "Flood-prevention works",
    "45246410": "Flood-defences maintenance works",
    "44212382": "Floodgates",
    "42131143": "Flood-control valves",
}
SECONDARY = {
    # moved from primary after the Oct 2026 test: used on street redevelopment, sports pitches, cycle lanes
    "45232130": "Storm-water piping construction work",
    "45232454": "Rain-water basin construction work",
    "45247230": "Dyke construction work",
    "45232400": "Sewer construction work",
    "45232410": "Sewerage work",
    "45232450": "Drainage construction works",
    "45232451": "Drainage and surface works",
    "45232452": "Drainage works",
    "45232453": "Drains construction work",
    "45111240": "Ground-drainage work",
    "45240000": "Construction work for water projects",
    "45243510": "Embankment works",
    "45247000": "Construction work for dams, canals, irrigation channels and aqueducts",
    "45247112": "Drainage canal construction work",
    "45247220": "Weir construction work",
    "45247270": "Reservoir construction works",
    "45221220": "Culverts",
    "45112000": "Excavating and earthmoving work",
    "45111000": "Demolition, site preparation and clearance work",
    "45221110": "Bridge construction work",
    "45233141": "Road-maintenance works",
    "44163112": "Drainage system",
    "90470000": "Sewer cleaning services",
    "90640000": "Gully cleaning and emptying services",
    "90641000": "Gully cleaning services",
    "90642000": "Gully emptying services",
    "90721800": "Natural risks or hazards protection services",
    "90722000": "Environmental rehabilitation",
    "71320000": "Engineering design services",
    "71335000": "Engineering studies",
    "71242000": "Project and design preparation, estimation of costs",
    "71351612": "Hydrometeorology services",
    "71351920": "Oceanography and hydrology services",
    "79415200": "Design consultancy services",
    "32441100": "Telemetry surveillance system",
    "38125000": "Rainfall recorders",
    "38290000": "Surveying, hydrographic, oceanographic and hydrological instruments and appliances",
    "45214640": "Meteorological stations construction work",
    "45000000": "Construction work",
}
# Whole CPV branches treated as secondary (keyword still required). Added after the Oct 2026 test:
# flood design, studies and technical support are mostly coded as generic engineering services.
SECONDARY_PREFIXES = {
    "71": "Architectural, construction, engineering and inspection services (whole division)",
    "4522": "Engineering works and construction works (bridges, tunnels, culverts)",
    "4523": "Construction work for pipelines, communication and power lines, highways, roads",
}
POSITIVE = [
    "inundac", "inundabl", "riuad", "barranc", "encauz", "cauce", "llera", "fluvial",
    "drenaj", "drenatge", "pluvial", "tormenta", "tempesta", "laminac", "escorrent",
    "desbord", "aliviader", "dominio publico hidraulico", "saih",
    "alerta temprana", "alerta primerenca", "pluviometr", "estacion de aforo", "avenida extraordinaria",
    "antiinundac",
    # Added after the Oct 2024–Oct 2026 backfill: CHJ "río Magro y afluentes" (€27M) and the
    # Generalitat watershed restoration of the Poyo–Pozalet–Saleta basins had no keyword.
    "afluent", "rambla", "restauracion hidrologic", "margen rio",
]
NEGATIVE = [
    "edifici", "colegio", "escola", "centro educativo", "hospital", "centro de salud",
    "piscina", "polideportiv", "poliesportiu", "cementeri", "ascensor", "climatiz",
    "calefacc", "impermeabiliz cubiert", "agua potable", "aigua potable",
    "abastecimiento", "incendi", "seguro", "limpieza viaria",
]
DANA_TAG = r"\bdana\b"
# A title with one of these keeps the contract even if a negative keyword matches
# (e.g. an anti-flood wall at a hospital). Added after the Oct 2026 test.
OVERRIDE = ["inundac", "antiinundac", "inundabl", "riuad"]
EXCLUDED_AUTHORITY = ["hospital", "centro de salud", "colegio", "instituto de educacion"]


# ---------------------------------------------------------------- matching
def norm(s):
    s = (s or "").replace("·", "").replace("l.l", "ll").lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def root_pattern(term):
    words = norm(term).split()
    gap = r"\w*(?:\W+\w+){0,2}\W+"  # rest of the word, then up to two words in between (FireWatch rule)
    return re.compile(r"\b" + gap.join(re.escape(w) for w in words))


POS_RE = [(t, root_pattern(t)) for t in POSITIVE]
OVR_RE = [(t, root_pattern(t)) for t in OVERRIDE]
NEG_RE = [(t, root_pattern(t)) for t in NEGATIVE]


def hits(text, pats):
    t = norm(text)
    return [term for term, p in pats if p.search(t)]


# ---------------------------------------------------------------- parsing
A = "{http://www.w3.org/2005/Atom}"
TOMB = "{http://purl.org/atompub/tombstones/1.0}deleted-entry"


def local(el):
    return el.tag.rsplit("}", 1)[-1]


def first(el, *path):
    """Follow local names; return first matching element or None."""
    cur = [el]
    for name in path:
        nxt = []
        for c in cur:
            nxt.extend(x for x in c if local(x) == name)
        if not nxt:
            return None
        cur = nxt
    return cur[0]


def text(el, *path):
    x = first(el, *path)
    return (x.text or "").strip() if x is not None else ""


def parse_entry(e):
    cfs = next((x for x in e if local(x) == "ContractFolderStatus"), None)
    if cfs is None:
        return None
    party = first(cfs, "LocatedContractingParty", "Party")
    chain, p = [], first(cfs, "LocatedContractingParty")
    while p is not None:
        p = first(p, "ParentLocatedParty")
        if p is not None:
            chain.append(text(p, "PartyName", "Name"))
    proj = first(cfs, "ProcurementProject")
    cpvs = sorted({(x.text or "").strip()[:8] for x in cfs.iter() if local(x) == "ItemClassificationCode" and x.text})
    nuts = sorted({(c.text or "").strip() for loc in cfs.iter() if local(loc) == "RealizedLocation"
                   for c in loc if local(c) == "CountrySubentityCode" and c.text})
    results = [x for x in cfs if local(x) == "TenderResult"]
    winners = sorted({text(r, "WinningParty", "PartyName", "Name") for r in results} - {""})
    award = sum(float(text(r, "AwardedTenderedProject", "LegalMonetaryTotal", "TaxExclusiveAmount") or 0) for r in results)
    return {
        "entry_id": text(e, "id"),
        "updated": text(e, "updated"),
        "link": (first(e, "link").get("href") if first(e, "link") is not None else ""),
        "file_id": text(cfs, "ContractFolderID"),
        "status": text(cfs, "ContractFolderStatusCode"),
        "authority": text(party, "PartyName", "Name") if party is not None else "",
        "authority_nif": next((text(pi, "ID") for pi in (party if party is not None else []) if local(pi) == "PartyIdentification"
                               and first(pi, "ID") is not None and first(pi, "ID").get("schemeName") == "NIF"), ""),
        "authority_postcode": text(party, "PostalAddress", "PostalZone") if party is not None else "",
        "authority_chain": " > ".join(c for c in chain if c),
        "title": text(proj, "Name") if proj is not None else text(e, "title"),
        "entry_title": text(e, "title"),
        "contract_type": text(proj, "TypeCode") if proj is not None else "",
        "cpv": " ".join(cpvs),
        "nuts": " ".join(nuts),
        "place": text(proj, "RealizedLocation", "CountrySubentity") if proj is not None else "",
        "budget_excl_vat": text(proj, "BudgetAmount", "TaxExclusiveAmount") if proj is not None else "",
        "award_excl_vat": f"{award:.2f}" if results else "",
        "award_date": min((text(r, "AwardDate") for r in results if text(r, "AwardDate")), default=""),
        "winners": " | ".join(winners),
        "procedure": text(cfs, "TenderingProcess", "ProcedureCode"),
        "urgency": text(cfs, "TenderingProcess", "UrgencyCode"),
    }


def iter_entries(paths):
    """Yield (path_name, element) for every entry and tombstone in .atom files or .zip archives of them."""
    for path in paths:
        path = Path(path)
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                for name in sorted(n for n in z.namelist() if n.endswith(".atom")):
                    with z.open(name) as f:
                        for el in ET.parse(f).getroot():
                            if local(el) in ("entry", "deleted-entry"):
                                yield name, el
        else:
            for el in ET.parse(path).getroot():
                if local(el) in ("entry", "deleted-entry"):
                    yield path.name, el


# ---------------------------------------------------------------- scope and rule
def in_scope(r):
    # A contract placed at province level (5-character NUTS) outside Valencia is out,
    # even when a Generalitat body or CHJ signs it (e.g. a dyke in Alicante).
    # Coarser codes (ES, ES52) say nothing about the province, so the authority tests decide.
    nuts = r["nuts"].split()
    if any(len(n) >= 5 for n in nuts) and not any(n.startswith("ES523") for n in nuts):
        return []
    reasons = []
    if any(n.startswith("ES523") for n in r["nuts"].split()):
        reasons.append("located ES523")
    parts = [p.strip() for p in norm(r["authority_chain"]).split(">")]
    if any(p in ("valencia", "valencia/valencia") for p in parts) and any("valencian" in p for p in parts):
        reasons.append("authority in Valencia province")
    if r["authority_postcode"].startswith("46"):
        reasons.append("authority postcode 46")
    if "confederacion hidrografica del jucar" in norm(r["authority"] + " " + r["authority_chain"]):
        reasons.append("CHJ")
    return reasons


def classify(r):
    cpvs = r["cpv"].split()
    prim = [c for c in cpvs if c in PRIMARY]
    sec = [c for c in cpvs if c in SECONDARY or (c not in PRIMARY and any(c.startswith(px) for px in SECONDARY_PREFIXES))]
    pos = hits(r["title"] + " " + r["entry_title"], POS_RE)
    neg = hits(r["title"] + " " + r["entry_title"] + " " + r["authority"], NEG_RE)
    auth_excl = hits(r["authority"], [(t, root_pattern(t)) for t in EXCLUDED_AUTHORITY])
    ovr = hits(r["title"] + " " + r["entry_title"], OVR_RE)
    r.update(primary_cpv=" ".join(prim), secondary_cpv=" ".join(sec), positive=" ".join(pos),
             negative="; ".join(neg + auth_excl), dana_tag="yes" if re.search(DANA_TAG, norm(r["title"] + " " + r["entry_title"])) else "")
    if not (prim or sec):
        return "no_cpv_match"
    if r["status"] == "ANUL":
        return "cancelled"
    if (neg or auth_excl) and not ovr:
        return "excluded_negative"
    if neg or auth_excl:
        return "kept_override"
    if prim:
        return "kept_primary"
    if pos:
        return "kept_secondary_keyword"
    return "secondary_no_keyword"


def ts(value):
    """Parse an ATOM timestamp (offsets vary between +01:00 and +02:00) for ordering."""
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def main(out_dir, *feeds):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    latest, deleted = {}, {}
    n_entries = 0
    for _, el in iter_entries(feeds):
        if local(el) == "deleted-entry":
            # Keep the latest deletion time per entry; it only wins over a newer publication if later.
            k, when = el.get("ref"), ts(el.get("when"))
            if k not in deleted or when > deleted[k]:
                deleted[k] = when
            continue
        n_entries += 1
        r = parse_entry(el)
        if r is None:
            continue
        k = r["entry_id"]
        if k not in latest or ts(r["updated"]) > ts(latest[k]["updated"]):
            latest[k] = r
    for k, when in deleted.items():
        if k in latest and when >= ts(latest[k]["updated"]):
            latest.pop(k)
    buckets, scope_n = {}, 0
    for r in latest.values():
        sc = in_scope(r)
        if not sc:
            continue
        scope_n += 1
        r["scope"] = "; ".join(sc)
        buckets.setdefault(classify(r), []).append(r)
    cols = ["result", "scope", "file_id", "status", "authority", "authority_chain", "title", "cpv", "primary_cpv",
            "secondary_cpv", "positive", "negative", "dana_tag", "budget_excl_vat", "award_excl_vat", "award_date",
            "winners", "procedure", "urgency", "nuts", "place", "updated", "link", "entry_id"]

    def write(name, keys):
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for key in keys:
                for r in sorted(buckets.get(key, []), key=lambda x: x["updated"], reverse=True):
                    w.writerow({"result": key, **r})

    write("kept.csv", ["kept_primary", "kept_secondary_keyword", "kept_override"])
    with open(out / "chj_all.csv", "w", newline="") as f:  # every CHJ contract, for targeted review (PD-003)
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for key, rs in buckets.items():
            for r in rs:
                if "CHJ" in r["scope"]:
                    w.writerow({"result": key, **r})
    write("excluded_negative.csv", ["excluded_negative", "cancelled"])
    write("secondary_no_keyword.csv", ["secondary_no_keyword"])
    kept = [r for k in ("kept_primary", "kept_secondary_keyword", "kept_override") for r in buckets.get(k, [])]
    lines = [
        f"Feeds: {', '.join(Path(f).name for f in feeds)}",
        f"Entries read: {n_entries}; unique contract records: {len(latest)}; tombstones: {len(deleted)}",
        f"In Valencia scope: {scope_n}",
        *(f"  {k}: {len(v)}" for k, v in sorted(buckets.items())),
        f"Kept with 'dana' in title: {sum(1 for r in kept if r['dana_tag'])}",
        "Kept by CPV: " + ", ".join(f"{c} {n}" for c, n in Counter(
            c for r in kept for c in (r["primary_cpv"] + " " + r["secondary_cpv"]).split()).most_common(15)),
        "Excluded by negative keyword: " + ", ".join(f"{c} {n}" for c, n in Counter(
            t for r in buckets.get("excluded_negative", []) for t in r["negative"].split("; ")).most_common(15)),
    ]
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(*sys.argv[1:])

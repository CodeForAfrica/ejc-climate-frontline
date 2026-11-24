"""Compare one month's PLACSP search run with everything seen before it.

Usage:
  python scripts/placsp_monthly_diff.py RUNS_DIR YYYYMM

RUNS_DIR holds one folder per run, each with the kept.csv and chj_all.csv
written by placsp_flood_search.py: the backfill baseline plus one folder per
month (named YYYYMM). Earlier runs are folded together, latest update wins,
and the month's run is compared with them.

Writes RUNS_DIR/YYYYMM/changes.csv and RUNS_DIR/YYYYMM/report.md.
Standard library only.
"""
import csv
import sys
from pathlib import Path

WATCH = ["status", "budget_excl_vat", "award_excl_vat", "winners"]
STATUS = {"PRE": "announced", "PUB": "open for bids", "EV": "under evaluation", "ADJ": "awarded",
          "RES": "resolved (contract formalised)", "ANUL": "cancelled"}


def load(path):
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {r["entry_id"]: r for r in csv.DictReader(f)}


def money(v):
    try:
        return f"€{float(v):,.0f}"
    except (TypeError, ValueError):
        return "n/a"


def main(runs_dir, month):
    runs = Path(runs_dir)
    cur_dir = runs / month
    # Baseline first, then earlier months in order, so later updates overwrite earlier ones.
    dirs = [d for d in runs.iterdir() if d.is_dir()]
    order = sorted(d for d in dirs if d.name.startswith("baseline")) + \
        sorted(d for d in dirs if d.name.isdigit() and d.name < month)
    seen_kept, seen_chj = {}, {}
    for d in order:
        for src, dst in (("kept.csv", seen_kept), ("chj_all.csv", seen_chj)):
            for k, r in load(d / src).items():
                if k not in dst or r["updated"] >= dst[k]["updated"]:
                    dst[k] = r

    kept, chj = load(cur_dir / "kept.csv"), load(cur_dir / "chj_all.csv")
    rows = []
    for k, r in kept.items():
        old = seen_kept.get(k)
        if old is None:
            rows.append(("new kept", r, ""))
        else:
            diffs = [f"{c}: {old.get(c) or '-'} → {r.get(c) or '-'}" for c in WATCH if (old.get(c) or "") != (r.get(c) or "")]
            if diffs:
                rows.append(("changed", r, "; ".join(diffs)))
    for k, r in chj.items():  # CHJ contracts the keyword rules miss (canals, dams)
        if k not in kept and k not in seen_chj and k not in seen_kept:
            rows.append(("new CHJ, not kept", r, ""))

    cols = ["change", "detail", "result", "status", "authority", "title", "file_id", "budget_excl_vat",
            "award_excl_vat", "winners", "dana_tag", "scope", "updated", "link", "entry_id"]
    with open(cur_dir / "changes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for change, r, detail in rows:
            w.writerow({**r, "change": change, "detail": detail})

    def line(r, detail=""):
        amount = money(r.get("award_excl_vat") or r.get("budget_excl_vat"))
        st = STATUS.get(r.get("status"), r.get("status"))
        extra = f" — {detail}" if detail else ""
        return f"- {r['title'][:160]} ({r['authority']}; {st}; {amount}){extra}\n  {r['link']}"

    groups = {}
    for change, r, detail in rows:
        groups.setdefault(change, []).append((r, detail))
    summary = (cur_dir / "summary.txt").read_text() if (cur_dir / "summary.txt").exists() else ""
    out = [f"# PLACSP monthly update: {month[:4]}-{month[4:]}", "",
           f"Compared with {len(order)} earlier run(s): {', '.join(d.name for d in order)}.", "",
           f"- New contracts kept by the flood rules: {len(groups.get('new kept', []))}",
           f"- Kept contracts with a changed status, amount or winner: {len(groups.get('changed', []))}",
           f"- New CHJ contracts the rules did not keep (review by hand): {len(groups.get('new CHJ, not kept', []))}",
           "", "These are rule results on titles only. Hand-check them before adding anything to the register.", ""]
    for title, key in (("New contracts kept", "new kept"), ("Changed contracts", "changed"),
                       ("New CHJ contracts not kept", "new CHJ, not kept")):
        items = groups.get(key, [])
        if items:
            out += [f"## {title}", ""] + [line(r, d) for r, d in
                                          sorted(items, key=lambda x: -float(x[0].get("award_excl_vat") or x[0].get("budget_excl_vat") or 0))] + [""]
    out += ["## Search summary", "", "```", summary.strip(), "```", ""]
    (cur_dir / "report.md").write_text("\n".join(out))
    print("\n".join(out[:9]))


if __name__ == "__main__":
    main(*sys.argv[1:])

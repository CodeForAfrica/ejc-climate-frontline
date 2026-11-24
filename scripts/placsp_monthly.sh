#!/usr/bin/env bash
# Monthly PLACSP flood-contract update.
#
# Downloads one month of PLACSP contracting-profile data, runs the flood search
# on it, and compares the result with all earlier runs.
#
# Usage: scripts/placsp_monthly.sh [YYYYMM]   (default: the previous month)
#
# Data and results stay in working/ (git-ignored):
#   working/placsp_raw/perfiles_YYYYMM.zip      monthly download
#   working/placsp_runs/YYYYMM/report.md        what changed, for the hand check
#   working/placsp_runs/YYYYMM/changes.csv      the same, as a table
#   working/placsp_runs/monthly.log             log of every run
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RAW="$REPO/working/placsp_raw"
RUNS="$REPO/working/placsp_runs"
MONTH="${1:-$(date -d "$(date +%Y-%m-01) -1 month" +%Y%m)}"
URL="https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_${MONTH}.zip"
ZIP="$RAW/perfiles_${MONTH}.zip"
mkdir -p "$RAW" "$RUNS"
exec >> "$RUNS/monthly.log" 2>&1
echo "== $(date -Is) month $MONTH"

notify() { command -v notify-send >/dev/null && notify-send "PLACSP update $MONTH" "$1" || true; }
trap 'notify "Failed. See working/placsp_runs/monthly.log"' ERR

# A file downloaded while its month was still running is incomplete: fetch again.
if [ -f "$ZIP" ] && [ "$(date -r "$ZIP" +%Y%m)" -le "$MONTH" ]; then rm -f "$ZIP"; fi

if ! { [ -f "$ZIP" ] && unzip -tq "$ZIP" >/dev/null 2>&1; }; then
  ok=0
  for try in 1 2 3 4 5; do
    if curl -s --fail -m 14400 -o "$ZIP.part" "$URL" && unzip -tq "$ZIP.part" >/dev/null 2>&1; then
      mv "$ZIP.part" "$ZIP"; ok=1; break
    fi
    echo "download try $try failed"; sleep 120
  done
  [ "$ok" = 1 ] || { rm -f "$ZIP.part"; echo "download failed"; false; }
fi
echo "downloaded $(du -h "$ZIP" | cut -f1)"

python3 -I "$REPO/scripts/placsp_flood_search.py" "$RUNS/$MONTH" "$ZIP"
python3 -I "$REPO/scripts/placsp_monthly_diff.py" "$RUNS" "$MONTH"

notify "$(sed -n 's/^- //p' "$RUNS/$MONTH/report.md" | head -3 | tr '\n' ' ') Report: working/placsp_runs/$MONTH/report.md"
echo "done $(date -Is)"

#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/packaging/out"
STAGE="$OUT/football-epa"
rm -rf "$STAGE"
mkdir -p "$STAGE"

rsync -a \
  --exclude '.venv' \
  --exclude '.git' \
  --exclude 'packaging/out' \
  --exclude '__pycache__' \
  --exclude 'data/live_log.csv' \
  --exclude 'data/game_state.json' \
  --exclude 'data/drive_state.json' \
  --exclude 'data/lineup_state.json' \
  --exclude 'data/football.db' \
  --exclude 'data/halftime_reports/*' \
  --exclude 'data/hudl_exports/*.xlsx' \
  "$ROOT/" "$STAGE/"

mkdir -p "$STAGE/data/hudl_exports" "$STAGE/data/halftime_reports" "$STAGE/data/game_plans"
cp "$ROOT/data/hudl_exports/README.txt" "$STAGE/data/hudl_exports/" 2>/dev/null || true
touch "$STAGE/data/halftime_reports/.gitkeep"

cp "$ROOT/packaging/templates/Install and Run.command" "$STAGE/"
cp "$ROOT/packaging/templates/Install and Run.bat" "$STAGE/"
chmod +x "$STAGE/Install and Run.command" \
  "$STAGE/run_live_local.command" "$STAGE/run_live_shared.command" \
  "$STAGE/run_live_local.sh" "$STAGE/run_live_shared.sh" 2>/dev/null || true

(
  cd "$OUT"
  rm -f football-epa-portable.zip
  zip -r football-epa-portable.zip football-epa >/dev/null
)
echo "Wrote $OUT/football-epa-portable.zip"

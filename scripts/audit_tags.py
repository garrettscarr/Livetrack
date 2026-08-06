#!/usr/bin/env python3
"""CP0 tag audit: case splits, alias coverage, roster/starters, scout map."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tag_normalize import normalize_play_call  # noqa: E402
from team_config import load_team_config, week1_opponent  # noqa: E402

DB = ROOT / "data" / "football.db"
ROSTER = ROOT / "data" / "roster.json"
STARTERS = ROOT / "data" / "starters.json"
FAVS = ROOT / "data" / "live_favorites.json"
OPPONENTS = ROOT / "data" / "opponents.csv"
SCOUT_DIR = ROOT / "data" / "hudl_exports"


def main() -> int:
    cfg = load_team_config()
    print("=== Team config ===")
    print(f"team: {cfg.get('team_name')}  week1: {week1_opponent()}")
    print(f"play aliases: {cfg.get('play_word_aliases')}")
    print()

    if not DB.exists():
        print("ERROR: football.db missing — run refresh_all.py")
        return 1

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT play_call, COUNT(*) n FROM offense_plays_epa "
        "WHERE play_call IS NOT NULL AND trim(play_call) != '' "
        "GROUP BY play_call ORDER BY n DESC"
    ).fetchall()

    # After normalize, do any labels still collide?
    buckets: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for name, n in rows:
        buckets[normalize_play_call(name)].append((name, n))

    splits = {k: v for k, v in buckets.items() if len(v) > 1}
    print("=== Play-call labels that normalize to the same canonical ===")
    if not splits:
        print("(none — aliases look clean)")
    else:
        for canon, variants in sorted(splits.items(), key=lambda x: -sum(n for _, n in x[1])):
            print(f"  {canon!r}: {variants}")

    # Case-only duplicates on formation (current season tagged)
    form_rows = con.execute(
        "SELECT formation, COUNT(*) n FROM offense_plays_epa "
        "WHERE form_tagged=1 AND formation IS NOT NULL AND trim(formation)!='' "
        "GROUP BY formation"
    ).fetchall()
    by_lower: dict[str, list] = defaultdict(list)
    for name, n in form_rows:
        by_lower[name.lower()].append((name, n))
    case_splits = {k: v for k, v in by_lower.items() if len(v) > 1}
    print("\n=== Formation case splits (form_tagged) ===")
    if not case_splits:
        print("(none)")
    else:
        for k, v in case_splits.items():
            print(f"  {k}: {v}")

    # Favorites vs Axle
    favs = json.loads(FAVS.read_text()) if FAVS.exists() else {}
    plays = []
    for bucket in (favs.get("plays") or {}).values():
        plays.extend(bucket or [])
    bad = [p for p in plays if "axel" in str(p).lower() and normalize_play_call(p) != p]
    print("\n=== Favorites needing normalize ===")
    print(bad or "(ok)")

    # Roster / starters
    roster_names = {p["name"] for p in json.loads(ROSTER.read_text()).get("players", [])}
    starters = json.loads(STARTERS.read_text()).get("offense", {})
    missing = [v for v in starters.values() if v not in roster_names]
    print("\n=== Starters missing from roster ===")
    print(missing or "(ok)")

    # Scout files for week-1 / schedule
    print("\n=== Scout Hudl files ===")
    scout_files = sorted(SCOUT_DIR.glob("* D.xlsx")) + sorted(SCOUT_DIR.glob("* O.xlsx"))
    for p in scout_files:
        print(f"  {p.name}")
    w1 = week1_opponent()
    has_d = (SCOUT_DIR / f"{w1} D.xlsx").exists()
    has_o = (SCOUT_DIR / f"{w1} O.xlsx").exists()
    print(f"week1 {w1}: D={has_d} O={has_o}")

    scout_opps = con.execute(
        "SELECT opponent, scout_role, COUNT(*) FROM scout_plays GROUP BY 1,2"
    ).fetchall()
    print("DB scout_plays:", scout_opps)

    if OPPONENTS.exists():
        print("\n=== Season opponents.csv ===")
        print(OPPONENTS.read_text().strip())

    print("\nAudit complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

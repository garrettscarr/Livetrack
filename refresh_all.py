"""
Refresh all data after a new Hudl export.

Run:
    python refresh_all.py

Optional:
    python refresh_all.py --dashboard   (also opens the Streamlit app)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATA_FILE = PROJECT_DIR / "data" / "hudl_exports" / "season.xlsx"
STEPS = (
    ("step2_clean.py", "Clean Hudl data and save to SQLite"),
    ("step3_epa.py", "Calculate expected points and EPA"),
)


def run_step(script_name: str, description: str) -> None:
    script_path = PROJECT_DIR / script_name
    print("\n" + "=" * 60)
    print(description)
    print("=" * 60)
    print(f"Running: python {script_name}\n")

    result = subprocess.run(
        [sys.executable, "-u", str(script_path)],
        cwd=PROJECT_DIR,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"\nStopped: {script_name} failed (exit code {result.returncode})")


def launch_dashboard() -> None:
    print("\n" + "=" * 60)
    print("Opening dashboard in your browser...")
    print("=" * 60)
    print("Press Ctrl+C in this terminal to stop the dashboard.\n")

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "step4_dashboard.py"],
        cwd=PROJECT_DIR,
        check=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh football EPA data from Hudl export.")
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Open the Streamlit dashboard after refresh finishes.",
    )
    args = parser.parse_args()

    print("Football EPA — full refresh")
    print(f"Project folder: {PROJECT_DIR}")

    season_dir = PROJECT_DIR / "data" / "hudl_exports"
    season_files = sorted(
        p for p in season_dir.glob("season*.xlsx")
        if not p.name.startswith("~$") and p.stem.lower() != "scout_season"
    )
    if not DATA_FILE.exists() and not season_files:
        print(f"\nMissing Hudl file: {DATA_FILE}")
        print("\nBefore refreshing:")
        print("  1. Export your Hudl playlist to Excel")
        print("  2. Save it as: data/hudl_exports/season.xlsx")
        print("  Optional prior year: data/hudl_exports/season_24-25.xlsx")
        raise SystemExit(1)

    print("Found season file(s):")
    for p in season_files or [DATA_FILE]:
        print(f"  · {p.name}")

    for script_name, description in STEPS:
        run_step(script_name, description)

    # Re-attach booth Live Track games (survive Hudl replace)
    try:
        from live_games import remerge_all_live_games

        live_info = remerge_all_live_games()
        print(
            f"\nLive Track remerge: {live_info.get('merged', 0)} game(s), "
            f"{live_info.get('plays', 0)} plays"
            + (
                f" ({live_info.get('skipped', 0)} skipped)"
                if live_info.get("skipped")
                else ""
            )
        )
    except Exception as exc:
        print(f"\nLive Track remerge skipped: {exc}")

    print("\n" + "=" * 60)
    print("REFRESH COMPLETE")
    print("=" * 60)
    print("  Database updated: data/football.db")
    print("  EPA tables ready: offense_plays_epa, defense_plays_epa")
    print("  Scout table:      scout_plays (if scout_season.xlsx present)")
    print("  Live games:       data/live_games/ (remerged after Hudl)")
    print("\nTo open the dashboard:")
    print("  python -m streamlit run step4_dashboard.py")
    print("  Mac: run_live_local.command   Windows: run_live_local.bat")
    print("\nFor booth + tablet (same Wi-Fi):")
    print("  Mac: run_live_shared.command  Windows: run_live_shared.bat")
    print("  (shared mode asks for booth PIN from data/team_config.json)")
    print("\nOr next time run:")
    print("  python refresh_all.py --dashboard")

    if args.dashboard:
        launch_dashboard()


if __name__ == "__main__":
    main()

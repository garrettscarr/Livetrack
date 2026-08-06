"""
Step 1: Load your Hudl Excel export and see what you have.

Before EPA, you need to know your column names and spot any messy data.
Run from the project folder:

    python step1_explore.py

Put your Hudl file here first:
    data/hudl_exports/season.xlsx
"""

from pathlib import Path

import pandas as pd

# Always look next to this script, not wherever the terminal happens to be.
PROJECT_DIR = Path(__file__).resolve().parent

# --- CHANGE THIS if your file has a different name ---
DATA_FILE = PROJECT_DIR / "data" / "hudl_exports" / "season.xlsx"


def main() -> None:
    if not DATA_FILE.exists():
        print(f"\nFile not found: {DATA_FILE.resolve()}")
        print("\nDo this first:")
        print("  1. Copy your Hudl Excel file into: data/hudl_exports/")
        print("  2. Rename it to season.xlsx  (or edit DATA_FILE in this script)")
        return

    print(f"\nLoading: {DATA_FILE.resolve()}\n")

    # Read the whole sheet. Hudl exports are usually one tab.
    df = pd.read_excel(DATA_FILE)

    print("=" * 60)
    print("HOW MUCH DATA?")
    print("=" * 60)
    print(f"Rows (plays):  {len(df):,}")
    print(f"Columns:       {len(df.columns)}")

    print("\n" + "=" * 60)
    print("COLUMN NAMES (your tagging fields)")
    print("=" * 60)
    for i, col in enumerate(df.columns, start=1):
        print(f"  {i:2}. {col}")

    print("\n" + "=" * 60)
    print("FIRST 3 PLAYS (sample)")
    print("=" * 60)
    # Show a readable slice — not every column if there are tons
    preview_cols = list(df.columns[:12])
    print(df[preview_cols].head(3).to_string())

    print("\n" + "=" * 60)
    print("MISSING VALUES (blank cells per column)")
    print("=" * 60)
    missing = df.isna().sum()
    missing = missing[missing > 0].sort_values(ascending=False)
    if missing.empty:
        print("  None — every column is filled on every row.")
    else:
        for col, count in missing.head(15).items():
            pct = 100 * count / len(df)
            print(f"  {col}: {count:,} blank ({pct:.0f}%)")

    print("\n" + "=" * 60)
    print("NEXT STEP")
    print("=" * 60)
    print("  Look at the column list above.")
    print("  Find which columns hold: down, distance, yard line, formation, play call, gain/loss.")
    print("  Then we map those names in step2 and start EPA math.\n")


if __name__ == "__main__":
    main()

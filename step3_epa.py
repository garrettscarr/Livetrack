"""
Step 3: Build expected points (EP) and EPA per play.

Run:
    python step3_epa.py

Football idea:
  EP  = "how many points we expect from this situation"
  EPA = "how much this play helped or hurt vs expectation"

  EPA = points_scored + EP(after) - EP(before)
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sqlite3

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "football.db"

# Starting guesses before the model learns from your data
DEFAULT_EP = 2.0
TD_POINTS = 6
KICKOFF_EP_AFTER = 0.0  # after you score a TD, you kick off (possession gone)


def situation_key(field_zone: str, down: int, distance_bucket: str) -> tuple:
    return (field_zone, down, distance_bucket)


def fp_to_zone(fp: float) -> str:
    if fp <= 20:
        return "backed_up"
    if fp <= 40:
        return "own_territory"
    if fp <= 60:
        return "midfield"
    if fp <= 80:
        return "opp_territory"
    return "red_zone"


def after_play_state(row: pd.Series) -> tuple[dict | None, float, bool]:
    """
    Returns (after_situation, points_scored, turnover).
    after_situation is None after a TD (kickoff follows).
    """
    fp = float(row["field_position"])
    down = int(row["down"])
    dist = float(row["distance"])
    yards = 0.0 if pd.isna(row["yards_gained"]) else float(row["yards_gained"])
    result = str(row["result"]) if pd.notna(row["result"]) else ""

    if row["is_touchdown"]:
        return None, TD_POINTS, False

    if row["is_turnover"]:
        spot = max(0.0, min(100.0, fp + yards))
        opp_fp = 100.0 - spot
        opp_zone = fp_to_zone(opp_fp)
        opp_dist_bucket = "medium" if dist > 6 else ("short" if dist <= 3 else "medium")
        after = {
            "field_position": opp_fp,
            "field_zone": opp_zone,
            "down": 1,
            "distance_bucket": opp_dist_bucket,
            "turnover": True,
        }
        return after, 0.0, True

    new_fp = max(0.0, min(100.0, fp + yards))

    if row["is_incomplete"]:
        new_down = down + 1
        new_dist = dist
    elif yards >= dist or new_fp >= 100:
        new_down = 1
        new_dist = min(10.0, 100.0 - new_fp) if new_fp < 100 else 0.0
    else:
        new_down = down + 1
        new_dist = max(0.0, dist - yards)

    if new_down > 4:
        spot = new_fp
        opp_fp = 100.0 - spot
        after = {
            "field_position": opp_fp,
            "field_zone": fp_to_zone(opp_fp),
            "down": 1,
            "distance_bucket": "medium",
            "turnover": True,
        }
        return after, 0.0, True

    after = {
        "field_position": new_fp,
        "field_zone": fp_to_zone(new_fp),
        "down": new_down,
        "distance_bucket": row["distance_bucket"],
        "turnover": False,
    }
    if new_down == 1:
        if new_dist <= 3:
            after["distance_bucket"] = "short"
        elif new_dist <= 6:
            after["distance_bucket"] = "medium"
        else:
            after["distance_bucket"] = "long"

    return after, 0.0, False


def lookup_ep(ep_table: dict, field_zone: str, down: int, distance_bucket: str) -> float:
    return ep_table.get(situation_key(field_zone, down, distance_bucket), DEFAULT_EP)


def build_ep_table(df: pd.DataFrame, iterations: int = 12) -> dict:
    """Learn EP values from your season using fixed-point iteration."""
    ep_table: dict[tuple, float] = {}

    # Seed with sensible HS-ish priors
    zone_prior = {
        "backed_up": 0.9,
        "own_territory": 1.4,
        "midfield": 2.0,
        "opp_territory": 3.2,
        "red_zone": 5.0,
    }
    down_penalty = {1: 1.0, 2: 0.85, 3: 0.65, 4: 0.45}
    dist_penalty = {"short": 1.05, "medium": 1.0, "long": 0.85, "unknown": 0.9}

    for zone in zone_prior:
        for down in (1, 2, 3, 4):
            for dist in ("short", "medium", "long"):
                ep_table[situation_key(zone, down, dist)] = (
                    zone_prior[zone] * down_penalty[down] * dist_penalty[dist]
                )

    for _ in range(iterations):
        bucket_values: dict[tuple, list[float]] = defaultdict(list)

        for _, row in df.iterrows():
            before = situation_key(
                row["field_zone"], int(row["down"]), row["distance_bucket"]
            )
            after, points, turnover = after_play_state(row)

            if after is None:
                ep_after = KICKOFF_EP_AFTER
            elif turnover:
                ep_after = -lookup_ep(
                    ep_table, after["field_zone"], after["down"], after["distance_bucket"]
                )
            else:
                ep_after = lookup_ep(
                    ep_table, after["field_zone"], after["down"], after["distance_bucket"]
                )

            bucket_values[before].append(points + ep_after)

        for key, values in bucket_values.items():
            ep_table[key] = sum(values) / len(values)

    return ep_table


def offense_play_success(
    down: float | int | None,
    distance: float | None,
    yards_gained: float | None,
    *,
    is_touchdown: bool = False,
    is_penalty: bool = False,
) -> float | None:
    """
    Success rate definition:
      1st/2nd: gain >= half the yards to go
      3rd/4th: gain >= all yards to go
      TD = success; penalties excluded (returns None)
    """
    if is_penalty:
        return None
    if is_touchdown:
        return 1.0
    if down is None or pd.isna(down) or distance is None or pd.isna(distance):
        return None
    yards = 0.0 if yards_gained is None or pd.isna(yards_gained) else float(yards_gained)
    dist = float(distance)
    d = int(down)
    if dist <= 0:
        return 1.0
    if d in (1, 2):
        return 1.0 if yards >= 0.5 * dist else 0.0
    if d in (3, 4):
        return 1.0 if yards >= dist else 0.0
    return None


def add_success_flags(df: pd.DataFrame, *, invert: bool = False) -> pd.DataFrame:
    """Add is_success (1/0) for eligible plays; NaN for penalties / unscorable."""
    out = df.copy()
    flags: list[float | None] = []
    for _, row in out.iterrows():
        raw = offense_play_success(
            row.get("down"),
            row.get("distance"),
            row.get("yards_gained"),
            is_touchdown=bool(row.get("is_touchdown", False)),
            is_penalty=bool(row.get("is_penalty", False)),
        )
        if raw is None:
            flags.append(None)
        elif invert:
            flags.append(1.0 - raw)
        else:
            flags.append(raw)
    out["is_success"] = flags
    return out


def add_epa(df: pd.DataFrame, ep_table: dict) -> pd.DataFrame:
    ep_before_list = []
    ep_after_list = []
    epa_list = []

    for _, row in df.iterrows():
        before = situation_key(
            row["field_zone"], int(row["down"]), row["distance_bucket"]
        )
        ep_before = lookup_ep(
            ep_table, row["field_zone"], int(row["down"]), row["distance_bucket"]
        )

        after, points, turnover = after_play_state(row)

        if after is None:
            ep_after = KICKOFF_EP_AFTER
        elif turnover:
            ep_after = -lookup_ep(
                ep_table, after["field_zone"], after["down"], after["distance_bucket"]
            )
        else:
            ep_after = lookup_ep(
                ep_table, after["field_zone"], after["down"], after["distance_bucket"]
            )

        epa = points + ep_after - ep_before

        ep_before_list.append(round(ep_before, 3))
        ep_after_list.append(round(ep_after, 3))
        epa_list.append(round(epa, 3))

    out = df.copy()
    out["ep_before"] = ep_before_list
    out["ep_after"] = ep_after_list
    out["epa"] = epa_list
    return out


def print_leaderboard(df: pd.DataFrame, group_col: str, title: str, min_plays: int = 8) -> None:
    valid = df[df[group_col].notna() & (df[group_col] != "")]
    # Prefer tagged rows so Unknown / blank prior-year tags don't dominate
    if "season" in valid.columns and group_col in {"formation", "formation_play"}:
        s = valid["season"].fillna("current").astype(str).str.strip().str.lower()
        valid = valid[s.isin({"current", "25-26", ""})]
    if group_col == "formation" and "form_tagged" in valid.columns:
        valid = valid[valid["form_tagged"].fillna(0).astype(int) == 1]
    elif group_col == "play_call" and "play_tagged" in valid.columns:
        valid = valid[valid["play_tagged"].fillna(0).astype(int) == 1]
    elif "tags_ok" in valid.columns and group_col in {"formation", "formation_play"}:
        valid = valid[valid["tags_ok"].fillna(0).astype(int) == 1]
    valid = valid[~valid[group_col].astype(str).str.contains("Unknown", na=False)]
    if valid.empty:
        print(f"\n{title}: no tagged data")
        return

    aggs = {"plays": ("epa", "count"), "avg_epa": ("epa", "mean"), "total_epa": ("epa", "sum")}
    if "is_success" in valid.columns:
        aggs["success_rate"] = ("is_success", "mean")
    board = (
        valid.groupby(group_col)
        .agg(**{k: v for k, v in aggs.items()})
        .query("plays >= @min_plays")
        .sort_values("avg_epa", ascending=False)
    )
    if "success_rate" in board.columns:
        board["success_rate"] = (board["success_rate"] * 100).round(0)

    print(f"\n{title} (min {min_plays} plays, sorted by avg EPA):")
    if board.empty:
        print("  Not enough plays in any category yet.")
        return
    print(board.head(10).round(3).to_string())


def process_side(
    df: pd.DataFrame,
    ep_table: dict,
    flip_for_defense: bool = False,
) -> pd.DataFrame:
    out = add_epa(df, ep_table)
    # Defense success = opponent failed the offense success test
    out = add_success_flags(out, invert=flip_for_defense)
    if flip_for_defense:
        out["opp_epa"] = out["epa"]
        out["epa"] = -out["epa"]
    return out


def print_side_report(df: pd.DataFrame, side_name: str, group_cols: list[tuple[str, str, int]]) -> None:
    print("\n" + "=" * 60)
    print(f"{side_name.upper()} EPA OVERVIEW")
    print("=" * 60)
    print(f"Average EPA per play: {df['epa'].mean():.3f}")
    print(f"Total EPA (season):   {df['epa'].sum():.1f}")
    print(f"Best single play EPA: {df['epa'].max():.2f}")
    print(f"Worst single play EPA:{df['epa'].min():.2f}")
    print("\nEPA by down (avg):")
    print(df.groupby("down")["epa"].mean().round(3).to_string())
    print("\nEPA by play type (avg):")
    print(df.groupby("play_type")["epa"].mean().round(3).to_string())
    print("\nEPA by field zone (avg):")
    print(df.groupby("field_zone")["epa"].mean().round(3).to_string())
    for col, title, min_p in group_cols:
        print_leaderboard(df, col, title, min_p)


def main() -> None:
    if not DB_FILE.exists():
        print(f"\nMissing database: {DB_FILE}")
        print("Run step2_clean.py first.")
        return

    with sqlite3.connect(DB_FILE) as conn:
        offense = pd.read_sql("SELECT * FROM offense_plays", conn)
        defense = pd.read_sql("SELECT * FROM defense_plays", conn)

    print(f"\nLoaded {len(offense):,} offensive plays")
    print(f"Loaded {len(defense):,} defensive plays")
    print("Building expected points model from offense + defense...")

    ep_table = build_ep_table(pd.concat([offense, defense], ignore_index=True))

    offense_epa = process_side(offense, ep_table, flip_for_defense=False)
    defense_epa = process_side(defense, ep_table, flip_for_defense=True)

    with sqlite3.connect(DB_FILE) as conn:
        offense_epa.to_sql("offense_plays_epa", conn, if_exists="replace", index=False)
        defense_epa.to_sql("defense_plays_epa", conn, if_exists="replace", index=False)

    print(f"\nSaved to: {DB_FILE}")
    print("  offense_plays_epa")
    print("  defense_plays_epa")

    print_side_report(
        offense_epa,
        "offense",
        [
            ("formation", "TOP FORMATIONS", 8),
            ("play_call", "TOP PLAY CALLS", 8),
            ("play_type", "PLAY TYPE", 20),
        ],
    )
    print_side_report(
        defense_epa,
        "defense",
        [
            ("def_call", "TOP FRONT | COVERAGE", 5),
            ("def_front", "TOP FRONTS", 8),
            ("coverage", "TOP COVERAGES", 8),
        ],
    )

    print("\n" + "=" * 60)
    print("NEXT: python -m streamlit run step4_dashboard.py")
    print("=" * 60)


if __name__ == "__main__":
    main()

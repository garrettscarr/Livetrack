"""
Step 2: Clean Hudl season + scout data into SQLite.

Season files (multi-year supported):
  season.xlsx              → current season (primary)
  season_24-25.xlsx        → prior year (optional)
  season_YYYY.xlsx         → any prior label

Scout notes:
  - Same schedule order as season when mapped via scout_opponents.csv
  - New game when PLAY # drops (does NOT need to return to 1 —
    scout often only includes snaps where the opponent was on defense)
  - ODK=D → opponent defense (fronts / coverages) for OUR offense planning
  - ODK=O → opponent offense (formations / play type) for OUR defense planning
"""

from pathlib import Path
import re
import sqlite3

import pandas as pd

from tag_normalize import UNKNOWN_TOKENS as _UNKNOWN_TOKENS
from tag_normalize import normalize_play_call

PROJECT_DIR = Path(__file__).resolve().parent
SCOUT_DIR = PROJECT_DIR / "data" / "hudl_exports"
DATA_FILE = SCOUT_DIR / "season.xlsx"
SCOUT_FILE = SCOUT_DIR / "scout_season.xlsx"  # legacy single-file fallback
OPPONENTS_FILE = PROJECT_DIR / "data" / "opponents.csv"
SCOUT_OPPONENTS_FILE = PROJECT_DIR / "data" / "scout_opponents.csv"
DB_FILE = PROJECT_DIR / "data" / "football.db"

# Required Hudl columns. MOTION / BLITZ are optional (older exports often omit them).
REQUIRED_COLS = {
    "PLAY #": "play_num",
    "ODK": "odk",
    "OFF FORM": "formation",
    "BACKFIELD": "backfield",
    "OFF PLAY": "play_call",
    "PLAY TYPE": "play_type",
    "DN": "down",
    "DIST": "distance",
    "DEF FRONT": "def_front",
    "COVERAGE": "coverage",
    "YARD LN": "yard_line",
    "HASH": "hash",
    "GN/LS": "yards_gained",
    "RESULT": "result",
}
OPTIONAL_COLS = {
    "MOTION": "motion",
    "BLITZ": "blitz",
}
COLUMN_MAP = {**REQUIRED_COLS, **OPTIONAL_COLS}


def yard_line_to_field_position(yard_ln: float) -> float:
    if pd.isna(yard_ln):
        return float("nan")
    if yard_ln <= 0:
        return abs(yard_ln)
    return 100 - yard_ln


def distance_bucket(distance: float) -> str:
    if pd.isna(distance):
        return "unknown"
    if distance <= 3:
        return "short"
    if distance <= 6:
        return "medium"
    return "long"


def field_zone(fp: float) -> str:
    if pd.isna(fp):
        return "unknown"
    if fp <= 20:
        return "backed_up"
    if fp <= 40:
        return "own_territory"
    if fp <= 60:
        return "midfield"
    if fp <= 80:
        return "opp_territory"
    return "red_zone"


def assign_game_ids(play_nums: pd.Series) -> pd.Series:
    """
    New game when PLAY # goes DOWN vs previous row.
    Does not require a reset to 1 — important for scout playlists that
    only include filtered snaps (e.g. opponent defense only).
    """
    game_ids = []
    game_id = 1
    prev = None
    for play_num in play_nums:
        if prev is not None and play_num < prev:
            game_id += 1
        game_ids.append(game_id)
        prev = play_num
    return pd.Series(game_ids, index=play_nums.index)


def _is_tagged(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    return s.ne("") & ~s.str.lower().isin(_UNKNOWN_TOKENS)


def load_opponents(season_label: str = "current") -> pd.DataFrame | None:
    """Load opponents.csv, or opponents_{season}.csv for prior years."""
    path = OPPONENTS_FILE
    if season_label and season_label not in {"current", "25-26"}:
        alt = PROJECT_DIR / "data" / f"opponents_{season_label}.csv"
        if alt.exists():
            path = alt
        else:
            return None
    if not path.exists():
        return None
    opponents = pd.read_csv(path)
    opponents["game_id"] = opponents["game_id"].astype(int)
    if "notes" not in opponents.columns:
        opponents["notes"] = ""
    opponents["notes"] = opponents["notes"].fillna("")
    return opponents[["game_id", "opponent", "notes"]]


def result_flags(result: str) -> dict:
    text = str(result).upper() if pd.notna(result) else ""
    is_td = "TD" in text
    return {
        "is_touchdown": is_td,
        "is_turnover": any(x in text for x in ("INTERCEPTION", "FUMBLE", "INT")),
        "is_penalty": "PENALTY" in text,
        "is_incomplete": "INCOMPLETE" in text,
        "points_scored": 6 if is_td else 0,
    }


def season_label_from_path(path: Path) -> str:
    """season.xlsx → current; season_24-25.xlsx → 24-25."""
    stem = path.stem.strip().lower()
    if stem == "season":
        return "current"
    m = re.match(r"season[_\s\-]*(.+)$", stem, flags=re.I)
    if m:
        return re.sub(r"\s+", "-", m.group(1).strip())
    return stem


def find_season_files() -> list[tuple[Path, str]]:
    """Primary season.xlsx plus optional season_*.xlsx prior-year files."""
    found: list[tuple[Path, str]] = []
    if not SCOUT_DIR.exists():
        return found
    primary = SCOUT_DIR / "season.xlsx"
    if primary.exists():
        found.append((primary, "current"))
    for path in sorted(SCOUT_DIR.glob("season*.xlsx")):
        if path.name.startswith("~$"):
            continue
        if path.name.lower() == "season.xlsx":
            continue
        # Skip legacy scout_season.xlsx
        if path.stem.lower() == "scout_season":
            continue
        found.append((path, season_label_from_path(path)))
    return found


def clean_side(
    raw: pd.DataFrame,
    odk: str,
    side: str,
    *,
    season: str = "current",
    source_file: str = "season.xlsx",
    opponents: pd.DataFrame | None = None,
) -> pd.DataFrame:
    subset = raw[raw["ODK"] == odk].copy()
    missing = [col for col in REQUIRED_COLS if col not in subset.columns]
    if missing:
        raise ValueError(f"Missing columns for {side} ({source_file}): {missing}")

    # Optional columns — pad if older Hudl export omitted them
    for src, dst in OPTIONAL_COLS.items():
        if src not in subset.columns:
            subset[src] = pd.NA

    keep_cols = list(COLUMN_MAP.keys()) + ["game_id"]
    df = subset[keep_cols].rename(columns=COLUMN_MAP)
    df["side"] = side
    df["season"] = season
    df["source_file"] = source_file
    df["field_position"] = df["yard_line"].apply(yard_line_to_field_position)
    df["distance_bucket"] = df["distance"].apply(distance_bucket)
    df["field_zone"] = df["field_position"].apply(field_zone)

    # Collapse inconsistent play spellings before combo keys / tag flags
    df["play_call"] = df["play_call"].apply(
        lambda v: normalize_play_call(v) if pd.notna(v) and str(v).strip() else v
    )

    df["formation_play"] = (
        df["formation"].fillna("Unknown").astype(str)
        + "  |  "
        + df["play_call"].fillna("Unknown").astype(str)
    )
    df["def_call"] = (
        df["def_front"].fillna("Unknown").astype(str)
        + "  |  "
        + df["coverage"].fillna("Unknown").astype(str)
    )

    # Tag quality — prior years are often incomplete; boards filter on these
    df["form_tagged"] = _is_tagged(df["formation"]).astype(int)
    df["play_tagged"] = _is_tagged(df["play_call"]).astype(int)
    # Prior-year formations are untrusted (wrong scheme / bad tags) — never board them.
    # Tagged play calls + all situation/gain rows still feed EPA.
    if str(season).strip().lower() not in {"current", "25-26", ""}:
        df["form_tagged"] = 0
    df["tags_ok"] = ((df["form_tagged"] == 1) & (df["play_tagged"] == 1)).astype(int)
    df["def_tagged"] = (
        _is_tagged(df["def_front"]) & _is_tagged(df["coverage"])
    ).astype(int)

    flags = df["result"].apply(result_flags).apply(pd.Series)
    df = pd.concat([df, flags], axis=1)

    if opponents is not None:
        df = df.merge(opponents, on="game_id", how="left")
        df["opponent"] = df["opponent"].fillna("Unknown")
        df["game_notes"] = df["notes"].fillna("")
        df = df.drop(columns=["notes"])
    else:
        df["opponent"] = "Unknown"
        df["game_notes"] = ""

    before = len(df)
    df = df.dropna(subset=["down", "distance", "field_position"])
    if before - len(df):
        print(
            f"  {side} [{season}]: dropped {before - len(df)} rows "
            "missing down/distance/yard line"
        )

    return df


def find_named_scout_files() -> list[tuple[Path, str, str]]:
    """
    Find scout exports named like:
      Farmersville D.xlsx  → opponent defense (for our offense)
      Farmersville O.xlsx  → opponent offense (for our defense)
    """
    found: list[tuple[Path, str, str]] = []
    if not SCOUT_DIR.exists():
        return found

    for path in sorted(SCOUT_DIR.glob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        stem = path.stem.strip()
        lower = stem.lower()
        # Skip our season film files
        if lower == "season" or lower.startswith("season_") or lower.startswith("season "):
            continue
        if lower in {"scout_season"}:
            continue
        if lower.endswith(" d") or stem.endswith(" D"):
            opponent = stem[:-2].strip()
            found.append((path, opponent, "opponent_defense"))
        elif lower.endswith(" o") or stem.endswith(" O"):
            opponent = stem[:-2].strip()
            found.append((path, opponent, "opponent_offense"))
    return found


def clean_scout_file(
    raw: pd.DataFrame,
    opponent: str,
    scout_role: str,
    source_name: str,
) -> pd.DataFrame:
    """Clean one opponent scout workbook. Role comes from the filename (D/O)."""
    if "game_id" not in raw.columns:
        raw = raw.copy()
        raw["game_id"] = assign_game_ids(raw["PLAY #"])

    missing = [col for col in REQUIRED_COLS if col not in raw.columns]
    if missing:
        raise ValueError(f"Missing columns in {source_name}: {missing}")
    for src in OPTIONAL_COLS:
        if src not in raw.columns:
            raw[src] = pd.NA

    # Prefer rows matching the intended ODK, but keep all if file is mixed
    prefer_odk = "D" if scout_role == "opponent_defense" else "O"
    if "ODK" in raw.columns and (raw["ODK"] == prefer_odk).any():
        subset = raw[raw["ODK"] == prefer_odk].copy()
    else:
        subset = raw.copy()

    df = subset[list(COLUMN_MAP.keys()) + ["game_id"]].rename(columns=COLUMN_MAP)
    df["scout_role"] = scout_role
    df["opponent"] = opponent
    df["source_file"] = source_name
    df["field_position"] = df["yard_line"].apply(yard_line_to_field_position)
    df["distance_bucket"] = df["distance"].apply(distance_bucket)
    df["field_zone"] = df["field_position"].apply(field_zone)
    df["play_call"] = df["play_call"].apply(
        lambda v: normalize_play_call(v) if pd.notna(v) and str(v).strip() else v
    )
    df["formation_play"] = (
        df["formation"].fillna("Unknown").astype(str)
        + "  |  "
        + df["play_call"].fillna("Unknown").astype(str)
    )
    df["def_call"] = (
        df["def_front"].fillna("Unknown").astype(str)
        + "  |  "
        + df["coverage"].fillna("Unknown").astype(str)
    )
    flags = df["result"].apply(result_flags).apply(pd.Series)
    df = pd.concat([df, flags], axis=1)

    before = len(df)
    if scout_role == "opponent_defense":
        # Situation optional — many scout D tags focus on front/coverage
        keep_mask = (
            df["def_front"].notna()
            | df["coverage"].notna()
            | (df["down"].notna() & df["distance"].notna())
        )
    else:
        keep_mask = df["down"].notna() & df["distance"].notna()

    kept = df[keep_mask].copy()
    dropped = before - len(kept)
    if dropped:
        print(f"  {source_name}: dropped {dropped} empty/incomplete rows")

    kept.loc[kept["field_zone"].isna() | (kept["field_zone"] == ""), "field_zone"] = "unknown"
    kept.loc[
        kept["distance_bucket"].isna() | (kept["distance_bucket"] == ""), "distance_bucket"
    ] = "unknown"
    return kept


def import_all_scout() -> pd.DataFrame:
    """Load all `Opponent D/O.xlsx` files; fall back to legacy scout_season.xlsx."""
    named = find_named_scout_files()
    frames: list[pd.DataFrame] = []

    if named:
        print(f"\nLoading named scout files ({len(named)}):")
        for path, opponent, role in named:
            print(f"  {path.name} -> {opponent} / {role}")
            raw = pd.read_excel(path)
            raw["game_id"] = assign_game_ids(raw["PLAY #"])
            print(f"    rows={len(raw):,}  scout cuts={raw['game_id'].nunique()}")
            frames.append(clean_scout_file(raw, opponent, role, path.name))
    elif SCOUT_FILE.exists():
        print(f"\nLoading legacy scout file: {SCOUT_FILE.name}")
        print("  Tip: prefer files named like 'Farmersville D.xlsx' and 'Farmersville O.xlsx'")
        raw = pd.read_excel(SCOUT_FILE)
        raw["game_id"] = assign_game_ids(raw["PLAY #"])
        # Split by ODK inside the file
        for odk, role in (("D", "opponent_defense"), ("O", "opponent_offense")):
            part = raw[raw["ODK"] == odk].copy()
            if part.empty:
                continue
            frames.append(clean_scout_file(part, "", role, SCOUT_FILE.name))
    else:
        print("\nNo scout files found.")
        print("  Add files like: data/hudl_exports/Farmersville D.xlsx")
        print("                  data/hudl_exports/Farmersville O.xlsx")
        return pd.DataFrame()

    if not frames:
        return pd.DataFrame()

    scout_df = pd.concat(frames, ignore_index=True)
    return scout_df


def print_side_summary(df: pd.DataFrame, side: str) -> None:
    print("\n" + "=" * 60)
    print(f"QUICK SUMMARY ({side})")
    print("=" * 60)
    print(f"\nPlays: {len(df):,}")
    if "season" in df.columns:
        print("\nBy season:")
        print(df["season"].value_counts().to_string())
        if "tags_ok" in df.columns:
            print("\nTag quality (form+play both tagged):")
            for season, grp in df.groupby("season"):
                ok = int(grp["tags_ok"].sum())
                print(f"  {season}: {ok}/{len(grp)} ({100*ok/max(1,len(grp)):.0f}%)")
    print("\nPlays by down:")
    print(df["down"].value_counts().sort_index().to_string())
    print("\nRun / Pass (opponent)" if side == "defense" else "\nRun / Pass:")
    print(df["play_type"].value_counts(dropna=False).to_string())

    if side == "offense":
        tagged = df[df.get("form_tagged", 1) == 1] if "form_tagged" in df.columns else df
        print("\nTop formations (tagged only):")
        print(tagged["formation"].value_counts(dropna=False).head(8).to_string())
        play_tagged = df[df.get("play_tagged", 1) == 1] if "play_tagged" in df.columns else df
        print("\nTop play calls (tagged only):")
        print(play_tagged["play_call"].value_counts(dropna=False).head(8).to_string())
    else:
        print("\nTop defensive fronts:")
        print(df["def_front"].value_counts(dropna=False).head(8).to_string())
        print("\nTop coverages:")
        print(df["coverage"].value_counts(dropna=False).head(8).to_string())
        print("\nTop front | coverage calls:")
        print(df["def_call"].value_counts(dropna=False).head(8).to_string())


def import_all_season() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load current + prior season Hudl files into offense/defense frames."""
    files = find_season_files()
    if not files:
        raise FileNotFoundError(
            f"No season.xlsx (or season_*.xlsx) in {SCOUT_DIR}. "
            "Export Hudl film and save it there."
        )

    off_frames: list[pd.DataFrame] = []
    def_frames: list[pd.DataFrame] = []
    game_offset = 0

    print(f"\nLoading {len(files)} season file(s):")
    for path, season in files:
        print(f"\n  {path.name} → season={season}")
        raw = pd.read_excel(path)
        local_ids = assign_game_ids(raw["PLAY #"])
        raw = raw.copy()
        raw["game_id"] = local_ids + game_offset
        n_games = int(local_ids.nunique())
        print(f"    rows={len(raw):,}  games={n_games}  game_id {game_offset+1}–{game_offset+n_games}")

        opponents = load_opponents(season)
        if opponents is not None:
            # Shift opponent map to match offset game_ids
            opp = opponents.copy()
            opp["game_id"] = opp["game_id"] + game_offset
        else:
            opp = None
            if season != "current":
                print(
                    f"    note: no opponents_{season}.csv — opponents left Unknown "
                    "(EPA still uses these snaps)"
                )

        offense = clean_side(
            raw, "O", "offense", season=season, source_file=path.name, opponents=opp
        )
        defense = clean_side(
            raw, "D", "defense", season=season, source_file=path.name, opponents=opp
        )
        print(
            f"    kept O={len(offense):,} D={len(defense):,} · "
            f"tags_ok O={int(offense['tags_ok'].sum())}/{len(offense)} "
            f"({100*offense['tags_ok'].mean():.0f}%)"
        )
        off_frames.append(offense)
        def_frames.append(defense)
        game_offset += n_games

    offense = pd.concat(off_frames, ignore_index=True)
    defense = pd.concat(def_frames, ignore_index=True)
    return offense, defense


def main() -> None:
    try:
        offense, defense = import_all_season()
    except FileNotFoundError as exc:
        print(f"\n{exc}")
        return

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        offense.to_sql("offense_plays", conn, if_exists="replace", index=False)
        defense.to_sql("defense_plays", conn, if_exists="replace", index=False)

        scout_df = import_all_scout()
        if not scout_df.empty:
            scout_df.to_sql("scout_plays", conn, if_exists="replace", index=False)
            opp_d = scout_df[scout_df["scout_role"] == "opponent_defense"]
            opp_o = scout_df[scout_df["scout_role"] == "opponent_offense"]
            print(f"\n  scout_plays saved: {len(scout_df):,}")
            print(f"    opponent_defense (for our offense): {len(opp_d):,}")
            print(f"    opponent_offense (for our defense): {len(opp_o):,}")
            print(f"    opponents: {sorted(scout_df['opponent'].dropna().unique().tolist())}")
            if not opp_d.empty:
                print("\n  Farmersville-style D — top fronts:")
                print(opp_d["def_front"].value_counts(dropna=False).head(8).to_string())
                print("\n  top coverages:")
                print(opp_d["coverage"].value_counts(dropna=False).head(8).to_string())
            if not opp_o.empty:
                print("\n  O scout — run/pass:")
                print(opp_o["play_type"].value_counts(dropna=False).head(5).to_string())
                print("\n  O scout — top formations:")
                print(opp_o["formation"].value_counts(dropna=False).head(8).to_string())
        else:
            # clear old scout table if files removed
            conn.execute("DROP TABLE IF EXISTS scout_plays")
            print("\n  No scout plays imported (old scout table cleared)")

    print(f"\nSaved to: {DB_FILE}")
    print(f"  offense_plays: {len(offense):,} rows")
    print(f"  defense_plays: {len(defense):,} rows")

    print_side_summary(offense, "offense")
    print_side_summary(defense, "defense")

    print("\n" + "=" * 60)
    print("NEXT: python step3_epa.py")
    print("=" * 60)
    print("Note: EPA uses all snaps with situation. Formation/play boards")
    print("      filter to tagged rows (tags_ok / form_tagged / play_tagged).")


if __name__ == "__main__":
    main()

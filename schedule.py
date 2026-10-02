"""
Season schedule (opponents.csv) helpers.

Active season → data/opponents.csv
Prior seasons → data/opponents_{id}.csv (e.g. opponents_25-26.csv)

Hudl import assigns game_id by PLAY # drops; this schedule maps
game_id → opponent / notes. Edit here, then Apply to DB or re-run refresh.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
OPPONENTS_FILE = DATA_DIR / "opponents.csv"
DB_FILE = DATA_DIR / "football.db"

_EMPTY_COLS = ["game_id", "opponent", "notes"]


def _season_api():
    import importlib

    import team_config as tc

    needed = (
        "current_season_id",
        "is_current_season_value",
        "current_season_aliases",
        "season_block",
        "set_current_season",
    )
    if any(not hasattr(tc, name) for name in needed):
        tc = importlib.reload(tc)
    return tc


def schedule_path(season_id: str | None = None) -> Path:
    """Path for a season's schedule CSV."""
    tc = _season_api()
    sid = str(season_id or tc.current_season_id()).strip()
    if tc.is_current_season_value(sid) or sid.lower() in {"current", ""}:
        return OPPONENTS_FILE
    return DATA_DIR / f"opponents_{sid}.csv"


def empty_schedule() -> pd.DataFrame:
    return pd.DataFrame(columns=_EMPTY_COLS)


def _normalize_schedule(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_schedule()
    out = df.copy()
    if "game_id" not in out.columns:
        out["game_id"] = range(1, len(out) + 1)
    if "opponent" not in out.columns:
        out["opponent"] = ""
    if "notes" not in out.columns:
        out["notes"] = ""
    out["game_id"] = pd.to_numeric(out["game_id"], errors="coerce")
    out = out[out["game_id"].notna()].copy()
    out["game_id"] = out["game_id"].astype(int)
    out["opponent"] = out["opponent"].fillna("").astype(str).str.strip()
    out["notes"] = out["notes"].fillna("").astype(str).str.strip()
    out = out[out["opponent"].ne("")]
    out = out.drop_duplicates(subset=["game_id"], keep="last")
    return out.sort_values("game_id").reset_index(drop=True)[_EMPTY_COLS]


def load_schedule(season_id: str | None = None) -> pd.DataFrame:
    path = schedule_path(season_id)
    if not path.exists():
        return empty_schedule()
    try:
        return _normalize_schedule(pd.read_csv(path))
    except Exception:
        return empty_schedule()


def save_schedule(df: pd.DataFrame, season_id: str | None = None) -> Path:
    path = schedule_path(season_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = _normalize_schedule(df)
    # Re-number if gaps? Keep explicit game_ids so Hudl mapping stays stable.
    if clean.empty:
        clean = empty_schedule()
    clean.to_csv(path, index=False)
    return path


def list_schedule_season_ids() -> list[str]:
    """Known schedule seasons: active id + any opponents_*.csv on disk."""
    tc = _season_api()
    ids: list[str] = []
    cur = tc.current_season_id()
    if cur:
        ids.append(cur)
    if OPPONENTS_FILE.exists() and cur not in ids:
        ids.append(cur)
    for path in sorted(DATA_DIR.glob("opponents_*.csv")):
        stem = path.stem  # opponents_25-26
        if stem.startswith("opponents_"):
            sid = stem[len("opponents_") :]
            if sid and sid not in ids:
                ids.append(sid)
    return ids


def ensure_prior_schedule_archived(prior_id: str | None = None) -> Path | None:
    """
    If opponents_{prior}.csv is missing, copy active opponents.csv there
    so rolling years doesn't lose the old schedule.
    """
    tc = _season_api()
    pid = str(prior_id or (tc.season_block().get("prior_id") or "")).strip()
    if not pid or tc.is_current_season_value(pid):
        return None
    dest = DATA_DIR / f"opponents_{pid}.csv"
    if dest.exists() or not OPPONENTS_FILE.exists():
        return dest if dest.exists() else None
    dest.write_text(OPPONENTS_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def start_new_season_schedule(
    *,
    new_season_id: str,
    new_season_label: str | None = None,
    blank: bool = True,
    seed_from: str | None = None,
) -> dict:
    """
    Archive active schedule under prior_id (if needed), flip team_config season,
    write a new opponents.csv (blank or copied).
    """
    tc = _season_api()
    new_id = str(new_season_id or "").strip()
    if not new_id:
        raise ValueError("New season id required (e.g. 26-27).")
    old_id = tc.current_season_id()
    if new_id.lower() == old_id.lower():
        raise ValueError(f"Season {new_id} is already active.")

    # Preserve current schedule under the season we're leaving
    if OPPONENTS_FILE.exists():
        archive = DATA_DIR / f"opponents_{old_id}.csv"
        if not archive.exists():
            archive.write_text(OPPONENTS_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    if blank:
        sched = empty_schedule()
    else:
        src = seed_from or old_id
        sched = load_schedule(src)
        if sched.empty and src != old_id:
            sched = load_schedule(old_id)

    tc.set_current_season(new_id, new_season_label or new_id)
    save_schedule(sched, new_id)  # writes opponents.csv for active
    return {
        "old_season": old_id,
        "new_season": new_id,
        "games": int(len(sched)),
        "blank": blank,
    }


def next_game_id(df: pd.DataFrame) -> int:
    if df is None or df.empty or "game_id" not in df.columns:
        return 1
    ids = pd.to_numeric(df["game_id"], errors="coerce").dropna()
    return int(ids.max()) + 1 if len(ids) else 1


def add_schedule_game(
    df: pd.DataFrame,
    opponent: str,
    *,
    notes: str = "",
    playoff: bool = False,
) -> pd.DataFrame:
    name = str(opponent or "").strip()
    if not name:
        raise ValueError("Opponent name required.")
    note = str(notes or "").strip()
    if playoff and "playoff" not in note.lower():
        note = "Playoffs" if not note else f"{note}; Playoffs"
    row = {"game_id": next_game_id(df), "opponent": name, "notes": note}
    base = _normalize_schedule(df)
    return _normalize_schedule(pd.concat([base, pd.DataFrame([row])], ignore_index=True))


def detected_hudl_games(season_id: str | None = None, table: str = "offense_plays") -> pd.DataFrame:
    """game_id aggregates from DB for a season (for Hudl → schedule mapping UI)."""
    if not DB_FILE.exists():
        return pd.DataFrame(columns=["game_id", "plays", "opponent", "game_notes"])
    tc = _season_api()
    sid = str(season_id or tc.current_season_id()).strip()
    aliases = tc.current_season_aliases() if tc.is_current_season_value(sid) else {sid.lower()}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            df = pd.read_sql(f"SELECT game_id, opponent, game_notes, season FROM {table}", conn)
    except Exception:
        return pd.DataFrame(columns=["game_id", "plays", "opponent", "game_notes"])
    if df.empty or "game_id" not in df.columns:
        return pd.DataFrame(columns=["game_id", "plays", "opponent", "game_notes"])
    if "season" in df.columns:
        s = df["season"].fillna("").astype(str).str.strip().str.lower()
        df = df[s.isin(aliases) | (s == sid.lower())]
    df["game_id"] = pd.to_numeric(df["game_id"], errors="coerce")
    df = df[df["game_id"].notna()]
    if df.empty:
        return pd.DataFrame(columns=["game_id", "plays", "opponent", "game_notes"])
    rows = []
    for gid, grp in df.groupby(df["game_id"].astype(int)):
        opp = ""
        notes = ""
        if "opponent" in grp.columns:
            vals = grp["opponent"].dropna().astype(str).str.strip()
            vals = vals[vals.ne("") & ~vals.str.lower().isin({"unknown", "nan"})]
            if len(vals):
                opp = str(vals.mode().iloc[0])
        if "game_notes" in grp.columns:
            nvals = grp["game_notes"].dropna().astype(str).str.strip()
            nvals = nvals[nvals.ne("") & ~nvals.str.lower().isin({"nan"})]
            if len(nvals):
                notes = str(nvals.mode().iloc[0])
        rows.append(
            {
                "game_id": int(gid),
                "plays": int(len(grp)),
                "opponent": opp,
                "game_notes": notes,
            }
        )
    return pd.DataFrame(rows).sort_values("game_id").reset_index(drop=True)


def apply_schedule_to_db(
    schedule_df: pd.DataFrame,
    season_id: str | None = None,
    tables: tuple[str, ...] = ("offense_plays", "defense_plays", "offense_plays_epa", "defense_plays_epa"),
) -> int:
    """
    Patch opponent / game_notes on DB rows for this season by game_id.
    Returns number of row updates across tables.
    """
    if not DB_FILE.exists():
        return 0
    sched = _normalize_schedule(schedule_df)
    if sched.empty:
        return 0
    tc = _season_api()
    sid = str(season_id or tc.current_season_id()).strip()
    aliases = tc.current_season_aliases() if tc.is_current_season_value(sid) else {sid.lower()}
    # Also match literal season stamp
    aliases = set(aliases) | {sid.lower(), "current", ""}

    updated = 0
    with sqlite3.connect(DB_FILE) as conn:
        for table in tables:
            try:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            except Exception:
                continue
            if "game_id" not in cols or "opponent" not in cols:
                continue
            has_notes = "game_notes" in cols
            has_season = "season" in cols
            for row in sched.itertuples(index=False):
                gid = int(row.game_id)
                opp = str(row.opponent)
                notes = str(row.notes)
                if has_season:
                    # Update rows whose season is in aliases
                    placeholders = ",".join("?" * len(aliases))
                    if has_notes:
                        cur = conn.execute(
                            f"UPDATE {table} SET opponent=?, game_notes=? "
                            f"WHERE game_id=? AND lower(coalesce(season,'')) IN ({placeholders})",
                            [opp, notes, gid, *[a.lower() for a in aliases]],
                        )
                    else:
                        cur = conn.execute(
                            f"UPDATE {table} SET opponent=? "
                            f"WHERE game_id=? AND lower(coalesce(season,'')) IN ({placeholders})",
                            [opp, gid, *[a.lower() for a in aliases]],
                        )
                else:
                    if has_notes:
                        cur = conn.execute(
                            f"UPDATE {table} SET opponent=?, game_notes=? WHERE game_id=?",
                            [opp, notes, gid],
                        )
                    else:
                        cur = conn.execute(
                            f"UPDATE {table} SET opponent=? WHERE game_id=?",
                            [opp, gid],
                        )
                updated += int(cur.rowcount or 0)
        conn.commit()
    return updated


def migrate_legacy_current_to_prior(
    *,
    prior_id: str | None = None,
    tables: tuple[str, ...] = (
        "offense_plays",
        "defense_plays",
        "offense_plays_epa",
        "defense_plays_epa",
        "scout_plays",
    ),
) -> dict:
    """
    Re-stamp DB rows labeled season='current' (or blank) as the prior season id.

    Needed after rolling team_config to a new year while old Hudl was still
    imported as season.xlsx → 'current'.
    """
    tc = _season_api()
    pid = str(prior_id or (tc.season_block().get("prior_id") or "")).strip()
    if not pid:
        raise ValueError("No prior_id set in team_config.season")
    if tc.is_current_season_value(pid):
        raise ValueError(f"prior_id {pid} still looks like the active season")
    if not DB_FILE.exists():
        return {"prior_id": pid, "updated": 0}

    updated = 0
    with sqlite3.connect(DB_FILE) as conn:
        for table in tables:
            try:
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            except Exception:
                continue
            if "season" not in cols:
                continue
            cur = conn.execute(
                f"UPDATE {table} SET season=? "
                f"WHERE lower(coalesce(trim(season),'')) IN ('current','')",
                [pid],
            )
            updated += int(cur.rowcount or 0)
        conn.commit()

    # Attach the archived schedule labels to those games
    sched = load_schedule(pid)
    labeled = 0
    if not sched.empty:
        labeled = apply_schedule_to_db(sched, pid)

    return {"prior_id": pid, "updated": updated, "labeled": labeled}

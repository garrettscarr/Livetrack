"""
Promote finished Live Track logs into Game Review (offense_plays / EPA).

Live snaps live in data/live_log.csv. When a new game starts, the finished
log is archived and also written under data/live_games/ so it survives
refresh_all (Hudl replace). Remerge restores live-sourced rows afterward.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "football.db"
LIVE_GAMES_DIR = PROJECT_DIR / "data" / "live_games"
LIVE_LOG_ARCHIVE_DIR = PROJECT_DIR / "data" / "live_log_archive"
LIVE_SOURCE_PREFIX = "live:"


def _safe_name(text: str) -> str:
    s = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in str(text or "")).strip()
    return re.sub(r"\s+", "_", s) or "game"


def _season_id() -> str:
    try:
        from team_config import current_season_id

        return str(current_season_id())
    except Exception:
        return "current"


def finished_opponent_from_log(df: pd.DataFrame | None) -> str:
    if df is None or df.empty or "opponent" not in df.columns:
        return ""
    vals = df["opponent"].dropna().astype(str).str.strip()
    vals = vals[vals.ne("") & ~vals.str.lower().isin({"nan", "none", "unknown"})]
    if vals.empty:
        return ""
    return str(vals.mode().iloc[0])


def _play_type_label(raw: str) -> str:
    t = str(raw or "").strip().lower()
    if t in {"pass", "p"}:
        return "Pass"
    if t in {"run", "r"}:
        return "Run"
    if t in {"rpo"}:
        return "RPO"
    if t in {"special", "st"}:
        return "Special"
    return "Run" if t else "Run"


def _live_result_to_hudl(result: str, play_type: str) -> str:
    r = str(result or "").strip()
    pt = str(play_type or "").strip().lower()
    if r == "TD":
        return "Rush, TD" if pt == "run" else "Complete, TD"
    if r == "Incomplete":
        return "Incomplete"
    if r == "Penalty":
        return "Penalty"
    if r == "Turnover":
        return "Interception"
    if r.startswith("Sack"):
        return "Sack"
    if r == "Punt":
        return "Punt"
    if r == "No gain":
        return "Rush" if pt == "run" else "Complete"
    if pt == "pass":
        return "Complete"
    return "Rush"


def _ball_to_yard_line(fp: float) -> float:
    y = max(1.0, min(99.0, float(fp)))
    if y <= 50:
        return -y
    return 100.0 - y


def _distance_yards(row: pd.Series) -> float:
    raw = row.get("distance_yards")
    try:
        if raw is not None and str(raw).strip() != "" and not pd.isna(raw):
            return float(raw)
    except (TypeError, ValueError):
        pass
    bucket = str(row.get("distance") or "").strip().lower()
    return {"short": 2.0, "medium": 5.0, "long": 10.0}.get(bucket, 10.0)


def live_log_to_offense_plays(
    df: pd.DataFrame,
    *,
    game_id: int,
    opponent: str,
    season: str | None = None,
    source_file: str | None = None,
) -> pd.DataFrame:
    """Map Live Track offense rows → offense_plays schema (no EPA yet)."""
    from step2_clean import distance_bucket, field_zone, result_flags

    if df is None or df.empty:
        return pd.DataFrame()

    work = df.copy()
    if "unit" in work.columns:
        work = work[work["unit"].astype(str).str.strip().str.lower() == "offense"]
    if work.empty:
        return pd.DataFrame()

    # Skip pure special-teams outcomes that don't belong on offense EPA boards
    if "result" in work.columns:
        skip = work["result"].astype(str).str.strip().str.lower().isin({"punt"})
        work = work[~skip]
    if work.empty:
        return pd.DataFrame()

    sid = season or _season_id()
    src = source_file or f"{LIVE_SOURCE_PREFIX}{_safe_name(opponent)}.csv"
    rows: list[dict] = []
    for i, (_, row) in enumerate(work.reset_index(drop=True).iterrows(), start=1):
        try:
            fp = float(row.get("ball_yard"))
        except (TypeError, ValueError):
            zone = str(row.get("field_zone") or "midfield")
            fp = {"backed_up": 15, "own_territory": 35, "midfield": 50, "opp_territory": 65, "red_zone": 85}.get(
                zone, 50
            )
        fp = max(1.0, min(99.0, fp))
        dist = _distance_yards(row)
        try:
            down = int(float(row.get("down") or 1))
        except (TypeError, ValueError):
            down = 1
        down = max(1, min(4, down))
        try:
            yards = float(row.get("yards_gained") or 0)
        except (TypeError, ValueError):
            yards = 0.0
        play_type = _play_type_label(row.get("play_type"))
        hudl_result = _live_result_to_hudl(str(row.get("result") or ""), play_type)
        formation = str(row.get("formation") or "").strip()
        play_call = str(row.get("play_call") or "").strip()
        motion = str(row.get("motion") or "").strip()
        def_front = str(row.get("def_front") or "").strip()
        coverage = str(row.get("coverage") or "").strip()
        blitz = row.get("blitz")
        blitz_s = "" if blitz is None or (isinstance(blitz, float) and pd.isna(blitz)) else str(blitz).strip()
        flags = result_flags(hudl_result)
        form_ok = 1 if formation and formation.lower() not in {"unknown", "nan", "?"} else 0
        play_ok = 1 if play_call and play_call.lower() not in {"unknown", "nan", "?"} else 0
        rows.append(
            {
                "play_num": i,
                "odk": "O",
                "formation": formation or "Unknown",
                "backfield": "",
                "play_call": play_call or "Unknown",
                "play_type": play_type,
                "down": down,
                "distance": dist,
                "def_front": def_front or "Unknown",
                "coverage": coverage or "Unknown",
                "yard_line": _ball_to_yard_line(fp),
                "hash": "",
                "yards_gained": yards,
                "result": hudl_result,
                "motion": motion,
                "blitz": blitz_s,
                "game_id": int(game_id),
                "side": "offense",
                "season": sid,
                "source_file": src,
                "field_position": fp,
                "distance_bucket": distance_bucket(dist),
                "field_zone": field_zone(fp),
                "formation_play": f"{formation or 'Unknown'}  |  {play_call or 'Unknown'}",
                "def_call": f"{def_front or 'Unknown'}  |  {coverage or 'Unknown'}",
                "form_tagged": form_ok,
                "play_tagged": play_ok,
                "tags_ok": int(form_ok and play_ok),
                "def_tagged": int(
                    bool(def_front and def_front.lower() not in {"unknown", "nan", "?"})
                    and bool(coverage and coverage.lower() not in {"unknown", "nan", "?"})
                ),
                "is_touchdown": flags["is_touchdown"],
                "is_turnover": flags["is_turnover"],
                "is_penalty": flags["is_penalty"],
                "is_incomplete": flags["is_incomplete"],
                "points_scored": flags["points_scored"],
                "opponent": opponent,
                "game_notes": "Live Track",
            }
        )
    return pd.DataFrame(rows)


def _resolve_game_id(opponent: str) -> int:
    from schedule import add_schedule_game, load_schedule, save_schedule

    name = str(opponent or "").strip()
    sched = load_schedule(None)
    if not sched.empty:
        hit = sched[sched["opponent"].astype(str).str.strip().str.lower() == name.lower()]
        if not hit.empty:
            return int(hit.iloc[0]["game_id"])
    sched = add_schedule_game(sched, name, notes="Live Track")
    save_schedule(sched, None)
    return int(sched.iloc[-1]["game_id"])


def _hudl_has_game(game_id: int, season: str, opponent: str = "") -> bool:
    """True if non-live (Hudl) rows already exist for this schedule game / opponent."""
    if not DB_FILE.exists():
        return False
    try:
        with sqlite3.connect(DB_FILE) as conn:
            df = pd.read_sql(
                "SELECT game_id, season, source_file, opponent FROM offense_plays",
                conn,
            )
    except Exception:
        return False
    if df.empty:
        return False
    if "season" in df.columns:
        s = df["season"].fillna("").astype(str).str.strip().str.lower()
        df = df[(s == str(season).lower()) | (s == "current") | (s == "")]
    if df.empty:
        return False
    src = df["source_file"].fillna("").astype(str)
    hudl = df[~src.str.startswith(LIVE_SOURCE_PREFIX)].copy()
    if hudl.empty:
        return False
    # Prefer opponent match when available (avoids game_id collisions across sources)
    opp = str(opponent or "").strip().lower()
    if opp and "opponent" in hudl.columns:
        om = hudl["opponent"].fillna("").astype(str).str.strip().str.lower()
        if (om == opp).any():
            return True
        # Different opponent on same game_id → not a Hudl conflict for this live game
        gid_hit = hudl["game_id"].astype(str) == str(int(game_id))
        if gid_hit.any():
            return False
    return bool((hudl["game_id"].astype(str) == str(int(game_id))).any())


def live_game_path(opponent: str, game_id: int, season: str | None = None) -> Path:
    sid = season or _season_id()
    return LIVE_GAMES_DIR / f"{_safe_name(sid)}_g{int(game_id)}_{_safe_name(opponent)}.csv"


def save_live_game_csv(plays: pd.DataFrame, path: Path) -> Path:
    LIVE_GAMES_DIR.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    plays.to_csv(path, index=False)
    return path


def _ep_table_for_live(plays: pd.DataFrame) -> dict:
    from step3_epa import build_ep_table

    try:
        with sqlite3.connect(DB_FILE) as conn:
            season = pd.read_sql("SELECT * FROM offense_plays", conn)
    except Exception:
        season = pd.DataFrame()
    if season.empty:
        return build_ep_table(plays) if not plays.empty else {}
    return build_ep_table(pd.concat([season, plays], ignore_index=True))


def _add_epa_rows(plays: pd.DataFrame) -> pd.DataFrame:
    from step3_epa import add_epa, add_success_flags

    if plays.empty:
        return plays
    ep = _ep_table_for_live(plays)
    return add_success_flags(add_epa(plays, ep), invert=False)


def _replace_live_in_table(conn: sqlite3.Connection, table: str, plays: pd.DataFrame, source_file: str) -> None:
    try:
        existing = pd.read_sql(f"SELECT * FROM {table}", conn)
    except Exception:
        existing = pd.DataFrame()
    if not existing.empty and "source_file" in existing.columns:
        keep = existing[existing["source_file"].fillna("").astype(str) != source_file].copy()
    else:
        keep = existing.copy() if existing is not None else pd.DataFrame()

    if plays is None or plays.empty:
        merged = keep
    elif keep.empty:
        merged = plays.copy()
    else:
        cols = list(dict.fromkeys(list(keep.columns) + list(plays.columns)))
        merged = pd.concat(
            [keep.reindex(columns=cols), plays.reindex(columns=cols)],
            ignore_index=True,
        )

    if merged is None or merged.empty:
        if not existing.empty:
            existing.iloc[0:0].to_sql(table, conn, if_exists="replace", index=False)
        return
    merged.to_sql(table, conn, if_exists="replace", index=False)


def merge_live_plays_into_db(plays: pd.DataFrame) -> dict:
    """Replace this live source_file in offense_plays + offense_plays_epa."""
    if plays is None or plays.empty:
        return {"merged": False, "plays": 0, "reason": "empty"}
    src = str(plays.iloc[0].get("source_file") or "")
    if not src.startswith(LIVE_SOURCE_PREFIX):
        src = f"{LIVE_SOURCE_PREFIX}game.csv"
        plays = plays.copy()
        plays["source_file"] = src
    epa = _add_epa_rows(plays)
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        _replace_live_in_table(conn, "offense_plays", plays, src)
        _replace_live_in_table(conn, "offense_plays_epa", epa, src)
    return {"merged": True, "plays": int(len(plays)), "source_file": src}


def promote_live_log_to_game_review(
    log_df: pd.DataFrame | None,
    *,
    force: bool = False,
) -> dict:
    """
    Persist a finished live log into data/live_games/ and Game Review tables.
    Skips merge when Hudl already has that schedule game_id (unless force).
    """
    out: dict = {
        "promoted": False,
        "merged": False,
        "plays": 0,
        "opponent": "",
        "game_id": None,
        "path": None,
        "reason": "",
    }
    if log_df is None or log_df.empty:
        out["reason"] = "empty_log"
        return out

    opponent = finished_opponent_from_log(log_df)
    if not opponent:
        out["reason"] = "no_opponent"
        return out

    plays_preview = live_log_to_offense_plays(log_df, game_id=0, opponent=opponent)
    if plays_preview.empty:
        out["reason"] = "no_offense_plays"
        out["opponent"] = opponent
        return out

    season = _season_id()
    game_id = _resolve_game_id(opponent)
    src = f"{LIVE_SOURCE_PREFIX}{_safe_name(opponent)}.csv"
    plays = live_log_to_offense_plays(
        log_df, game_id=game_id, opponent=opponent, season=season, source_file=src
    )
    path = live_game_path(opponent, game_id, season)
    save_live_game_csv(plays, path)
    out.update(
        {
            "opponent": opponent,
            "game_id": int(game_id),
            "plays": int(len(plays)),
            "path": str(path),
            "promoted": True,
        }
    )

    if not force and _hudl_has_game(game_id, season, opponent=opponent):
        out["reason"] = "hudl_exists"
        out["merged"] = False
        return out

    merge = merge_live_plays_into_db(plays)
    out["merged"] = bool(merge.get("merged"))
    out["reason"] = "ok" if out["merged"] else str(merge.get("reason") or "merge_failed")
    return out


def list_saved_live_games() -> list[Path]:
    if not LIVE_GAMES_DIR.exists():
        return []
    return sorted(LIVE_GAMES_DIR.glob("*.csv"))


def remerge_all_live_games(*, skip_hudl_conflicts: bool = True) -> dict:
    """After refresh_all, re-append saved live games into the DB."""
    files = list_saved_live_games()
    merged = 0
    skipped = 0
    plays = 0
    for path in files:
        try:
            df = pd.read_csv(path)
        except Exception:
            skipped += 1
            continue
        if df.empty:
            skipped += 1
            continue
        game_id = int(pd.to_numeric(df.get("game_id"), errors="coerce").dropna().iloc[0]) if "game_id" in df.columns else 0
        season = str(df.iloc[0].get("season") or _season_id())
        opp = str(df.iloc[0].get("opponent") or "")
        if skip_hudl_conflicts and game_id and _hudl_has_game(game_id, season, opponent=opp):
            skipped += 1
            continue
        info = merge_live_plays_into_db(df)
        if info.get("merged"):
            merged += 1
            plays += int(info.get("plays") or 0)
        else:
            skipped += 1
    return {"files": len(files), "merged": merged, "skipped": skipped, "plays": plays}

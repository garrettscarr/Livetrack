"""
Mesh engine: season EPA + scout tendencies + live log adjustments.

Scout roles:
  opponent_defense (ODK=D) → their fronts/coverages → helps OUR offense
  opponent_offense (ODK=O) → their formations/run-pass → helps OUR defense
"""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "football.db"
LIVE_LOG_FILE = PROJECT_DIR / "data" / "live_log.csv"
OPPONENTS_FILE = PROJECT_DIR / "data" / "opponents.csv"


def _is_current_season_value(value) -> bool:
    """Resolve season helper even if Streamlit cached an older team_config."""
    import importlib

    import team_config as tc

    if not hasattr(tc, "is_current_season_value"):
        tc = importlib.reload(tc)
    return tc.is_current_season_value(value)


def _current_season_aliases() -> set[str]:
    import importlib

    import team_config as tc

    if not hasattr(tc, "current_season_aliases"):
        tc = importlib.reload(tc)
    return tc.current_season_aliases()


def load_table(sql: str) -> pd.DataFrame:
    if not DB_FILE.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_FILE) as conn:
        try:
            return pd.read_sql(sql, conn)
        except Exception:
            return pd.DataFrame()


def load_scout(
    role: str | None = None,
    opponent: str | None = None,
    *,
    season: str | None = "current",
) -> pd.DataFrame:
    """Load scout plays. season='current' (default), a label like '24-25', or 'all'."""
    df = load_table("SELECT * FROM scout_plays")
    if df.empty:
        return df
    if role:
        df = df[df["scout_role"] == role]
    if opponent and str(opponent).strip() and "opponent" in df.columns:
        df = df[df["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()]
    if season and str(season).strip().lower() != "all" and "season" in df.columns:
        want = str(season).strip().lower()
        # Coerce to python strings — Arrow large_string breaks bool OR masks
        season_s = df["season"].astype(object)
        if want in {"current", ""} or want in _current_season_aliases():
            mask = season_s.map(_is_current_season_value).fillna(False).astype(bool)
            # Legacy rows with no season stamp count as current
            stripped = season_s.where(season_s.notna(), "").astype(str).str.strip()
            missing = season_s.isna() | (stripped == "") | (stripped.str.lower() == "nan")
            missing = missing.fillna(False).astype(bool)
            df = df[mask.to_numpy() | missing.to_numpy()]
        else:
            s = season_s.fillna("").astype(str).str.strip().str.lower()
            df = df[s == want]
    return df


def load_season_opponents() -> list[str]:
    """Ordered opponent names from the active season schedule."""
    try:
        from schedule import load_schedule

        sched = load_schedule(None)
        if not sched.empty and "opponent" in sched.columns:
            return [str(x) for x in sched["opponent"].tolist() if str(x).strip()]
    except Exception:
        pass
    if not OPPONENTS_FILE.exists():
        return []
    opps = pd.read_csv(OPPONENTS_FILE)
    return [str(x) for x in opps["opponent"].tolist()]


def filter_situation(
    df: pd.DataFrame,
    down: int | None,
    distance_bucket: str | None,
    field_zone: str | None,
) -> pd.DataFrame:
    out = df.copy()
    if down is not None and "down" in out.columns:
        out = out[out["down"] == down]
    if distance_bucket and distance_bucket != "Any" and "distance_bucket" in out.columns:
        out = out[out["distance_bucket"] == distance_bucket.lower()]
    if field_zone and field_zone != "Any" and "field_zone" in out.columns:
        out = out[out["field_zone"] == field_zone.lower()]
    return out


def broaden_situation(
    df: pd.DataFrame,
    down: int,
    dist: str,
    zone: str,
    *,
    exact_min: int = 10,
    down_dist_min: int = 10,
    down_min: int = 5,
) -> tuple[pd.DataFrame, str]:
    """Prefer exact situation, then widen until enough plays exist."""
    matched = filter_situation(df, down, dist, zone)
    if len(matched) >= exact_min:
        return matched, "exact"
    matched = filter_situation(df, down, dist, None)
    if len(matched) >= down_dist_min:
        return matched, "down+distance"
    matched = filter_situation(df, down, None, None)
    if len(matched) >= down_min:
        return matched, "down-only"
    # Last resort: return whatever exact/down+distance had, even if sparse
    exact = filter_situation(df, down, dist, zone)
    if not exact.empty:
        return exact, "sparse"
    down_dist = filter_situation(df, down, dist, None)
    if not down_dist.empty:
        return down_dist, "sparse"
    return matched, "sparse"


# Back-compat alias used internally
def _broaden(scout_df: pd.DataFrame, down: int, dist: str, zone: str) -> tuple[pd.DataFrame, str]:
    return broaden_situation(scout_df, down, dist, zone)


def _top_counts(series: pd.Series, n: int = 5) -> list[dict]:
    if series is None:
        return []
    try:
        cleaned = series.dropna().astype(str)
        cleaned = cleaned[~cleaned.str.contains("Unknown", na=False)]
    except Exception:
        return []
    if cleaned.empty:
        return []
    counts = cleaned.value_counts().head(n)
    return [{"name": k, "plays": int(v)} for k, v in counts.items()]


def _most_called(items: list[dict]) -> dict | None:
    return items[0] if items else None


def offense_scout_tendencies(
    scout_defense_df: pd.DataFrame,
    down: int,
    distance_bucket: str,
    field_zone: str,
) -> dict:
    """Opponent was on defense → what fronts/coverages they showed."""
    empty = {
        "plays": 0,
        "lean": "—",
        "top_fronts": [],
        "top_coverages": [],
        "top_def_calls": [],
        "most_front": None,
        "most_coverage": None,
        "most_play": None,
        "scope": "none",
        "kind": "opponent_defense",
    }
    if scout_defense_df.empty:
        return empty

    matched, scope = _broaden(scout_defense_df, down, distance_bucket, field_zone)
    if matched.empty:
        return empty

    fronts = _top_counts(matched["def_front"]) if "def_front" in matched.columns else []
    covs = _top_counts(matched["coverage"]) if "coverage" in matched.columns else []
    calls = _top_counts(matched["def_call"]) if "def_call" in matched.columns else []

    most_front = _most_called(fronts)
    most_cov = _most_called(covs)
    most_play = _most_called(calls)
    top_front = most_front["name"] if most_front else "—"
    top_cov = most_cov["name"] if most_cov else "—"
    lean = f"{top_front} / {top_cov}" if top_front != "—" else "—"

    return {
        "plays": len(matched),
        "lean": lean,
        "top_fronts": fronts,
        "top_coverages": covs,
        "top_def_calls": calls,
        "most_front": most_front,
        "most_coverage": most_cov,
        "most_play": most_play,
        "scope": scope,
        "kind": "opponent_defense",
        "run_pct": None,
        "pass_pct": None,
    }


def defense_scout_tendencies(
    scout_offense_df: pd.DataFrame,
    down: int,
    distance_bucket: str,
    field_zone: str,
) -> dict:
    """Opponent was on offense → run/pass + formations + plays."""
    empty = {
        "plays": 0,
        "run_pct": None,
        "pass_pct": None,
        "lean": "—",
        "top_formations": [],
        "top_plays": [],
        "most_formation": None,
        "most_coverage": None,
        "most_play": None,
        "scope": "none",
        "kind": "opponent_offense",
    }
    if scout_offense_df.empty:
        return empty

    matched, scope = _broaden(scout_offense_df, down, distance_bucket, field_zone)
    if matched.empty:
        return empty

    typed = matched[matched["play_type"].isin(["Run", "Pass"])]
    run_n = int((typed["play_type"] == "Run").sum())
    pass_n = int((typed["play_type"] == "Pass").sum())
    total_rp = run_n + pass_n
    run_pct = round(100 * run_n / total_rp, 1) if total_rp else None
    pass_pct = round(100 * pass_n / total_rp, 1) if total_rp else None

    if run_pct is None:
        lean = "—"
    elif run_pct >= (pass_pct or 0) + 8:
        lean = "Run"
    elif (pass_pct or 0) >= run_pct + 8:
        lean = "Pass"
    else:
        lean = "Balanced"

    forms = _top_counts(matched["formation"]) if "formation" in matched.columns else []
    plays = _top_counts(matched["play_call"]) if "play_call" in matched.columns else []
    covs = _top_counts(matched["coverage"]) if "coverage" in matched.columns else []

    return {
        "plays": len(matched),
        "run_pct": run_pct,
        "pass_pct": pass_pct,
        "lean": lean,
        "top_formations": forms,
        "top_plays": plays,
        "top_coverages": covs,
        "most_formation": _most_called(forms),
        "most_coverage": _most_called(covs),
        "most_play": _most_called(plays),
        "scope": scope,
        "kind": "opponent_offense",
    }


# Back-compat name used by older dashboard code paths
def situation_tendencies(scout_df, down, distance_bucket, field_zone):
    if scout_df.empty:
        return defense_scout_tendencies(scout_df, down, distance_bucket, field_zone)
    if "scout_role" in scout_df.columns and (scout_df["scout_role"] == "opponent_defense").any():
        return offense_scout_tendencies(scout_df, down, distance_bucket, field_zone)
    return defense_scout_tendencies(scout_df, down, distance_bucket, field_zone)


def load_scout_opponent_offense() -> pd.DataFrame:
    return load_scout("opponent_offense")


def load_scout_opponent_defense() -> pd.DataFrame:
    return load_scout("opponent_defense")


def scout_favorite_looks(
    opponent: str | None,
    *,
    n: int = 6,
) -> dict[str, list[str]]:
    """
    Most-used fronts / coverages vs tonight's opponent (scout opponent_defense).

    Used to keep tagger chips short — favorites only.
    """
    empty: dict[str, list[str]] = {"fronts": [], "coverages": []}
    opp = str(opponent or "").strip()
    if not opp:
        return empty
    try:
        df = load_scout("opponent_defense", opponent=opp)
    except Exception:
        return empty
    if df is None or getattr(df, "empty", True):
        return empty
    fronts = [r["name"] for r in _top_counts(df["def_front"], n=n) if r.get("name")]
    covs = [r["name"] for r in _top_counts(df["coverage"], n=n) if r.get("name")]
    return {"fronts": fronts, "coverages": covs}


# --- Scout matchup report (upload × our EPA) ---------------------------------

_COV_ALIASES: dict[str, set[str]] = {
    "0": {"0", "cover 0", "0 switch", "cover 0 switch"},
    "1": {"1", "cover 1", "cover 1 press man", "cover 1 man"},
    "2": {"2", "cover 2", "cover 2 man", "2 man"},
    "3": {"3", "cover 3", "3 lock", "cover 3 lock"},
    "4": {"4", "cover 4", "quarters"},
}


def _canon_cov_token(value) -> str:
    import re

    s = str(value or "").strip().lower()
    if not s or s in {"nan", "none", "unknown"}:
        return ""
    s = re.sub(r"^cover\s+", "", s)
    m = re.match(r"^(\d+)", s)
    return m.group(1) if m else s


def booth_front_tag(value, *, mode: str = "as_scouted") -> str:
    """
    Map a scout/film front to the booth tag used for matching.

    mode='even_42': numbered specialty fronts (31/13/22…) → Even (4-2 base).
    mode='as_scouted': keep scout labels (case-normalized).
    """
    import re

    s = str(value or "").strip().lower()
    if not s or s in {"nan", "none", "unknown"}:
        return ""
    if mode != "even_42":
        return s
    if s in {"bear", "odd", "even"}:
        return s
    if re.fullmatch(r"\d+", s):
        return "even"
    return s


def _look_mask(
    series: pd.Series,
    name: str,
    *,
    kind: str,
    booth_mode: str = "as_scouted",
) -> pd.Series:
    """Boolean mask: our tagged column matches a scout look (with aliases)."""
    if kind == "front":
        want = booth_front_tag(name, mode=booth_mode)
        if not want:
            return pd.Series(False, index=series.index)
        vals = series.map(lambda v: booth_front_tag(v, mode=booth_mode))
        return vals == want
    token = _canon_cov_token(name)
    aliases = _COV_ALIASES.get(token, {token} if token else set())
    if not aliases:
        return pd.Series(False, index=series.index)
    vals = series.map(_canon_cov_token)
    return vals.isin(aliases)


def _our_stats_vs_look(
    offense_df: pd.DataFrame | None,
    col: str,
    name: str,
    *,
    min_plays: int = 3,
    booth_mode: str = "as_scouted",
    positive_calls_only: bool = False,
) -> dict:
    """Our season EPA / success when we faced this defensive look."""
    out = {
        "our_plays": 0,
        "avg_epa": None,
        "success_rate": None,
        "thin": True,
        "best_calls": [],
    }
    if offense_df is None or getattr(offense_df, "empty", True):
        return out
    if col not in offense_df.columns or not str(name or "").strip():
        return out
    kind = (
        "front"
        if col == "def_front"
        else "coverage"
        if col == "coverage"
        else "exact"
    )
    if kind in {"front", "coverage"}:
        mask = _look_mask(
            offense_df[col], name, kind=kind, booth_mode=booth_mode
        )
    else:
        want = str(name).strip().lower()
        mask = offense_df[col].astype(str).str.strip().str.lower() == want
    sub = offense_df.loc[mask]
    out["our_plays"] = int(len(sub))
    if sub.empty:
        return out
    if "epa" in sub.columns:
        out["avg_epa"] = round(float(sub["epa"].mean()), 3)
    if "is_success" in sub.columns and len(sub) > 0:
        try:
            out["success_rate"] = round(float(sub["is_success"].mean()), 3)
        except Exception:
            out["success_rate"] = None
    out["thin"] = len(sub) < int(min_plays)
    if (
        "play_call" in sub.columns
        and "epa" in sub.columns
        and len(sub) >= max(2, min_plays - 1)
    ):
        try:
            tagged = sub
            if "play_tagged" in sub.columns:
                t = sub[sub["play_tagged"].fillna(0).astype(int) == 1]
                if len(t) >= 2:
                    tagged = t
            g = (
                tagged.groupby(tagged["play_call"].astype(str))
                .agg(plays=("epa", "count"), avg_epa=("epa", "mean"))
                .query("plays >= 2")
                .sort_values("avg_epa", ascending=False)
                .head(5)
            )
            calls = [
                {
                    "call": str(idx),
                    "plays": int(row["plays"]),
                    "avg_epa": round(float(row["avg_epa"]), 3),
                }
                for idx, row in g.iterrows()
            ]
            if positive_calls_only:
                calls = [c for c in calls if c["avg_epa"] > 0]
            out["best_calls"] = calls[:3]
        except Exception:
            out["best_calls"] = []
    return out


def _verdict_for_look(our: dict, scout_plays: int, scout_total: int) -> str:
    """edge / trap / neutral / unknown — for coach-facing report."""
    if our.get("thin") or our.get("avg_epa") is None:
        return "unknown"
    epa = float(our["avg_epa"])
    share = (scout_plays / scout_total) if scout_total else 0
    if epa >= 0.05:
        return "edge"
    if epa <= -0.05 and share >= 0.08:
        return "trap"
    if epa <= -0.05:
        return "caution"
    return "neutral"


def _filter_offense_seasons(
    offense_df: pd.DataFrame | None,
    seasons: list[str] | None,
) -> pd.DataFrame | None:
    if offense_df is None or getattr(offense_df, "empty", True):
        return offense_df
    if not seasons:
        return offense_df
    want = {str(s).strip().lower() for s in seasons if str(s).strip()}
    if not want or "all" in want:
        return offense_df
    if "season" not in offense_df.columns:
        return offense_df
    s = offense_df["season"].astype(str).str.strip().str.lower()
    return offense_df.loc[s.isin(want)].copy()


def _filter_current_season_offense(
    offense_df: pd.DataFrame | None,
) -> pd.DataFrame | None:
    """Current-season slice for primary EPA (falls back to all if untagged)."""
    if offense_df is None or getattr(offense_df, "empty", True):
        return offense_df
    if "season" not in offense_df.columns:
        return offense_df
    mask = offense_df["season"].map(_is_current_season_value).fillna(False).astype(bool)
    sub = offense_df.loc[mask].copy()
    return sub if not sub.empty else offense_df


def _primary_offense_sample(
    offense_df: pd.DataFrame | None,
    our_seasons: list[str] | None,
) -> tuple[pd.DataFrame | None, str]:
    """Season-first EPA sample: explicit multiselect → current season → all."""
    if our_seasons:
        filtered = _filter_offense_seasons(offense_df, our_seasons)
        label = ", ".join(str(s) for s in our_seasons)
        return filtered, label
    cur = _filter_current_season_offense(offense_df)
    try:
        import team_config as tc

        label = tc.current_season_label()
    except Exception:
        label = "This season"
    return cur, label


def _pick_epa_basis(season_stats: dict, all_stats: dict) -> tuple[dict, str]:
    """Prefer current-season EPA; fall back to all-time when sample is thin."""
    if (
        not season_stats.get("thin")
        and season_stats.get("avg_epa") is not None
        and int(season_stats.get("our_plays") or 0) >= 1
    ):
        return season_stats, "season"
    if all_stats.get("avg_epa") is not None and int(all_stats.get("our_plays") or 0) >= 1:
        return all_stats, "all_time"
    if not season_stats.get("thin"):
        return season_stats, "season"
    return all_stats, "all_time" if int(all_stats.get("our_plays") or 0) else "season"


def build_scout_matchup_report(
    opponent: str,
    offense_df: pd.DataFrame | None,
    *,
    top_n: int = 8,
    min_our_plays: int = 3,
    scout_season: str = "current",
    scout_df: pd.DataFrame | None = None,
    booth_front_mode: str = "even_42",
    our_seasons: list[str] | None = None,
) -> dict:
    """
    Opponent defense tendencies from scout × our EPA vs those looks.

    booth_front_mode:
      - 'even_42' (default): numbered scout fronts → Even for matching (4-2 booth)
      - 'as_scouted': match exact scout front labels
    Pass scout_df to use an in-memory upload without reading the DB.
    """
    opp = str(opponent or "").strip()
    empty = {
        "opponent": opp,
        "scout_snaps": 0,
        "booth_front_mode": booth_front_mode,
        "fronts": [],
        "fronts_detail": [],
        "coverages": [],
        "def_calls": [],
        "edges": [],
        "traps": [],
        "summary": "No scout defense data for this opponent.",
        "notes": [],
    }
    if not opp and scout_df is None:
        return empty

    if scout_df is not None:
        scout = scout_df.copy()
    else:
        if not opp:
            return empty
        try:
            scout = load_scout(
                "opponent_defense", opponent=opp, season=scout_season
            )
        except Exception:
            return empty
    if scout is None or getattr(scout, "empty", True):
        return empty

    our_all = offense_df
    our_primary, primary_label = _primary_offense_sample(offense_df, our_seasons)
    notes: list[str] = []
    # Coverage tags are sparse in recent seasons — fall back for cov EPA (all-time)
    our_cov_primary = our_primary
    our_cov_all = our_all
    if (
        our_primary is not None
        and not getattr(our_primary, "empty", True)
        and "coverage" in our_primary.columns
    ):
        cov_tagged = our_primary["coverage"].notna() & (
            our_primary["coverage"].astype(str).str.strip().str.lower().isin({"", "nan", "none"})
            == False
        )
        if int(cov_tagged.sum()) < 30 and our_all is not None and not getattr(our_all, "empty", True):
            our_cov_primary = our_all
            notes.append(
                "Coverage EPA (season) uses all stored seasons — thin coverage tags this year."
            )
    total = int(len(scout))
    mode = (
        booth_front_mode
        if booth_front_mode in {"even_42", "as_scouted"}
        else "even_42"
    )

    fronts_detail_raw = (
        _top_counts(scout["def_front"], n=top_n)
        if "def_front" in scout.columns
        else []
    )
    if mode == "even_42" and "def_front" in scout.columns:
        booth_series = scout["def_front"].map(
            lambda v: booth_front_tag(v, mode=mode)
        )
        fronts_raw = _top_counts(booth_series, n=top_n)
    else:
        fronts_raw = fronts_detail_raw
    covs_raw = (
        _top_counts(scout["coverage"], n=top_n)
        if "coverage" in scout.columns
        else []
    )
    calls_raw = (
        _top_counts(scout["def_call"], n=top_n)
        if "def_call" in scout.columns
        else []
    )

    def _enrich(
        items: list[dict],
        col: str,
        *,
        front_mode: str | None = None,
        film_only: bool = False,
        sample_primary: pd.DataFrame | None = None,
        sample_all: pd.DataFrame | None = None,
    ) -> list[dict]:
        rows: list[dict] = []
        bm = front_mode if front_mode is not None else mode
        sample_season = our_primary if sample_primary is None else sample_primary
        sample_career = our_all if sample_all is None else sample_all
        for it in items:
            name = str(it.get("name") or "")
            if not name or name.lower() in {"nan", "none", ""}:
                continue
            scout_n = int(it.get("plays") or 0)
            pct = round(100.0 * scout_n / total, 1) if total else 0.0
            if film_only:
                booth = booth_front_tag(name, mode="even_42")
                rows.append(
                    {
                        "look": name,
                        "booth_tag": booth.title() if booth else "—",
                        "scout_plays": scout_n,
                        "scout_pct": pct,
                        "our_plays": 0,
                        "avg_epa": None,
                        "success_rate": None,
                        "our_plays_all": 0,
                        "avg_epa_all": None,
                        "success_rate_all": None,
                        "verdict": "film",
                        "verdict_basis": "film",
                        "best_calls": [],
                        "thin": True,
                    }
                )
                continue
            season_stats = _our_stats_vs_look(
                sample_season,
                col,
                name,
                min_plays=min_our_plays,
                booth_mode=bm if col == "def_front" else "as_scouted",
                positive_calls_only=True,
            )
            all_stats = _our_stats_vs_look(
                sample_career,
                col,
                name,
                min_plays=min_our_plays,
                booth_mode=bm if col == "def_front" else "as_scouted",
                positive_calls_only=True,
            )
            basis_stats, basis = _pick_epa_basis(season_stats, all_stats)
            verdict = _verdict_for_look(basis_stats, scout_n, total)
            display = name
            if col == "def_front" and mode == "even_42" and bm == mode:
                display = (
                    name.title()
                    if name.lower() in {"even", "odd", "bear"}
                    else name
                )
            best = season_stats.get("best_calls") or []
            if not best:
                best = all_stats.get("best_calls") or []
            rows.append(
                {
                    "look": display,
                    "scout_plays": scout_n,
                    "scout_pct": pct,
                    "our_plays": season_stats["our_plays"],
                    "avg_epa": season_stats["avg_epa"],
                    "success_rate": season_stats["success_rate"],
                    "thin": bool(season_stats.get("thin")),
                    "our_plays_all": all_stats["our_plays"],
                    "avg_epa_all": all_stats["avg_epa"],
                    "success_rate_all": all_stats["success_rate"],
                    "thin_all": bool(all_stats.get("thin")),
                    "verdict": verdict,
                    "verdict_basis": basis,
                    "best_calls": best,
                }
            )
        return rows

    fronts = _enrich(fronts_raw, "def_front", front_mode=mode)
    fronts_detail = _enrich(
        fronts_detail_raw,
        "def_front",
        front_mode="as_scouted",
        film_only=(mode == "even_42"),
    )
    coverages = _enrich(
        covs_raw,
        "coverage",
        sample_primary=our_cov_primary,
        sample_all=our_cov_all,
    )
    def_calls = _enrich(
        calls_raw,
        "def_call",
        sample_primary=our_cov_primary,
        sample_all=our_cov_all,
    )

    pool = list(fronts) + list(coverages)
    edges = [r for r in pool if r.get("verdict") == "edge"]
    traps = [r for r in pool if r.get("verdict") in {"trap", "caution"}]
    edges.sort(
        key=lambda r: (float(r.get("scout_pct") or 0) * float(r.get("avg_epa") or 0)),
        reverse=True,
    )
    traps.sort(
        key=lambda r: (
            float(r.get("scout_pct") or 0) * abs(float(r.get("avg_epa") or 0))
        ),
        reverse=True,
    )

    top_f = fronts[0]["look"] if fronts else "—"
    top_c = coverages[0]["look"] if coverages else "—"
    if mode == "even_42":
        notes.append(
            "Booth mode: 4-2 — numbered scout fronts mapped to Even for EPA match."
        )
    notes.append(f"Primary EPA sample: **{primary_label}** (season-first; all-time shown alongside).")
    our_n = (
        int(len(our_primary))
        if our_primary is not None and not getattr(our_primary, "empty", True)
        else 0
    )
    our_all_n = (
        int(len(our_all))
        if our_all is not None and not getattr(our_all, "empty", True)
        else 0
    )
    summary = (
        f"vs {opp or 'upload'}: scout {total} D snaps · lean {top_f} / {top_c} · "
        f"{len(edges)} edge · {len(traps)} trap/caution · "
        f"our n={our_n:,} ({primary_label}) · career n={our_all_n:,}"
    )
    return {
        "opponent": opp or "Opponent",
        "version": 2,
        "scout_snaps": total,
        "booth_front_mode": mode,
        "our_plays_sampled": our_n,
        "our_plays_all_time": our_all_n,
        "our_seasons": list(our_seasons or []),
        "primary_season_label": primary_label,
        "fronts": fronts,
        "fronts_detail": fronts_detail,
        "coverages": coverages,
        "def_calls": def_calls,
        "edges": edges[:6],
        "traps": traps[:6],
        "summary": summary,
        "notes": notes,
    }


def scout_matchup_report_markdown(report: dict) -> str:
    """Plain markdown for download / locker-room print."""
    opp = report.get("opponent") or "Opponent"
    lines = [
        f"# Scout matchup · vs {opp}",
        "",
        str(report.get("summary") or ""),
        "",
        f"Scout defense snaps: **{report.get('scout_snaps', 0)}**",
        f"Our snaps (season): **{report.get('our_plays_sampled', '—')}**",
        f"Our snaps (career): **{report.get('our_plays_all_time', '—')}**",
        f"Primary sample: **{report.get('primary_season_label', 'This season')}**",
        "",
        "_Season EPA first; career in parentheses. Verdict* = based on career sample._",
        "",
    ]
    for note in report.get("notes") or []:
        lines.append(f"> {note}")
    if report.get("notes"):
        lines.append("")

    def _row(r: dict, *, dual: bool = True) -> str:
        epa = r.get("avg_epa")
        suc = r.get("success_rate")
        epa_s = f"{epa:+.3f}" if epa is not None else "—"
        suc_s = f"{100 * suc:.0f}%" if suc is not None else "—"
        basis = r.get("verdict_basis") or ""
        if dual and r.get("avg_epa_all") is not None:
            epa_a = r.get("avg_epa_all")
            epa_all_s = f"{epa_a:+.3f}" if epa_a is not None else "—"
            n_all = r.get("our_plays_all", "—")
            epa_col = f"{epa_s} ({epa_all_s} career)"
            n_col = f"{r.get('our_plays')} ({n_all})"
        else:
            epa_col = epa_s
            n_col = str(r.get("our_plays"))
        verdict = str(r.get("verdict") or "—")
        if basis == "all_time" and verdict not in {"film", "—"}:
            verdict += "*"
        return (
            f"| {r.get('look')} | {r.get('scout_pct')}% | {n_col} | "
            f"{epa_col} | {suc_s} | {verdict} |"
        )

    mode = report.get("booth_front_mode") or "as_scouted"
    if mode == "even_42":
        lines.extend(
            [
                "## Booth fronts × our success",
                "",
                "| Front (booth) | Scout % | Our plays | Our EPA | Success | Verdict |",
                "| --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for r in report.get("fronts") or []:
            lines.append(_row(r))
        if report.get("fronts_detail"):
            lines.extend(
                [
                    "",
                    "## Scout front detail (film only)",
                    "",
                    "| Scout front | Scout % | Booth tag |",
                    "| --- | ---: | --- |",
                ]
            )
            for r in report["fronts_detail"]:
                lines.append(
                    f"| {r.get('look')} | {r.get('scout_pct')}% | "
                    f"{r.get('booth_tag') or '—'} |"
                )
    else:
        lines.extend(
            [
                "## Their fronts × our success",
                "",
                "| Front | Scout % | Our plays | Our EPA | Success | Verdict |",
                "| --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for r in report.get("fronts") or []:
            lines.append(_row(r))

    lines.extend(["", "## Their coverages × our success", ""])
    lines.append("| Coverage | Scout % | Our plays | Our EPA | Success | Verdict |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
    for r in report.get("coverages") or []:
        lines.append(_row(r))
    if report.get("edges"):
        lines.extend(["", "## Edges (we good vs looks they run)", ""])
        for r in report["edges"]:
            epa = r.get("avg_epa")
            epa_s = f"{epa:+.3f}" if epa is not None else "—"
            lines.append(
                f"- **{r['look']}** · scout {r['scout_pct']}% · "
                f"our EPA {epa_s} (n={r['our_plays']})"
            )
            for c in r.get("best_calls") or []:
                lines.append(
                    f"  - Feature: {c['call']} ({c['avg_epa']:+.3f}, n={c['plays']})"
                )
    if report.get("traps"):
        lines.extend(["", "## Traps / caution (they run it · we struggle)", ""])
        for r in report["traps"]:
            epa = r.get("avg_epa")
            epa_s = f"{epa:+.3f}" if epa is not None else "—"
            lines.append(
                f"- **{r['look']}** · scout {r['scout_pct']}% · our EPA {epa_s} "
                f"(n={r['our_plays']})"
            )
    lines.append("")
    return "\n".join(lines)



_LIVE_LOG_CACHE: tuple[float, int, pd.DataFrame] | None = None


def load_live_log() -> pd.DataFrame:
    """Read live_log.csv; reuse in-process cache when mtime/size unchanged."""
    global _LIVE_LOG_CACHE
    if not LIVE_LOG_FILE.exists():
        _LIVE_LOG_CACHE = None
        return pd.DataFrame()
    try:
        st = LIVE_LOG_FILE.stat()
        mtime, size = st.st_mtime, st.st_size
        cached = _LIVE_LOG_CACHE
        if cached is not None and cached[0] == mtime and cached[1] == size:
            return cached[2].copy()
        df = pd.read_csv(LIVE_LOG_FILE)
        _LIVE_LOG_CACHE = (mtime, size, df)
        return df.copy()
    except Exception:
        return pd.DataFrame()


def live_log_adjustments(
    log_df: pd.DataFrame,
    unit: str,
    down: int,
    dist: str,
    zone: str,
    *,
    opponent: str | None = None,
    half: int | None = None,
    weight: float = 1.0,
) -> dict[str, float]:
    if log_df.empty:
        return {}

    unit_logs = log_df[log_df["unit"].astype(str).str.lower() == unit.lower()].copy()
    if unit_logs.empty or "call" not in unit_logs.columns:
        return {}

    if opponent and "opponent" in unit_logs.columns:
        unit_logs = unit_logs[
            unit_logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
        ]

    if half is not None and "half" in unit_logs.columns and not unit_logs.empty:
        unit_logs = unit_logs[_half_equals(unit_logs["half"], half)]

    sit = unit_logs.copy()
    if {"down", "distance", "field_zone"}.issubset(sit.columns):
        exact = sit[
            (sit["down"] == down)
            & (sit["distance"].astype(str).str.lower() == dist.lower())
            & (sit["field_zone"].astype(str).str.lower() == zone.lower())
        ]
        if len(exact) >= 1:
            sit = exact

    offense_good = {"Gain", "TD"}
    offense_bad = {"Incomplete", "Turnover", "Sack / TFL", "No gain", "Punt"}
    defense_good = {"Incomplete", "Sack / TFL", "Turnover", "No gain", "Punt"}
    defense_bad = {"Gain", "TD"}

    adj: dict[str, float] = {}
    for _, row in sit.iterrows():
        call = str(row.get("call", "")).strip()
        if not call or call == "(none)":
            continue
        result = str(row.get("result", ""))
        if unit.lower() == "offense":
            delta = 0.15 if result in offense_good else (-0.20 if result in offense_bad else 0.0)
        else:
            delta = 0.15 if result in defense_good else (-0.20 if result in defense_bad else 0.0)
        adj[call] = adj.get(call, 0.0) + delta * weight
    return adj


def mesh_rankings(
    season_table: pd.DataFrame,
    call_col: str,
    tendencies: dict,
    live_adj: dict[str, float],
    unit: str,
    top_n: int = 3,
    *,
    plan_pins: list[str] | None = None,
    plan_status: dict[str, str] | None = None,
    plan_weight: float = 0.08,
    live_weight: float = 1.8,
    scout_weight: float = 0.75,
    season_weight: float = 0.4,
) -> pd.DataFrame:
    """Rank calls with live evidence > scout lean > season EPA."""
    if season_table.empty:
        return pd.DataFrame()

    out = season_table.copy()
    out["season_epa"] = out["avg_epa"]
    if "success_rate" not in out.columns:
        out["success_rate"] = 0.0
    out["success_rate"] = out["success_rate"].fillna(0.0)
    out["scout_bonus"] = 0.0
    out["plan_bonus"] = 0.0
    out["live_adj"] = (
        out[call_col].map(lambda c: live_adj.get(str(c), 0.0)).fillna(0.0) * live_weight
    )

    lean = tendencies.get("lean", "—")
    kind = tendencies.get("kind", "")
    scout_plays = int(tendencies.get("plays", 0) or 0)

    # Scout lean bonuses (scaled by scout_weight in mesh_score)
    if unit.lower() == "defense" and lean in {"Run", "Pass"} and scout_plays > 0:
        out.loc[out["season_epa"] > 0, "scout_bonus"] += 0.10
    if unit.lower() == "offense" and kind == "opponent_defense" and scout_plays > 0:
        out.loc[out["season_epa"] > 0, "scout_bonus"] += 0.08

    pins = {str(p).strip() for p in (plan_pins or []) if str(p).strip()}
    status = plan_status or {}
    for idx, row in out.iterrows():
        call = str(row[call_col])
        if call not in pins:
            continue
        st = status.get(call, "unproven")
        if st == "kill":
            out.at[idx, "plan_bonus"] = -0.15
        elif st == "confirmed":
            out.at[idx, "plan_bonus"] = plan_weight * 1.5
        else:
            out.at[idx, "plan_bonus"] = plan_weight

    success_term = 0.35 * (out["success_rate"] - 0.5)
    out["mesh_score"] = (
        season_weight * out["season_epa"]
        + success_term
        + scout_weight * out["scout_bonus"]
        + out["plan_bonus"]
        + out["live_adj"]
    ).round(3)
    out = out.sort_values("mesh_score", ascending=False).reset_index(drop=True)
    return out.head(top_n)


# ---------------------------------------------------------------------------
# Game plan persistence
# ---------------------------------------------------------------------------

GAME_PLANS_DIR = PROJECT_DIR / "data" / "game_plans"


def _plan_path(opponent: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in opponent).strip()
    return GAME_PLANS_DIR / f"{safe or 'Unknown'}.json"


def load_game_plan(opponent: str) -> dict:
    path = _plan_path(opponent)
    empty = {
        "opponent": opponent,
        "offense_pins": [],
        "defense_pins": [],
        "updated_at": None,
    }
    if not path.exists():
        return empty
    try:
        import json

        data = json.loads(path.read_text())
        data.setdefault("offense_pins", [])
        data.setdefault("defense_pins", [])
        data["opponent"] = opponent
        return data
    except Exception:
        return empty


def save_game_plan(plan: dict) -> Path:
    import json
    from datetime import datetime

    GAME_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan = dict(plan)
    plan["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path = _plan_path(str(plan.get("opponent", "Unknown")))
    path.write_text(json.dumps(plan, indent=2))
    return path


def pin_names(plan: dict, unit: str) -> list[str]:
    key = "offense_pins" if unit.lower() == "offense" else "defense_pins"
    return [str(p.get("call", "")).strip() for p in plan.get(key, []) if p.get("call")]


def suggest_edges(
    our_table: pd.DataFrame,
    call_col: str,
    their_looks: list[dict],
    our_vs_look: pd.DataFrame,
    look_col: str,
    *,
    top_n: int = 5,
) -> list[dict]:
    """Suggest plan pins: we are good + they run related looks frequently."""
    if our_table.empty:
        return []
    look_names = {str(x["name"]) for x in their_looks[:5]} if their_looks else set()
    suggestions: list[dict] = []
    ranked = our_table.sort_values(
        ["avg_epa", "success_rate"] if "success_rate" in our_table.columns else ["avg_epa"],
        ascending=False,
    )
    for _, row in ranked.head(12).iterrows():
        call = str(row[call_col])
        sr = float(row["success_rate"]) if "success_rate" in row and pd.notna(row["success_rate"]) else None
        why_bits = [f"EPA {row['avg_epa']:+.2f}"]
        if sr is not None:
            why_bits.append(f"succ {sr:.0%}")
        if not our_vs_look.empty and look_col in our_vs_look.columns and look_names:
            matched = our_vs_look[our_vs_look[look_col].astype(str).isin(look_names)]
            if not matched.empty and call_col in matched.columns:
                sub = matched[matched[call_col].astype(str) == call]
                if not sub.empty:
                    why_bits.append(f"vs their looks n={len(sub)}")
        suggestions.append({"call": call, "why": " · ".join(why_bits)})
        if len(suggestions) >= top_n:
            break
    return suggestions


def score_live_calls(
    log_df: pd.DataFrame,
    unit: str,
    opponent: str | None = None,
    half: int | None = None,
) -> pd.DataFrame:
    """Aggregate tonight's log into working / not-working call scores."""
    if log_df.empty or "call" not in log_df.columns:
        return pd.DataFrame(columns=["call", "plays", "score", "good", "bad"])
    logs = log_df[log_df["unit"].astype(str).str.lower() == unit.lower()].copy()
    if opponent and "opponent" in logs.columns:
        logs = logs[
            logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
        ]
    if half is not None and "half" in logs.columns and not logs.empty:
        logs = logs[_half_equals(logs["half"], half)]
    if logs.empty:
        return pd.DataFrame(columns=["call", "plays", "score", "good", "bad"])

    offense_good = {"Gain", "TD"}
    offense_bad = {"Incomplete", "Turnover", "Sack / TFL", "No gain", "Punt"}
    defense_good = {"Incomplete", "Sack / TFL", "Turnover", "No gain", "Punt"}
    defense_bad = {"Gain", "TD"}
    good_set = offense_good if unit.lower() == "offense" else defense_good
    bad_set = offense_bad if unit.lower() == "offense" else defense_bad

    rows = []
    for call, grp in logs.groupby(logs["call"].astype(str)):
        if not call or call == "(none)":
            continue
        results = grp["result"].astype(str) if "result" in grp.columns else pd.Series(dtype=str)
        good = int(results.isin(good_set).sum())
        bad = int(results.isin(bad_set).sum())
        rows.append(
            {
                "call": call,
                "plays": len(grp),
                "good": good,
                "bad": bad,
                "score": good * 0.15 - bad * 0.20,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["call", "plays", "score", "good", "bad"])
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


def plan_pin_status(plan: dict, unit: str, live_scores: pd.DataFrame) -> dict[str, str]:
    """Map each pin to confirmed / unproven / kill from tonight's evidence."""
    scores = {}
    if not live_scores.empty:
        scores = {str(r.call): float(r.score) for r in live_scores.itertuples(index=False)}
    status: dict[str, str] = {}
    for name in pin_names(plan, unit):
        if name not in scores:
            status[name] = "unproven"
        elif scores[name] > 0.05:
            status[name] = "confirmed"
        elif scores[name] < -0.05:
            status[name] = "kill"
        else:
            status[name] = "unproven"
    return status


# ---------------------------------------------------------------------------
# Game phase + halftime report
# ---------------------------------------------------------------------------

GAME_STATE_FILE = PROJECT_DIR / "data" / "game_state.json"
HALFTIME_REPORTS_DIR = PROJECT_DIR / "data" / "halftime_reports"
HT_MIN_SAMPLE = 3  # tendency boards need at least this many snaps


def load_game_state() -> dict:
    empty = {
        "opponent": None,
        "phase": "1st",  # 1st | halftime | 2nd
        "halftime_at": None,
        "report_path": None,
    }
    if not GAME_STATE_FILE.exists():
        return empty
    try:
        import json

        data = json.loads(GAME_STATE_FILE.read_text())
        out = dict(empty)
        out.update(data or {})
        return out
    except Exception:
        return empty


def save_game_state(state: dict) -> Path:
    import json

    from file_lock import file_lock

    GAME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(GAME_STATE_FILE):
        tmp = GAME_STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(GAME_STATE_FILE)
    return GAME_STATE_FILE


def _half_equals(series: pd.Series, half: int) -> pd.Series:
    """Match half whether stored as 1, '1', or 1.0."""
    return pd.to_numeric(series, errors="coerce") == int(half)


def filter_live_logs(
    log_df: pd.DataFrame,
    opponent: str | None = None,
    half: int | None = None,
) -> pd.DataFrame:
    if log_df is None or log_df.empty:
        return pd.DataFrame()
    logs = log_df.copy()
    if opponent and "opponent" in logs.columns:
        # Always apply — empty result means no plays for this opponent tonight
        logs = logs[
            logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
        ]
    if half is not None and "half" in logs.columns and not logs.empty:
        logs = logs[_half_equals(logs["half"], half)]
    return logs


def _live_result_sets(unit: str) -> tuple[set[str], set[str]]:
    offense_good = {"Gain", "TD"}
    offense_bad = {"Incomplete", "Turnover", "Sack / TFL", "No gain", "Punt"}
    defense_good = {"Incomplete", "Sack / TFL", "Turnover", "No gain", "Punt"}
    defense_bad = {"Gain", "TD"}
    if str(unit).lower() == "defense":
        return defense_good, defense_bad
    return offense_good, offense_bad


def _is_blitz(val) -> bool:
    return str(val).strip().lower() in {"yes", "y", "1", "true", "blitz"}


def score_live_dimension(
    log_df: pd.DataFrame,
    group_col: str,
    unit: str | None = None,
    *,
    min_plays: int = 1,
    label_name: str = "label",
) -> pd.DataFrame:
    """Score a categorical column (formation, coverage, situation, etc.)."""
    empty = pd.DataFrame(
        columns=[label_name, "plays", "good", "bad", "score", "avg_yards", "success_rate"]
    )
    if log_df is None or log_df.empty or group_col not in log_df.columns:
        return empty
    logs = log_df.copy()
    if unit and "unit" in logs.columns:
        logs = logs[logs["unit"].astype(str).str.lower() == unit.lower()]
    if logs.empty:
        return empty

    rows = []
    for raw, grp in logs.groupby(logs[group_col].fillna("(blank)").astype(str)):
        label = str(raw).strip()
        if not label or label.lower() in {"(blank)", "nan", "none", "(none)"}:
            continue
        if len(grp) < min_plays:
            continue
        # Score using unit of the group (or forced unit)
        u = unit or (str(grp["unit"].iloc[0]) if "unit" in grp.columns else "Offense")
        good_set, bad_set = _live_result_sets(u)
        results = grp["result"].astype(str) if "result" in grp.columns else pd.Series(dtype=str)
        good = int(results.isin(good_set).sum())
        bad = int(results.isin(bad_set).sum())
        yards = (
            pd.to_numeric(grp["yards_gained"], errors="coerce")
            if "yards_gained" in grp.columns
            else pd.Series(dtype=float)
        )
        n = int(len(grp))
        rows.append(
            {
                label_name: label,
                "plays": n,
                "good": good,
                "bad": bad,
                "score": round(good * 0.15 - bad * 0.20, 3),
                "avg_yards": round(float(yards.mean()), 2) if len(yards) and yards.notna().any() else None,
                "success_rate": round(good / n, 3) if n else 0.0,
            }
        )
    if not rows:
        return empty
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)


def analyze_live_blitz(log_df: pd.DataFrame, unit: str | None = None) -> dict:
    """Blitz rate + performance when blitzed vs not, broken down by situation."""
    out: dict = {
        "plays": 0,
        "blitz_plays": 0,
        "blitz_pct": 0.0,
        "when_blitz": None,
        "when_no_blitz": None,
        "by_coverage": [],
        "by_formation": [],
        "by_field_zone": [],
        "by_down": [],
        "by_situation": [],
        "by_down_distance": [],
    }
    if log_df is None or log_df.empty or "blitz" not in log_df.columns:
        return out
    logs = log_df.copy()
    if unit and "unit" in logs.columns:
        logs = logs[logs["unit"].astype(str).str.lower() == unit.lower()]
    if logs.empty:
        return out

    # Only snaps with an explicit Yes/No blitz tag (skip quick-log blanks)
    def _blitz_tagged(val) -> bool:
        return str(val).strip().lower() in {
            "yes", "y", "1", "true", "blitz", "no", "n", "0", "false"
        }

    logs = logs[logs["blitz"].map(_blitz_tagged)]
    if logs.empty:
        return out

    flags = logs["blitz"].map(_is_blitz)
    n = int(len(logs))
    b = int(flags.sum())
    out["plays"] = n
    out["blitz_plays"] = b
    out["blitz_pct"] = round(100.0 * b / n, 1) if n else 0.0

    def _meta(sub: pd.DataFrame) -> dict | None:
        if sub.empty:
            return None
        u = unit or (str(sub["unit"].iloc[0]) if "unit" in sub.columns else "Offense")
        good_set, bad_set = _live_result_sets(u)
        results = sub["result"].astype(str) if "result" in sub.columns else pd.Series(dtype=str)
        good = int(results.isin(good_set).sum())
        bad = int(results.isin(bad_set).sum())
        yards = (
            pd.to_numeric(sub["yards_gained"], errors="coerce")
            if "yards_gained" in sub.columns
            else pd.Series(dtype=float)
        )
        nn = int(len(sub))
        return {
            "plays": nn,
            "good": good,
            "bad": bad,
            "score": round(good * 0.15 - bad * 0.20, 3),
            "avg_yards": round(float(yards.mean()), 2) if len(yards) and yards.notna().any() else None,
            "success_rate": round(good / nn, 3) if nn else 0.0,
        }

    out["when_blitz"] = _meta(logs[flags])
    out["when_no_blitz"] = _meta(logs[~flags])

    def _rate_rows(series: pd.Series, key_name: str) -> list[dict]:
        rows = []
        for key, grp in logs.groupby(series):
            label = str(key).strip()
            if not label or label.lower() in {"nan", "none", "?", "(blank)"}:
                continue
            rate = float(grp["blitz"].map(_is_blitz).mean()) if len(grp) else 0.0
            blitz_n = int(grp["blitz"].map(_is_blitz).sum())
            rows.append(
                {
                    key_name: label,
                    "plays": int(len(grp)),
                    "blitz_plays": blitz_n,
                    "blitz_pct": round(100.0 * rate, 1),
                }
            )
        return sorted(rows, key=lambda r: (-r["blitz_pct"], -r["blitz_plays"], -r["plays"]))

    if "coverage" in logs.columns:
        out["by_coverage"] = [
            {
                "coverage": r["label"],
                "plays": r["plays"],
                "blitz_plays": r["blitz_plays"],
                "blitz_pct": r["blitz_pct"],
            }
            for r in _rate_rows(logs["coverage"].fillna("?").astype(str), "label")
        ]

    if "formation" in logs.columns:
        out["by_formation"] = [
            {
                "formation": r["label"],
                "plays": r["plays"],
                "blitz_plays": r["blitz_plays"],
                "blitz_pct": r["blitz_pct"],
            }
            for r in _rate_rows(logs["formation"].fillna("?").astype(str), "label")
            if r["plays"] >= 1
        ]

    if "field_zone" in logs.columns:
        out["by_field_zone"] = [
            {
                "field_zone": r["label"],
                "plays": r["plays"],
                "blitz_plays": r["blitz_plays"],
                "blitz_pct": r["blitz_pct"],
            }
            for r in _rate_rows(logs["field_zone"].fillna("?").astype(str), "label")
        ]

    if "down" in logs.columns:
        down_rows = []
        for d, grp in logs.groupby(logs["down"]):
            rate = float(grp["blitz"].map(_is_blitz).mean()) if len(grp) else 0.0
            down_rows.append(
                {
                    "down": int(d) if pd.notna(d) else 0,
                    "plays": int(len(grp)),
                    "blitz_plays": int(grp["blitz"].map(_is_blitz).sum()),
                    "blitz_pct": round(100.0 * rate, 1),
                }
            )
        out["by_down"] = sorted(down_rows, key=lambda r: r["down"])

    sit_series = logs.apply(_situation_key, axis=1)
    out["by_situation"] = [
        {
            "situation": r["label"],
            "plays": r["plays"],
            "blitz_plays": r["blitz_plays"],
            "blitz_pct": r["blitz_pct"],
        }
        for r in _rate_rows(sit_series, "label")
        if r["blitz_plays"] > 0 or r["plays"] >= 2
    ]

    if {"down", "distance"}.issubset(logs.columns):
        dd = logs["down"].astype(str) + " & " + logs["distance"].astype(str)
        out["by_down_distance"] = [
            {
                "down_distance": r["label"],
                "plays": r["plays"],
                "blitz_plays": r["blitz_plays"],
                "blitz_pct": r["blitz_pct"],
            }
            for r in _rate_rows(dd, "label")
        ]

    return out


def analyze_live_coverage(log_df: pd.DataFrame, unit: str | None = None) -> dict:
    """Coverage mix + where each coverage shows (formation / zone / down-distance)."""
    out: dict = {
        "plays": 0,
        "mix": [],
        "by_formation": [],
        "by_field_zone": [],
        "by_down_distance": [],
    }
    if log_df is None or log_df.empty or "coverage" not in log_df.columns:
        return out
    logs = log_df.copy()
    if unit and "unit" in logs.columns:
        logs = logs[logs["unit"].astype(str).str.lower() == unit.lower()]
    cov = logs["coverage"].fillna("").astype(str).str.strip()
    logs = logs[cov.ne("") & ~cov.str.lower().isin({"nan", "none", "?", "(blank)", "(none)"})]
    if logs.empty:
        return out
    n = int(len(logs))
    out["plays"] = n

    mix = []
    for c, grp in logs.groupby(logs["coverage"].astype(str).str.strip()):
        mix.append(
            {
                "coverage": str(c),
                "plays": int(len(grp)),
                "pct": round(100.0 * len(grp) / n, 1),
            }
        )
    out["mix"] = sorted(mix, key=lambda r: (-r["pct"], -r["plays"]))

    def _breakdown(series: pd.Series, dim_name: str) -> list[dict]:
        rows = []
        for dim_val, grp in logs.groupby(series):
            label = str(dim_val).strip()
            if not label or label.lower() in {"nan", "none", "?", "(blank)"}:
                continue
            gn = int(len(grp))
            for c, cgrp in grp.groupby(grp["coverage"].astype(str).str.strip()):
                rows.append(
                    {
                        dim_name: label,
                        "coverage": str(c),
                        "plays": int(len(cgrp)),
                        "pct": round(100.0 * len(cgrp) / gn, 1),
                        "group_plays": gn,
                    }
                )
        return sorted(rows, key=lambda r: (-r["group_plays"], -r["pct"], -r["plays"]))

    if "formation" in logs.columns:
        out["by_formation"] = _breakdown(logs["formation"].fillna("?").astype(str), "formation")
    if "field_zone" in logs.columns:
        out["by_field_zone"] = _breakdown(
            logs["field_zone"].fillna("?").astype(str), "field_zone"
        )
    if {"down", "distance"}.issubset(logs.columns):
        dd = logs["down"].astype(str) + " & " + logs["distance"].astype(str)
        out["by_down_distance"] = _breakdown(dd, "down_distance")

    return out


def _load_ep_table_from_season() -> dict:
    """EP lookup from season EPA table (avg ep_before by situation)."""
    from step3_epa import DEFAULT_EP, situation_key

    df = load_table(
        "SELECT field_zone, down, distance_bucket, AVG(ep_before) AS ep "
        "FROM offense_plays_epa GROUP BY field_zone, down, distance_bucket"
    )
    table: dict = {}
    if not df.empty:
        for _, row in df.iterrows():
            try:
                key = situation_key(
                    str(row["field_zone"]),
                    int(row["down"]),
                    str(row["distance_bucket"]),
                )
                table[key] = float(row["ep"])
            except (TypeError, ValueError):
                continue
    if not table:
        # Priors if DB empty
        from step3_epa import build_ep_table

        season = load_table("SELECT * FROM offense_plays")
        if not season.empty:
            return build_ep_table(season)
    return table


def _estimate_live_play_epa(row: pd.Series, ep_table: dict) -> float:
    """Approximate EPA for a live-log snap using season EP + result/yards."""
    from step3_epa import (
        DEFAULT_EP,
        KICKOFF_EP_AFTER,
        TD_POINTS,
        fp_to_zone,
        lookup_ep,
    )

    zone = str(row.get("field_zone") or "midfield").strip().lower() or "midfield"
    try:
        down = int(row.get("down") or 1)
    except (TypeError, ValueError):
        down = 1
    dist_bucket = str(row.get("distance") or "long").strip().lower() or "long"
    try:
        dist_y = float(row.get("distance_yards") or 0) or {
            "short": 2.0,
            "medium": 5.0,
            "long": 10.0,
        }.get(dist_bucket, 10.0)
    except (TypeError, ValueError):
        dist_y = 10.0
    result = str(row.get("result") or "")
    try:
        yards = float(row.get("yards_gained") or 0)
    except (TypeError, ValueError):
        yards = 0.0

    ep_before = lookup_ep(ep_table, zone, down, dist_bucket) if ep_table else DEFAULT_EP

    if result == "TD":
        return round(TD_POINTS + KICKOFF_EP_AFTER - ep_before, 3)
    if result == "Turnover":
        ep_after = -lookup_ep(ep_table, "midfield", 1, "long") if ep_table else -DEFAULT_EP
        return round(ep_after - ep_before, 3)
    if result == "Punt":
        ep_after = (
            -lookup_ep(ep_table, "own_territory", 1, "long") if ep_table else -DEFAULT_EP
        )
        return round(ep_after - ep_before, 3)

    zone_fp = {
        "backed_up": 10.0,
        "own_territory": 30.0,
        "midfield": 50.0,
        "opp_territory": 70.0,
        "red_zone": 90.0,
    }
    fp = max(0.0, min(99.0, zone_fp.get(zone, 50.0) + yards))
    new_zone = fp_to_zone(fp)

    if result in {"Incomplete", "Penalty"} or (result == "No gain" and yards <= 0):
        new_down = down + 1
        new_dist = dist_y
    elif yards >= dist_y or result == "Gain" and yards >= dist_y:
        new_down = 1
        new_dist = min(10.0, 100.0 - fp)
    else:
        new_down = down + 1
        new_dist = max(0.0, dist_y - yards)

    if new_down > 4:
        opp_zone = fp_to_zone(100.0 - fp)
        ep_after = -lookup_ep(ep_table, opp_zone, 1, "medium") if ep_table else -DEFAULT_EP
        return round(ep_after - ep_before, 3)

    if new_dist <= 3:
        new_bucket = "short"
    elif new_dist <= 6:
        new_bucket = "medium"
    else:
        new_bucket = "long"
    ep_after = lookup_ep(ep_table, new_zone, int(new_down), new_bucket) if ep_table else DEFAULT_EP
    return round(ep_after - ep_before, 3)


def live_half_xp(log_df: pd.DataFrame, unit: str = "Offense") -> dict:
    """
    Halftime xP vs actual points — same mental model as Game Review (xP).

    Pace-normalized against season game averages:
      xPoints = season_avg_pts * (plays / season_avg_plays)
                + (half_epa - season_avg_epa * plays / season_avg_plays)
      luck = actual − xPoints  (offense: + = overperforming)
    Defense inverts luck sign in the display layer.
    """
    empty = {
        "unit": unit,
        "plays": 0,
        "actual_points": 0,
        "xpoints": 0.0,
        "luck": 0.0,
        "total_epa": 0.0,
        "tds": 0,
        "season_avg_pts": None,
        "season_avg_epa": None,
    }
    if log_df is None or log_df.empty:
        return empty
    logs = log_df.copy()
    if "unit" in logs.columns:
        logs = logs[logs["unit"].astype(str).str.lower() == unit.lower()]
    if logs.empty:
        return empty

    ep_table = _load_ep_table_from_season()
    epas = [_estimate_live_play_epa(row, ep_table) for _, row in logs.iterrows()]
    total_epa = float(sum(epas))
    results = logs["result"].astype(str) if "result" in logs.columns else pd.Series(dtype=str)
    tds = int((results == "TD").sum()) if not results.empty else 0
    actual = tds * 6
    n = int(len(logs))

    # Season calibration
    table = "offense_plays_epa" if unit.lower() == "offense" else "defense_plays_epa"
    # Pace calibration from current-season games only (prior year is EPA fuel, not game book)
    season = load_table(
        f"SELECT game_id, season, SUM(epa) AS total_epa, SUM(points_scored) AS pts, COUNT(*) AS plays "
        f"FROM {table} GROUP BY game_id, season"
    )
    if season.empty:
        season = load_table(
            f"SELECT game_id, SUM(epa) AS total_epa, SUM(points_scored) AS pts, COUNT(*) AS plays "
            f"FROM {table} GROUP BY game_id"
        )
    elif "season" in season.columns:
        season = season[season["season"].map(_is_current_season_value)]
    if season.empty or season["plays"].mean() <= 0:
        # Fallback: process-only scoreboard
        return {
            **empty,
            "plays": n,
            "actual_points": actual,
            "xpoints": round(actual, 1),
            "luck": 0.0,
            "total_epa": round(total_epa, 2),
            "tds": tds,
        }

    avg_epa = float(season["total_epa"].mean())
    avg_pts = float(season["pts"].mean())
    avg_plays = float(season["plays"].mean())
    expected_epa = avg_epa * (n / avg_plays)
    xpoints = avg_pts * (n / avg_plays) + (total_epa - expected_epa)
    # Defense: points_scored in DB is still opponent TD points on those plays
    luck = actual - xpoints
    return {
        "unit": unit,
        "plays": n,
        "actual_points": int(actual),
        "xpoints": round(float(xpoints), 1),
        "luck": round(float(luck), 1),
        "total_epa": round(total_epa, 2),
        "tds": tds,
        "season_avg_pts": round(avg_pts, 1),
        "season_avg_epa": round(avg_epa, 2),
        "season_avg_plays": round(avg_plays, 1),
    }


def _play_call_overall_key(row: pd.Series) -> str:
    """Display play call for the overall board (Army Bear)."""
    for col in ("play_call", "call"):
        key = _clean_tag(row.get(col, ""))
        if key:
            return key
    return ""


def _play_call_mode_key(row: pd.Series) -> str:
    """
    Dual-tag RPO outcomes as `Army Bear · run` / `Army Bear · pass`.
    Single-tag snaps stay on the overall board only (empty mode key).
    """
    overall = _play_call_overall_key(row)
    if not overall:
        return ""
    run_tag = _clean_tag(row.get("run_tag", ""))
    pass_tag = _clean_tag(row.get("pass_tag", ""))
    if not (run_tag and pass_tag):
        return ""
    ptype = str(row.get("play_type") or "").strip().lower()
    if ptype not in {"run", "pass"}:
        return ""
    return f"{overall} · {ptype}"


def annotate_play_call_keys(log_df: pd.DataFrame) -> pd.DataFrame:
    """Add play_call_overall + play_call_mode columns for HT boards."""
    if log_df is None or log_df.empty:
        return pd.DataFrame()
    work = log_df.copy()
    work["play_call_overall"] = work.apply(_play_call_overall_key, axis=1)
    work["play_call_mode"] = work.apply(_play_call_mode_key, axis=1)
    return work


def _formation_play_key(row: pd.Series) -> str:
    form = str(row.get("formation", "") or "").strip()
    play = str(row.get("play_call", "") or row.get("call", "") or "").strip()
    if not form or form.lower() in {"nan", "none", "(none)"}:
        return ""
    if not play or play.lower() in {"nan", "none", "(none)", "(blank)"}:
        return ""
    return f"{form} | {play}"


def _offense_logs(log_df: pd.DataFrame) -> pd.DataFrame:
    if log_df is None or log_df.empty:
        return pd.DataFrame()
    if "unit" not in log_df.columns:
        return log_df.copy()
    return log_df[log_df["unit"].astype(str).str.lower() == "offense"].copy()


def _clean_tag(val) -> str:
    s = str(val or "").strip()
    if not s or s.lower() in {"nan", "none", "(none)", "(blank)", "?", "—"}:
        return ""
    return s


def _live_drive_starters(log_df: pd.DataFrame) -> pd.DataFrame:
    """First offensive snap of each drive_id (tonight)."""
    logs = _offense_logs(log_df)
    if logs.empty or "drive_id" not in logs.columns:
        return pd.DataFrame()
    work = logs.copy()
    work["_did"] = pd.to_numeric(work["drive_id"], errors="coerce")
    work = work[work["_did"].notna()]
    if work.empty:
        return pd.DataFrame()
    if "timestamp" in work.columns:
        work = work.sort_values(["_did", "timestamp"], kind="mergesort")
    else:
        work = work.sort_index(kind="mergesort")
    return work.groupby("_did", sort=False).head(1).drop(columns=["_did"], errors="ignore")


def _live_convert_downs(log_df: pd.DataFrame) -> pd.DataFrame:
    """3rd / 4th down offense snaps."""
    logs = _offense_logs(log_df)
    if logs.empty or "down" not in logs.columns:
        return pd.DataFrame()
    downs = pd.to_numeric(logs["down"], errors="coerce")
    return logs[downs.isin([3, 4])].copy()


def _score_vs_look(
    log_df: pd.DataFrame,
    group_col: str,
    look_col: str,
    *,
    min_plays: int = 2,
    limit: int = 12,
) -> list[dict]:
    """Score group_col (e.g. formation) broken down by a defense look column."""
    logs = _offense_logs(log_df)
    if logs.empty or group_col not in logs.columns or look_col not in logs.columns:
        return []
    work = logs.copy()
    work["_grp"] = work[group_col].map(_clean_tag)
    work["_look"] = work[look_col].map(_clean_tag)
    work = work[work["_grp"].ne("") & work["_look"].ne("")]
    if work.empty:
        return []
    work["_key"] = work["_grp"] + " vs " + work["_look"]
    scored = score_live_dimension(work, "_key", "Offense", min_plays=min_plays, label_name="label")
    if scored.empty:
        return []
    rows = []
    for _, r in scored.head(limit).iterrows():
        lab = str(r.get("label") or "")
        parts = lab.split(" vs ", 1)
        rows.append(
            {
                "label": lab,
                "formation": parts[0] if parts else lab,
                "look": parts[1] if len(parts) > 1 else "",
                "look_type": look_col,
                "plays": int(r.get("plays", 0) or 0),
                "good": int(r.get("good", 0) or 0),
                "bad": int(r.get("bad", 0) or 0),
                "score": round(float(r.get("score", 0) or 0), 3),
                "avg_yards": r.get("avg_yards"),
                "success_rate": r.get("success_rate"),
            }
        )
    return rows


def _scenario_board(
    log_df: pd.DataFrame,
    group_col: str,
    *,
    min_plays: int = 2,
    limit: int = 8,
) -> list[dict]:
    if log_df is None or log_df.empty or group_col not in log_df.columns:
        return []
    scored = score_live_dimension(
        log_df, group_col, "Offense", min_plays=min_plays, label_name="label"
    )
    return _dim_records(scored, limit=limit)


def _live_distance_bucket(row: pd.Series) -> str:
    """Normalize live-log distance to short / medium / long."""
    dist = str(row.get("distance") or "").strip().lower()
    if dist in {"short", "medium", "long"}:
        return dist
    try:
        y = float(row.get("distance_yards"))
    except (TypeError, ValueError):
        y = None
    if y is None:
        return ""
    if y <= 3:
        return "short"
    if y <= 6:
        return "medium"
    return "long"


def _filter_live_down(
    log_df: pd.DataFrame,
    down: int,
    distance_bucket: str | None = None,
) -> pd.DataFrame:
    logs = _offense_logs(log_df)
    if logs.empty or "down" not in logs.columns:
        return pd.DataFrame()
    work = logs[pd.to_numeric(logs["down"], errors="coerce") == int(down)].copy()
    if work.empty:
        return work
    if distance_bucket:
        work["_db"] = work.apply(_live_distance_bucket, axis=1)
        work = work[work["_db"] == str(distance_bucket).lower()]
        work = work.drop(columns=["_db"], errors="ignore")
    return work


def _pair_boards(
    live_df: pd.DataFrame,
    *,
    downs: list[int] | None = None,
    distance_bucket: str | None = None,
    first_and_ten: bool = False,
    live_min: int = 1,
    season_min: int = 4,
    limit: int = 6,
) -> dict:
    """Tonight + year formation/play boards for one situation slice."""
    return {
        "tonight_n": int(len(live_df)) if live_df is not None else 0,
        "overall": {
            "tonight": _live_slice_overall(live_df),
            "season": _season_slice_overall(
                downs=downs,
                distance_bucket=distance_bucket,
                first_and_ten=first_and_ten,
            ),
        },
        "formations": _scenario_board(live_df, "formation", min_plays=live_min, limit=limit),
        "plays": _scenario_board(live_df, "play_call", min_plays=live_min, limit=limit),
        "season_formations": _season_scenario_board(
            downs=downs,
            distance_buckets=[distance_bucket] if distance_bucket else None,
            first_and_ten=first_and_ten,
            group_col="formation",
            min_plays=season_min,
            limit=limit,
        ),
        "season_plays": _season_scenario_board(
            downs=downs,
            distance_buckets=[distance_bucket] if distance_bucket else None,
            first_and_ten=first_and_ten,
            group_col="play_call",
            min_plays=season_min,
            limit=limit,
        ),
    }


def _live_slice_overall(live_df: pd.DataFrame) -> dict:
    """Aggregate tonight EPA + result score for one situation slice."""
    empty = {
        "plays": 0,
        "avg_epa": None,
        "total_epa": None,
        "score": 0.0,
        "avg_yards": None,
        "success_rate": None,
    }
    if live_df is None or live_df.empty:
        return empty
    ep_table = _load_ep_table_from_season()
    epas = [_estimate_live_play_epa(row, ep_table) for _, row in live_df.iterrows()]
    n = int(len(epas))
    total = float(sum(epas))
    avg = total / n if n else 0.0
    good_set, bad_set = _live_result_sets("Offense")
    results = (
        live_df["result"].astype(str) if "result" in live_df.columns else pd.Series(dtype=str)
    )
    good = int(results.isin(good_set).sum()) if not results.empty else 0
    bad = int(results.isin(bad_set).sum()) if not results.empty else 0
    yards = (
        pd.to_numeric(live_df["yards_gained"], errors="coerce")
        if "yards_gained" in live_df.columns
        else pd.Series(dtype=float)
    )
    return {
        "plays": n,
        "avg_epa": round(avg, 3),
        "total_epa": round(total, 2),
        "score": round(good * 0.15 - bad * 0.20, 3),
        "avg_yards": round(float(yards.mean()), 2)
        if len(yards) and yards.notna().any()
        else None,
        "success_rate": round(good / n, 3) if n else None,
    }


def _season_slice_overall(
    *,
    downs: list[int] | None = None,
    distance_bucket: str | None = None,
    first_and_ten: bool = False,
) -> dict:
    """Year EPA for a down / distance slice (all tagged snaps, not by call)."""
    empty = {
        "plays": 0,
        "avg_epa": None,
        "success_rate": None,
    }
    df = load_table(
        "SELECT down, distance_bucket, epa, is_success, play_tagged, tags_ok "
        "FROM offense_plays_epa"
    )
    if df is None or df.empty:
        df = load_table(
            "SELECT down, distance_bucket, epa, is_success FROM offense_plays_epa"
        )
    if df is None or df.empty:
        return empty
    work = df.copy()
    if "play_tagged" in work.columns:
        work = work[pd.to_numeric(work["play_tagged"], errors="coerce").fillna(0) == 1]
    elif "tags_ok" in work.columns:
        work = work[pd.to_numeric(work["tags_ok"], errors="coerce").fillna(0) == 1]
    if downs:
        work = work[pd.to_numeric(work["down"], errors="coerce").isin(downs)]
    if distance_bucket:
        work = work[
            work["distance_bucket"].astype(str).str.lower() == str(distance_bucket).lower()
        ]
    if first_and_ten:
        work = work[
            (pd.to_numeric(work["down"], errors="coerce") == 1)
            & (work["distance_bucket"].astype(str).str.lower() == "long")
        ]
    if work.empty:
        return empty
    epa = pd.to_numeric(work["epa"], errors="coerce")
    succ = (
        pd.to_numeric(work["is_success"], errors="coerce")
        if "is_success" in work.columns
        else pd.Series(dtype=float)
    )
    n = int(len(work))
    avg_epa = float(epa.mean()) if epa.notna().any() else 0.0
    sr = float(succ.mean()) if len(succ) and succ.notna().any() else None
    return {
        "plays": n,
        "avg_epa": round(avg_epa, 3),
        "success_rate": round(sr, 3) if sr is not None else None,
    }


def _season_scenario_board(
    *,
    downs: list[int] | None = None,
    distance_buckets: list[str] | None = None,
    first_and_ten: bool = False,
    group_col: str = "formation",
    min_plays: int = 5,
    limit: int = 8,
) -> list[dict]:
    """Year-to-date EPA board for situation slices (down / distance)."""
    if group_col not in {"formation", "play_call", "formation_play"}:
        return []
    # Pull tag-quality flags when present (multi-season Hudl / prior years)
    df = load_table(
        f"SELECT {group_col}, down, distance_bucket, epa, is_success, "
        f"form_tagged, play_tagged, tags_ok, season "
        f"FROM offense_plays_epa"
    )
    if df is None or df.empty:
        df = load_table(
            f"SELECT {group_col}, down, distance_bucket, epa, is_success "
            f"FROM offense_plays_epa"
        )
    if df is None or df.empty or group_col not in df.columns:
        return []
    work = df.copy()
    work[group_col] = work[group_col].map(_clean_tag)
    work = work[work[group_col].ne("")]
    # Formation boards: current season only (prior-year formations are flawed).
    # Play-call boards: any season if play_tagged. EPA model still uses all snaps.
    if "season" in work.columns and group_col in {"formation", "formation_play"}:
        work = work[work["season"].map(_is_current_season_value)]
    if group_col == "formation" and "form_tagged" in work.columns:
        work = work[pd.to_numeric(work["form_tagged"], errors="coerce").fillna(0) == 1]
    elif group_col == "play_call" and "play_tagged" in work.columns:
        work = work[pd.to_numeric(work["play_tagged"], errors="coerce").fillna(0) == 1]
    elif group_col == "formation_play" and "tags_ok" in work.columns:
        work = work[pd.to_numeric(work["tags_ok"], errors="coerce").fillna(0) == 1]
    elif "tags_ok" in work.columns and group_col != "play_call":
        work = work[pd.to_numeric(work["tags_ok"], errors="coerce").fillna(0) == 1]
    if downs:
        work = work[pd.to_numeric(work["down"], errors="coerce").isin(downs)]
    if distance_buckets:
        wanted = {str(b).lower() for b in distance_buckets}
        work = work[work["distance_bucket"].astype(str).str.lower().isin(wanted)]
    if first_and_ten:
        # Season proxy for drive starters: 1st & long (usually 1st & 10)
        work = work[
            (pd.to_numeric(work["down"], errors="coerce") == 1)
            & (work["distance_bucket"].astype(str).str.lower() == "long")
        ]
    if work.empty:
        return []
    rows = []
    for label, grp in work.groupby(work[group_col]):
        n = int(len(grp))
        if n < min_plays:
            continue
        epa = pd.to_numeric(grp["epa"], errors="coerce")
        succ = (
            pd.to_numeric(grp["is_success"], errors="coerce")
            if "is_success" in grp.columns
            else pd.Series(dtype=float)
        )
        avg_epa = float(epa.mean()) if epa.notna().any() else 0.0
        sr = float(succ.mean()) if len(succ) and succ.notna().any() else None
        rows.append(
            {
                "label": str(label),
                "plays": n,
                "avg_epa": round(avg_epa, 3),
                "success_rate": round(sr, 3) if sr is not None else None,
                "score": round(avg_epa, 3),  # align sort key with live boards
                "good": int(succ.fillna(0).sum()) if len(succ) else 0,
                "bad": int(n - succ.fillna(0).sum()) if len(succ) else 0,
            }
        )
    rows.sort(key=lambda r: (float(r.get("avg_epa") or 0), int(r.get("plays") or 0)), reverse=True)
    return rows[:limit]


def _defense_look_key(row: pd.Series) -> str:
    front = _clean_tag(row.get("def_front"))
    cov = _clean_tag(row.get("coverage"))
    if "blitz" in row.index:
        blitz = "Blitz" if _is_blitz(row.get("blitz")) else "No blitz"
    else:
        blitz = ""
    bits = [b for b in (front, blitz, cov) if b]
    return " · ".join(bits)


def detect_standout_looks(
    log_df: pd.DataFrame,
    *,
    min_plays: int = 3,
    min_pct: float = 55.0,
    limit: int = 8,
) -> list[dict]:
    """
    Flag situation buckets where the defense repeats the same look
    (front · blitz · coverage) at a high rate — e.g. 2nd & long → Even · Blitz · Cover 3.
    """
    logs = _offense_logs(log_df)
    if logs.empty:
        return []
    need = {"coverage", "def_front"}
    if not need.issubset(set(logs.columns)):
        return []
    work = logs.copy()
    # Prefer down & distance bucket; fall back to situation string
    if {"down", "distance"}.issubset(work.columns):
        work["_sit"] = work["down"].astype(str) + " & " + work["distance"].astype(str)
    elif "situation" in work.columns:
        work["_sit"] = work["situation"].astype(str)
    else:
        return []
    work["_look"] = work.apply(_defense_look_key, axis=1)
    work = work[work["_look"].str.len() > 0]
    if work.empty:
        return []

    out: list[dict] = []
    for sit, grp in work.groupby(work["_sit"].astype(str)):
        n = int(len(grp))
        if n < min_plays:
            continue
        counts = grp["_look"].value_counts()
        if counts.empty:
            continue
        top_look = str(counts.index[0])
        top_n = int(counts.iloc[0])
        pct = round(100.0 * top_n / n, 1)
        if pct < min_pct:
            continue
        # Strength: prefer higher pct then larger sample
        out.append(
            {
                "situation": str(sit),
                "look": top_look,
                "plays": n,
                "look_plays": top_n,
                "pct": pct,
                "strength": round(pct * (n ** 0.5), 1),
                "message": (
                    f"On **{sit}** they showed **{top_look}** "
                    f"**{pct:.0f}%** of the time ({top_n}/{n})."
                ),
            }
        )
    out.sort(key=lambda r: (-float(r.get("strength") or 0), -int(r.get("plays") or 0)))
    return out[:limit]


def _coverage_dominance(mix: list[dict]) -> dict:
    """
    If 1–3 coverages dominate the half, breakdown charts by situation are noise.
    """
    if not mix:
        return {"dominant": False, "top": [], "top_pct": 0.0, "skip_breakdowns": False}
    ordered = sorted(mix, key=lambda r: -float(r.get("pct") or 0))
    top = ordered[:3]
    top_pct = round(sum(float(r.get("pct") or 0) for r in top), 1)
    lead = float(top[0].get("pct") or 0) if top else 0.0
    # One coverage ≥70%, or top 1–3 cover ≥85% of tagged snaps
    dominant = lead >= 70.0 or (len(top) <= 3 and top_pct >= 85.0 and lead >= 45.0)
    return {
        "dominant": dominant,
        "top": top,
        "top_pct": top_pct,
        "lead_pct": lead,
        "skip_breakdowns": dominant,
        "summary": " · ".join(
            f"{r.get('coverage')} {r.get('pct')}%" for r in top if r.get("coverage")
        ),
    }


def _dim_records(df: pd.DataFrame, limit: int = 8, label_name: str = "label") -> list[dict]:
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.head(limit).iterrows():
        out.append(
            {
                "label": str(r.get(label_name, r.get("call", ""))),
                "plays": int(r.get("plays", 0) or 0),
                "good": int(r.get("good", 0) or 0),
                "bad": int(r.get("bad", 0) or 0),
                "score": round(float(r.get("score", 0) or 0), 3),
                "avg_yards": r.get("avg_yards"),
                "success_rate": r.get("success_rate"),
            }
        )
    return out


def _scores_to_records(df: pd.DataFrame, limit: int = 8) -> list[dict]:
    if df is None or df.empty:
        return []
    out = []
    for r in df.head(limit).itertuples(index=False):
        out.append(
            {
                "call": str(r.call),
                "plays": int(r.plays),
                "good": int(r.good),
                "bad": int(r.bad),
                "score": round(float(r.score), 3),
            }
        )
    return out


def _situation_key(row: pd.Series) -> str:
    if "situation" in row.index and pd.notna(row.get("situation")) and str(row.get("situation")).strip():
        return str(row.get("situation")).strip()
    down = row.get("down", "?")
    dist = row.get("distance", "?")
    zone = row.get("field_zone", "?")
    return f"{down} & {dist} | {zone}"


def build_halftime_report(
    opponent: str,
    live_logs: pd.DataFrame,
    plan: dict,
    player_board: pd.DataFrame | None = None,
) -> dict:
    """Structured 1st-half adjustment report for the locker room."""
    from datetime import datetime

    half1 = filter_live_logs(live_logs, opponent=opponent, half=1)
    # Fallback to all tonight ONLY when half was never tagged (legacy / blank half)
    scope = "1st_half"
    if half1.empty:
        all_tonight = filter_live_logs(live_logs, opponent=opponent, half=None)
        if not all_tonight.empty and "half" in all_tonight.columns:
            half_num = pd.to_numeric(all_tonight["half"], errors="coerce")
            if half_num.isna().all():
                half1 = all_tonight
                scope = "all_logged_tonight"
            # else: keep empty — do not mix 2nd-half snaps into HT
        elif not all_tonight.empty:
            half1 = all_tonight
            scope = "all_logged_tonight"

    off_scores = score_live_calls(half1, "Offense", opponent, half=None)
    def_scores = score_live_calls(half1, "Defense", opponent, half=None)
    off_status = plan_pin_status(plan, "offense", off_scores)
    def_status = plan_pin_status(plan, "defense", def_scores)

    results = half1["result"].astype(str) if not half1.empty and "result" in half1.columns else pd.Series(dtype=str)
    units = half1["unit"].astype(str) if not half1.empty and "unit" in half1.columns else pd.Series(dtype=str)

    # Core tendency boards
    half1_sit = half1.copy()
    if not half1_sit.empty:
        half1_sit["situation_key"] = half1_sit.apply(_situation_key, axis=1)

    formations_o = score_live_dimension(half1, "formation", "Offense", min_plays=HT_MIN_SAMPLE)
    formations_d = score_live_dimension(half1, "formation", "Defense", min_plays=HT_MIN_SAMPLE)
    coverage_o = score_live_dimension(half1, "coverage", "Offense", min_plays=HT_MIN_SAMPLE)
    coverage_d = score_live_dimension(half1, "coverage", "Defense", min_plays=HT_MIN_SAMPLE)
    fronts_o = score_live_dimension(half1, "def_front", "Offense", min_plays=HT_MIN_SAMPLE)
    situations_o = score_live_dimension(
        half1_sit, "situation_key", "Offense", min_plays=HT_MIN_SAMPLE, label_name="label"
    )
    situations_d = score_live_dimension(
        half1_sit, "situation_key", "Defense", min_plays=HT_MIN_SAMPLE, label_name="label"
    )
    # Formation | play combos
    half1_fp = half1.copy()
    if not half1_fp.empty:
        half1_fp["formation_play"] = half1_fp.apply(_formation_play_key, axis=1)
        half1_fp = half1_fp[half1_fp["formation_play"].astype(str).str.len() > 0]
    combos_o = score_live_dimension(half1_fp, "formation_play", "Offense", min_plays=max(2, HT_MIN_SAMPLE - 1))
    combos_d = score_live_dimension(half1_fp, "formation_play", "Defense", min_plays=max(2, HT_MIN_SAMPLE - 1))

    # Play calls: overall (Army Bear) + dual-tag run/pass split (Army Bear · run)
    half1_pc = annotate_play_call_keys(half1)
    plays_overall_o = score_live_dimension(
        half1_pc, "play_call_overall", "Offense", min_plays=max(2, HT_MIN_SAMPLE - 1)
    )
    plays_overall_d = score_live_dimension(
        half1_pc, "play_call_overall", "Defense", min_plays=max(2, HT_MIN_SAMPLE - 1)
    )
    half1_mode = half1_pc[half1_pc["play_call_mode"].astype(str).str.len() > 0] if not half1_pc.empty else half1_pc
    plays_mode_o = score_live_dimension(
        half1_mode, "play_call_mode", "Offense", min_plays=max(1, HT_MIN_SAMPLE - 2)
    )
    plays_mode_d = score_live_dimension(
        half1_mode, "play_call_mode", "Defense", min_plays=max(1, HT_MIN_SAMPLE - 2)
    )

    # Down & distance (shorter labels for charts)
    if not half1.empty and {"down", "distance"}.issubset(half1.columns):
        half1_dd = half1.copy()
        half1_dd["down_distance"] = (
            half1_dd["down"].astype(str) + " & " + half1_dd["distance"].astype(str)
        )
    else:
        half1_dd = half1
    down_dist_o = score_live_dimension(half1_dd, "down_distance", "Offense", min_plays=HT_MIN_SAMPLE)
    down_dist_d = score_live_dimension(half1_dd, "down_distance", "Defense", min_plays=HT_MIN_SAMPLE)

    blitz_o = analyze_live_blitz(half1, "Offense")
    blitz_d = analyze_live_blitz(half1, "Defense")
    # Overall blitz rate across all logged snaps with a blitz tag
    blitz_all = analyze_live_blitz(half1, unit=None)
    coverage_tend_o = analyze_live_coverage(half1, "Offense")
    coverage_tend_d = analyze_live_coverage(half1, "Defense")

    # Scenario boards — tonight + season (by down, convert distance, drive openers)
    convert_live = _live_convert_downs(half1)
    openers_live = _live_drive_starters(half1)

    def _with_combo_key(frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or frame.empty:
            return pd.DataFrame()
        out = frame.copy()
        out["formation_play"] = out.apply(_formation_play_key, axis=1)
        return out[out["formation_play"].astype(str).str.len() > 0]

    convert_fp = _with_combo_key(convert_live)
    openers_fp = _with_combo_key(openers_live)

    down_labels = {1: "1st down", 2: "2nd down", 3: "3rd down", 4: "4th down"}
    by_down: dict = {}
    for d in (1, 2, 3, 4):
        live_d = _filter_live_down(half1, d)
        block = {
            "label": down_labels[d],
            "down": d,
            **_pair_boards(
                live_d,
                downs=[d],
                live_min=1 if d >= 3 else 2,
                season_min=4 if d <= 2 else 3,
                limit=6,
            ),
        }
        by_dist: dict = {}
        for bucket in ("short", "medium", "long"):
            live_b = _filter_live_down(half1, d, bucket)
            by_dist[bucket] = {
                "label": f"{down_labels[d]} & {bucket}",
                "distance": bucket,
                **_pair_boards(
                    live_b,
                    downs=[d],
                    distance_bucket=bucket,
                    live_min=1,
                    season_min=3 if d >= 3 else 4,
                    limit=6,
                ),
            }
        block["by_distance"] = by_dist
        by_down[str(d)] = block

    scenarios = {
        "by_down": by_down,
        "convert": {
            "label": "Gotta convert (3rd / 4th overall)",
            "tonight_n": int(len(convert_live)),
            "formations": _scenario_board(convert_live, "formation", min_plays=2, limit=8),
            "plays": _scenario_board(convert_live, "play_call", min_plays=2, limit=8),
            "combos": _scenario_board(convert_fp, "formation_play", min_plays=2, limit=8),
            "season_formations": _season_scenario_board(
                downs=[3, 4], group_col="formation", min_plays=5, limit=8
            ),
            "season_plays": _season_scenario_board(
                downs=[3, 4], group_col="play_call", min_plays=5, limit=8
            ),
        },
        "drive_start": {
            "label": "Drive starters (1st snap of drive)",
            "tonight_n": int(len(openers_live)),
            "formations": _scenario_board(openers_live, "formation", min_plays=1, limit=8),
            "plays": _scenario_board(openers_live, "play_call", min_plays=1, limit=8),
            "combos": _scenario_board(openers_fp, "formation_play", min_plays=1, limit=8),
            "season_note": "Year board uses 1st & long as drive-start proxy.",
            "season_formations": _season_scenario_board(
                first_and_ten=True, group_col="formation", min_plays=5, limit=8
            ),
            "season_plays": _season_scenario_board(
                first_and_ten=True, group_col="play_call", min_plays=5, limit=8
            ),
        },
    }

    form_vs_cov = _score_vs_look(half1, "formation", "coverage", min_plays=2, limit=14)
    form_vs_front = _score_vs_look(half1, "formation", "def_front", min_plays=2, limit=14)
    combo_vs_cov = _score_vs_look(half1_fp, "formation_play", "coverage", min_plays=2, limit=12)
    standouts = detect_standout_looks(half1, min_plays=3, min_pct=55.0, limit=8)
    cov_dom = _coverage_dominance(coverage_tend_o.get("mix") or [])
    coverage_tend_o["dominance"] = cov_dom
    if cov_dom.get("skip_breakdowns"):
        # Avoid redundant "100% Cover X in every bucket" chart noise
        coverage_tend_o["by_formation"] = []
        coverage_tend_o["by_field_zone"] = []
        coverage_tend_o["by_down_distance"] = []

    def _thin_filter(block: dict, keys: list[str], plays_key: str = "plays") -> dict:
        out = dict(block)
        for k in keys:
            rows = out.get(k) or []
            out[k] = [r for r in rows if int(r.get(plays_key, 0) or 0) >= HT_MIN_SAMPLE]
        return out

    blitz_o = _thin_filter(
        blitz_o, ["by_formation", "by_field_zone", "by_down_distance", "by_situation", "by_coverage"]
    )
    blitz_d = _thin_filter(
        blitz_d, ["by_formation", "by_field_zone", "by_down_distance", "by_situation", "by_coverage"]
    )
    coverage_tend_o = _thin_filter(
        coverage_tend_o,
        ["by_formation", "by_field_zone", "by_down_distance"],
        plays_key="group_plays",
    )
    coverage_tend_d = _thin_filter(
        coverage_tend_d,
        ["by_formation", "by_field_zone", "by_down_distance"],
        plays_key="group_plays",
    )
    # Coverage mix: keep labels with n>=min
    if coverage_tend_o.get("mix"):
        coverage_tend_o["mix"] = [
            r for r in coverage_tend_o["mix"] if int(r.get("plays", 0) or 0) >= HT_MIN_SAMPLE
        ]
    if coverage_tend_d.get("mix"):
        coverage_tend_d["mix"] = [
            r for r in coverage_tend_d["mix"] if int(r.get("plays", 0) or 0) >= HT_MIN_SAMPLE
        ]

    xp_o = live_half_xp(half1, "Offense")
    xp_d = live_half_xp(half1, "Defense")

    summary = {
        "plays": int(len(half1)),
        "offense_plays": int((units.str.lower() == "offense").sum()) if not units.empty else 0,
        "defense_plays": int((units.str.lower() == "defense").sum()) if not units.empty else 0,
        "tds": int((results == "TD").sum()) if not results.empty else 0,
        "turnovers": int((results == "Turnover").sum()) if not results.empty else 0,
        "sacks_tfl": int((results == "Sack / TFL").sum()) if not results.empty else 0,
        "blitz_pct": blitz_all.get("blitz_pct", 0.0),
        "blitz_plays": blitz_all.get("blitz_plays", 0),
        "actual_points": xp_o.get("actual_points", 0),
        "xpoints": xp_o.get("xpoints", 0.0),
        "luck": xp_o.get("luck", 0.0),
        "scope": scope,
    }

    working_o = off_scores[off_scores["score"] > 0.05] if not off_scores.empty else off_scores
    working_d = def_scores[def_scores["score"] > 0.05] if not def_scores.empty else def_scores
    buried_o = off_scores[off_scores["score"] < -0.05] if not off_scores.empty else off_scores
    buried_d = def_scores[def_scores["score"] < -0.05] if not def_scores.empty else def_scores

    adjustments: list[str] = []
    for unit, status in (("Offense", off_status), ("Defense", def_status)):
        kills = [c for c, t in status.items() if t == "kill"]
        conf = [c for c, t in status.items() if t == "confirmed"]
        unprov = [c for c, t in status.items() if t == "unproven"]
        for c in kills:
            adjustments.append(f"KILL ({unit}): shelve `{c}` — 1st half evidence is negative.")
        for c in conf:
            adjustments.append(f"LEAN ({unit}): keep featuring `{c}` — confirmed tonight.")
        for c in unprov:
            adjustments.append(f"TEST ({unit}): `{c}` still unproven — sample or cut.")

    for rec in _scores_to_records(working_o, 3):
        adjustments.append(
            f"OFFENSE hot: `{rec['call']}` ({rec['good']} good / {rec['bad']} bad, n={rec['plays']})."
        )
    for rec in _scores_to_records(buried_o, 3):
        adjustments.append(
            f"OFFENSE cold: avoid `{rec['call']}` ({rec['good']} good / {rec['bad']} bad, n={rec['plays']})."
        )
    for rec in _scores_to_records(working_d, 3):
        adjustments.append(
            f"DEFENSE hot: `{rec['call']}` ({rec['good']} good / {rec['bad']} bad, n={rec['plays']})."
        )
    for rec in _scores_to_records(buried_d, 3):
        adjustments.append(
            f"DEFENSE cold: avoid `{rec['call']}` ({rec['good']} good / {rec['bad']} bad, n={rec['plays']})."
        )

    # Primary callouts: blitz situations, formations, combos, players
    if blitz_o.get("plays"):
        adjustments.append(
            f"BLITZ: **{blitz_o['blitz_pct']}%** "
            f"({blitz_o['blitz_plays']}/{blitz_o['plays']})."
        )
        for sit in (blitz_o.get("by_down_distance") or [])[:3]:
            if sit.get("blitz_pct", 0) >= 25 and sit.get("plays", 0) >= 2:
                adjustments.append(
                    f"BLITZ situation: `{sit['down_distance']}` — "
                    f"{sit['blitz_pct']}% ({sit.get('blitz_plays', 0)}/{sit['plays']})."
                )
        for sit in (blitz_o.get("by_situation") or [])[:2]:
            if sit.get("blitz_plays", 0) >= 1 and sit.get("blitz_pct", 0) >= 40:
                adjustments.append(
                    f"BLITZ situation: `{sit['situation']}` — "
                    f"{sit['blitz_pct']}% ({sit.get('blitz_plays', 0)}/{sit['plays']})."
                )

    for rec in _dim_records(formations_o, 2):
        if rec["score"] > 0.05:
            adjustments.append(
                f"FORMATION lean: `{rec['label']}` (score {rec['score']:+.2f}, n={rec['plays']})."
            )
    cold_form = formations_o[formations_o["score"] < -0.05] if not formations_o.empty else formations_o
    for rec in _dim_records(cold_form.sort_values("score"), 2):
        adjustments.append(
            f"FORMATION cold: `{rec['label']}` (score {rec['score']:+.2f}, n={rec['plays']})."
        )

    hot_combo = combos_o[combos_o["score"] > 0.05] if not combos_o.empty else combos_o
    cold_combo = combos_o[combos_o["score"] < -0.05] if not combos_o.empty else combos_o
    for rec in _dim_records(hot_combo, 3):
        adjustments.append(
            f"COMBO lean: `{rec['label']}` (score {rec['score']:+.2f}, n={rec['plays']})."
        )
    for rec in _dim_records(cold_combo.sort_values("score"), 2):
        adjustments.append(
            f"COMBO cold: `{rec['label']}` (score {rec['score']:+.2f}, n={rec['plays']})."
        )

    for srow in standouts[:5]:
        adjustments.append(f"LOOK: {srow.get('message')}")

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_adj: list[str] = []
    for a in adjustments:
        if a not in seen:
            seen.add(a)
            unique_adj.append(a)

    players: list[dict] = []
    if player_board is not None and not player_board.empty:
        board = player_board.copy()
        sort_col = "plus_minus" if "plus_minus" in board.columns else None
        if sort_col:
            # Prefer players with a real sample
            if "snaps" in board.columns:
                sampled = board[board["snaps"].fillna(0).astype(int) >= 2]
                if sampled.empty:
                    sampled = board
            else:
                sampled = board
            # One row per player (best active pos by abs +/-)
            sampled = sampled.copy()
            sampled["_abs"] = sampled[sort_col].abs()
            sampled = (
                sampled.sort_values(["player", "_abs", "snaps"], ascending=[True, False, False])
                .drop_duplicates(subset=["player"], keep="first")
            )
            top = sampled.sort_values(sort_col, ascending=False).head(4)
            bot = sampled.sort_values(sort_col, ascending=True).head(3)
            seen_names: set[str] = set()
            for label, chunk in (("up", top), ("down", bot)):
                for _, row in chunk.iterrows():
                    name = str(row.get("player", ""))
                    if not name or name in seen_names:
                        continue
                    # Skip near-zero noise on the "down" board if already featured up
                    pm = float(row.get("plus_minus", 0) or 0)
                    if label == "up" and pm <= 0:
                        continue
                    if label == "down" and pm >= 0:
                        continue
                    seen_names.add(name)
                    players.append(
                        {
                            "player": name,
                            "active_pos": str(row.get("active_pos", "—")),
                            "snaps": int(row.get("snaps", 0) or 0),
                            "plus_minus": pm,
                            "band": label,
                        }
                    )
            for p in players:
                if p["band"] == "up":
                    adjustments.append(
                        f"PLAYER up: `{p['player']}` @{p['active_pos']} "
                        f"({p['plus_minus']:+.2f}, {p['snaps']} snaps)."
                    )
            for p in players:
                if p["band"] == "down":
                    adjustments.append(
                        f"PLAYER down: `{p['player']}` @{p['active_pos']} "
                        f"({p['plus_minus']:+.2f}, {p['snaps']} snaps)."
                    )

    # Re-dedupe after player lines
    seen = set()
    unique_adj = []
    for a in adjustments:
        if a not in seen:
            seen.add(a)
            unique_adj.append(a)

    report = {
        "opponent": opponent,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "version": 9,
        "summary": summary,
        "working": {
            "offense": _scores_to_records(working_o),
            "defense": _scores_to_records(working_d),
        },
        "not_working": {
            "offense": _scores_to_records(buried_o),
            "defense": _scores_to_records(buried_d),
        },
        "plan_status": {
            "offense": off_status,
            "defense": def_status,
        },
        "formations": {
            "offense": _dim_records(formations_o),
            "defense": _dim_records(formations_d),
        },
        "formation_play": {
            "offense": _dim_records(combos_o, limit=12),
            "defense": _dim_records(combos_d, limit=12),
        },
        "play_calls": {
            "overall": {
                "offense": _dim_records(plays_overall_o, limit=12),
                "defense": _dim_records(plays_overall_d, limit=12),
            },
            "by_mode": {
                "offense": _dim_records(plays_mode_o, limit=12),
                "defense": _dim_records(plays_mode_d, limit=12),
            },
        },
        "formation_vs_look": {
            "vs_coverage": form_vs_cov,
            "vs_front": form_vs_front,
            "combo_vs_coverage": combo_vs_cov,
        },
        "scenarios": scenarios,
        "standout_looks": standouts,
        "coverage": {
            "offense": _dim_records(coverage_o),
            "defense": _dim_records(coverage_d),
        },
        "fronts": {
            "offense": _dim_records(fronts_o),
        },
        "situations": {
            "offense": _dim_records(situations_o),
            "defense": _dim_records(situations_d),
        },
        "down_distance": {
            "offense": _dim_records(down_dist_o),
            "defense": _dim_records(down_dist_d),
        },
        "blitz": {
            "overall": blitz_all,
            "offense": blitz_o,
            "defense": blitz_d,
        },
        "coverage_tendencies": {
            "offense": coverage_tend_o,
            "defense": coverage_tend_d,
        },
        "xp": {
            "offense": xp_o,
            "defense": xp_d,
        },
        "adjustments": unique_adj,
        "players": players,
    }
    return report


def format_halftime_report_markdown(report: dict) -> str:
    """Short printable — blitz/coverage tendencies, formations, combos, xP, players."""
    opp = report.get("opponent", "Unknown")
    when = report.get("generated_at", "")
    s = report.get("summary", {})
    xp = (report.get("xp") or {}).get("offense") or {}
    lines = [
        f"# Halftime — vs {opp}",
        f"_{when}_ · {s.get('plays', 0)} plays · blitz **{s.get('blitz_pct', 0)}%** · "
        f"TO {s.get('turnovers', 0)} · Sack/TFL {s.get('sacks_tfl', 0)}",
    ]
    if xp.get("plays"):
        luck = xp.get("luck", 0)
        verb = "OVER" if luck > 0.5 else ("UNDER" if luck < -0.5 else "ON")
        lines.append(
            f"- **xP:** actual {xp.get('actual_points', 0)} · "
            f"xPoints {xp.get('xpoints', 0)} · luck {luck:+.1f} ({verb} process)"
        )

    def _short_board(title: str, rows: list[dict], n: int = 3) -> None:
        if not rows:
            return
        ordered = sorted(rows, key=lambda r: float(r.get("score") or 0), reverse=True)
        tops = ordered[:n]
        bots = [r for r in reversed(ordered) if float(r.get("score") or 0) < 0][:2]
        lines.append("")
        lines.append(f"## {title}")
        for r in tops:
            lab = r.get("label") or r.get("call")
            lines.append(f"- ▲ `{lab}` {r.get('score', 0):+.2f} (n={r.get('plays', 0)})")
        for r in bots:
            lab = r.get("label") or r.get("call")
            lines.append(f"- ▼ `{lab}` {r.get('score', 0):+.2f} (n={r.get('plays', 0)})")

    blitz = (report.get("blitz") or {}).get("offense") or {}
    if blitz.get("plays"):
        lines.append("")
        lines.append("## When they blitz")
        lines.append(
            f"- Overall **{blitz.get('blitz_pct', 0)}%** "
            f"({blitz.get('blitz_plays', 0)}/{blitz.get('plays', 0)})"
        )
        for title, key, label_key in (
            ("vs formation", "by_formation", "formation"),
            ("field position", "by_field_zone", "field_zone"),
            ("down & distance", "by_down_distance", "down_distance"),
        ):
            rows = blitz.get(key) or []
            hot = [r for r in rows if r.get("blitz_pct", 0) >= 25 or r.get("blitz_plays", 0) >= 1][:5]
            if not hot:
                continue
            lines.append(f"- **{title}:**")
            for row in hot:
                lines.append(
                    f"  - `{row.get(label_key)}`: **{row.get('blitz_pct', 0)}%** "
                    f"({row.get('blitz_plays', 0)}/{row.get('plays', 0)})"
                )

    standouts = report.get("standout_looks") or []
    if standouts:
        lines.append("")
        lines.append("## Standout looks")
        for row in standouts[:6]:
            lines.append(f"- {row.get('message', '')}")

    cov = (report.get("coverage_tendencies") or {}).get("offense") or {}
    if cov.get("plays"):
        lines.append("")
        lines.append("## Coverage")
        mix = cov.get("mix") or []
        dom = cov.get("dominance") or {}
        if mix:
            lines.append(
                "- Mix: "
                + ", ".join(f"`{r['coverage']}` {r['pct']}%" for r in mix[:5])
            )
        if dom.get("skip_breakdowns"):
            lines.append("- Coverage is concentrated — situation breakdowns omitted.")
        else:
            for title, key, label_key in (
                ("vs formation", "by_formation", "formation"),
                ("field position", "by_field_zone", "field_zone"),
                ("down & distance", "by_down_distance", "down_distance"),
            ):
                rows = cov.get(key) or []
                best: dict[str, dict] = {}
                for r in rows:
                    dim = str(r.get(label_key, ""))
                    if dim not in best or r.get("pct", 0) > best[dim].get("pct", 0):
                        best[dim] = r
                top_dims = sorted(best.values(), key=lambda r: -r.get("group_plays", 0))[:5]
                if not top_dims:
                    continue
                lines.append(f"- **{title}:**")
                for row in top_dims:
                    lines.append(
                        f"  - `{row.get(label_key)}` → Cover `{row.get('coverage')}` "
                        f"**{row.get('pct', 0)}%** (n={row.get('group_plays', 0)})"
                    )

    _short_board("Formations working", (report.get("formations") or {}).get("offense") or [])
    vs_cov = (report.get("formation_vs_look") or {}).get("vs_coverage") or []
    if vs_cov:
        _short_board("Formations vs coverage", vs_cov, n=4)
    _short_board(
        "Formation | Play combos",
        (report.get("formation_play") or {}).get("offense") or [],
        n=4,
    )
    play_calls = report.get("play_calls") or {}
    _short_board(
        "Play calls overall",
        (play_calls.get("overall") or {}).get("offense") or [],
        n=4,
    )
    _short_board(
        "Play calls · run vs pass",
        (play_calls.get("by_mode") or {}).get("offense") or [],
        n=4,
    )

    scenarios = report.get("scenarios") or {}

    def _md_board(title: str, rows: list[dict], n: int = 3) -> None:
        if not rows:
            return
        lines.append(f"- **{title}:**")
        for r in rows[:n]:
            lab = r.get("label")
            if r.get("avg_epa") is not None:
                lines.append(
                    f"  - `{lab}` EPA {float(r.get('avg_epa') or 0):+.2f} (n={r.get('plays', 0)})"
                )
            else:
                lines.append(
                    f"  - `{lab}` {float(r.get('score') or 0):+.2f} (n={r.get('plays', 0)})"
                )

    by_down = scenarios.get("by_down") or {}
    for d_key in ("1", "2", "3", "4"):
        block = by_down.get(d_key) or {}
        if not block:
            continue
        lines.append("")
        lines.append(f"## {block.get('label', d_key)} (tonight n={block.get('tonight_n', 0)})")
        overall = block.get("overall") or {}
        ton = overall.get("tonight") or {}
        sea = overall.get("season") or {}
        ov_bits = []
        if ton.get("plays") and ton.get("avg_epa") is not None:
            ov_bits.append(f"tonight EPA {float(ton['avg_epa']):+.2f} (n={ton['plays']})")
        if sea.get("plays") and sea.get("avg_epa") is not None:
            ov_bits.append(f"year EPA {float(sea['avg_epa']):+.2f} (n={sea['plays']})")
        if ov_bits:
            lines.append(f"- **Overall:** {' · '.join(ov_bits)}")
        _md_board("Tonight formations", block.get("formations") or [])
        _md_board("Tonight plays", block.get("plays") or [])
        _md_board("Year formations", block.get("season_formations") or [])
        _md_board("Year plays", block.get("season_plays") or [])
        if block.get("by_distance"):
            for bucket in ("short", "medium", "long"):
                sub = (block.get("by_distance") or {}).get(bucket) or {}
                if not sub or not (
                    sub.get("formations")
                    or sub.get("season_formations")
                    or (sub.get("overall") or {}).get("tonight", {}).get("plays")
                ):
                    continue
                lines.append(f"- **& {bucket}** (n={sub.get('tonight_n', 0)}):")
                sub_ov = sub.get("overall") or {}
                sub_ton = sub_ov.get("tonight") or {}
                sub_sea = sub_ov.get("season") or {}
                sub_bits = []
                if sub_ton.get("plays") and sub_ton.get("avg_epa") is not None:
                    sub_bits.append(
                        f"tonight EPA {float(sub_ton['avg_epa']):+.2f} (n={sub_ton['plays']})"
                    )
                if sub_sea.get("plays") and sub_sea.get("avg_epa") is not None:
                    sub_bits.append(
                        f"year EPA {float(sub_sea['avg_epa']):+.2f} (n={sub_sea['plays']})"
                    )
                if sub_bits:
                    lines.append(f"  - **Overall:** {' · '.join(sub_bits)}")
                _md_board("  Tonight formations", sub.get("formations") or [])
                _md_board("  Tonight plays", sub.get("plays") or [])
                _md_board("  Year formations", sub.get("season_formations") or [])
                _md_board("  Year plays", sub.get("season_plays") or [])

    for key in ("convert", "drive_start"):
        block = scenarios.get(key) or {}
        if not block:
            continue
        lines.append("")
        lines.append(f"## {block.get('label', key)} (tonight n={block.get('tonight_n', 0)})")
        _md_board("Formations", block.get("formations") or [])
        _md_board("Plays", block.get("plays") or [])
        _md_board("Year formations", block.get("season_formations") or [])
        _md_board("Year plays", block.get("season_plays") or [])

    players = report.get("players") or []
    if players:
        lines.append("")
        lines.append("## Standout players")
        for p in players:
            mark = "▲" if p.get("band") == "up" else "▼"
            lines.append(
                f"- {mark} **{p.get('player')}** @{p.get('active_pos', '—')} · "
                f"{p.get('plus_minus', 0):+.2f} · {p.get('snaps', 0)} snaps"
            )

    lines.append("")
    lines.append("_2nd half: feature hot formations/combos; expect blitz/coverage in those spots._")
    return "\n".join(lines)


def save_halftime_report(report: dict) -> Path:
    import json

    HALFTIME_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(
        ch if ch.isalnum() or ch in "-_ " else "_"
        for ch in str(report.get("opponent", "Unknown"))
    ).strip() or "Unknown"
    stamp = str(report.get("generated_at", "")).replace(":", "").replace("T", "_")
    path = HALFTIME_REPORTS_DIR / f"{safe}_{stamp or 'report'}.json"
    path.write_text(json.dumps(report, indent=2))
    md_path = path.with_suffix(".md")
    md_path.write_text(format_halftime_report_markdown(report))
    return path


def end_first_half(opponent: str, live_logs: pd.DataFrame, plan: dict, player_board=None) -> dict:
    """Mark 1st half over, build+save report, update game phase."""
    report = build_halftime_report(opponent, live_logs, plan, player_board=player_board)
    path = save_halftime_report(report)
    state = {
        "opponent": opponent,
        "phase": "halftime",
        "halftime_at": report["generated_at"],
        # Store relative paths so reports still open if the project folder moves
        "report_path": str(path.relative_to(PROJECT_DIR)) if path.is_relative_to(PROJECT_DIR) else path.name,
        "report_md": str(path.with_suffix(".md").relative_to(PROJECT_DIR))
        if path.with_suffix(".md").is_relative_to(PROJECT_DIR)
        else path.with_suffix(".md").name,
    }
    save_game_state(state)
    return {"state": state, "report": report, "markdown": format_halftime_report_markdown(report)}

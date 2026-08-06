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


def load_table(sql: str) -> pd.DataFrame:
    if not DB_FILE.exists():
        return pd.DataFrame()
    with sqlite3.connect(DB_FILE) as conn:
        try:
            return pd.read_sql(sql, conn)
        except Exception:
            return pd.DataFrame()


def load_scout(role: str | None = None, opponent: str | None = None) -> pd.DataFrame:
    df = load_table("SELECT * FROM scout_plays")
    if df.empty:
        return df
    if role:
        df = df[df["scout_role"] == role]
    if opponent and str(opponent).strip() and "opponent" in df.columns:
        df = df[df["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()]
    return df


def load_season_opponents() -> list[str]:
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


def load_live_log() -> pd.DataFrame:
    if not LIVE_LOG_FILE.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(LIVE_LOG_FILE)
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
        filtered = unit_logs[
            unit_logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
        ]
        if not filtered.empty:
            unit_logs = filtered

    if half is not None and "half" in unit_logs.columns:
        half_logs = unit_logs[unit_logs["half"].astype(str) == str(half)]
        if not half_logs.empty:
            unit_logs = half_logs

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
        filt = logs[logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()]
        if not filt.empty:
            logs = filt
    if half is not None and "half" in logs.columns:
        logs = logs[logs["half"].astype(str) == str(half)]
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

    GAME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Prefer atomic-ish write under lock when available
    try:
        from file_lock import file_lock

        with file_lock(GAME_STATE_FILE):
            tmp = GAME_STATE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, indent=2))
            tmp.replace(GAME_STATE_FILE)
    except Exception:
        GAME_STATE_FILE.write_text(json.dumps(state, indent=2))
    return GAME_STATE_FILE


def filter_live_logs(
    log_df: pd.DataFrame,
    opponent: str | None = None,
    half: int | None = None,
) -> pd.DataFrame:
    if log_df is None or log_df.empty:
        return pd.DataFrame()
    logs = log_df.copy()
    if opponent and "opponent" in logs.columns:
        filt = logs[logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()]
        if not filt.empty:
            logs = filt
    if half is not None and "half" in logs.columns:
        logs = logs[logs["half"].astype(str) == str(half)]
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
        s = season["season"].fillna("current").astype(str).str.strip().str.lower()
        season = season[s.isin({"current", "25-26", ""})]
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
        s = work["season"].fillna("current").astype(str).str.strip().str.lower()
        work = work[s.isin({"current", "25-26", ""})]
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
    # If nothing tagged half=1 yet, fall back to all tonight (legacy logs)
    scope = "1st_half"
    if half1.empty:
        half1 = filter_live_logs(live_logs, opponent=opponent, half=None)
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
        if d in (3, 4):
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
                        season_min=3,
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
        "version": 8,
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
        _md_board("Tonight formations", block.get("formations") or [])
        _md_board("Tonight plays", block.get("plays") or [])
        _md_board("Year formations", block.get("season_formations") or [])
        _md_board("Year plays", block.get("season_plays") or [])
        if block.get("by_distance"):
            for bucket in ("short", "medium", "long"):
                sub = (block.get("by_distance") or {}).get(bucket) or {}
                if not sub or not (sub.get("formations") or sub.get("season_formations")):
                    continue
                lines.append(f"- **& {bucket}** (n={sub.get('tonight_n', 0)}):")
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
        "report_path": str(path),
        "report_md": str(path.with_suffix(".md")),
    }
    save_game_state(state)
    return {"state": state, "report": report, "markdown": format_halftime_report_markdown(report)}

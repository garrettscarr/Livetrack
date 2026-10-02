"""
Shared booth snap pointer: Drive # + Play # for parallel tagging.

Main owns booth_snap.json (advances after each LOG; resets on Start drive).
Taggers keep their own play index, sync only when a new drive opens, and
upsert film fields onto the same drive_id + play_n row so packs merge when
both sides have tagged that play — neither waits on the other's pace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
BOOTH_SNAP_FILE = PROJECT_DIR / "data" / "booth_snap.json"

_EMPTY = {
    "opponent": None,
    "drive_id": None,
    "play_n": 1,
    "half": 1,
}


def load_booth_snap() -> dict:
    if not BOOTH_SNAP_FILE.exists():
        return dict(_EMPTY)
    try:
        from file_lock import file_lock

        with file_lock(BOOTH_SNAP_FILE):
            raw = json.loads(BOOTH_SNAP_FILE.read_text(encoding="utf-8"))
    except Exception:
        try:
            raw = json.loads(BOOTH_SNAP_FILE.read_text(encoding="utf-8"))
        except Exception:
            return dict(_EMPTY)
    out = dict(_EMPTY)
    out.update(raw or {})
    try:
        out["play_n"] = max(1, int(out.get("play_n") or 1))
    except (TypeError, ValueError):
        out["play_n"] = 1
    if out.get("drive_id") is not None:
        try:
            out["drive_id"] = int(out["drive_id"])
        except (TypeError, ValueError):
            out["drive_id"] = None
    return out


def save_booth_snap(state: dict) -> None:
    from file_lock import file_lock

    BOOTH_SNAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "opponent": state.get("opponent"),
        "drive_id": state.get("drive_id"),
        "play_n": int(state.get("play_n") or 1),
        "half": int(state.get("half") or 1),
    }
    with file_lock(BOOTH_SNAP_FILE):
        tmp = BOOTH_SNAP_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(BOOTH_SNAP_FILE)


def reset_booth_snap_for_drive(
    opponent: str,
    drive_id: int,
    *,
    half: int = 1,
    play_n: int = 1,
) -> dict:
    """Call when a drive starts — play numbering restarts at 1 (or resume play_n)."""
    state = {
        "opponent": opponent,
        "drive_id": int(drive_id),
        "play_n": max(1, int(play_n)),
        "half": int(half or 1),
    }
    save_booth_snap(state)
    return state


def sync_booth_snap_to_drive(
    opponent: str,
    drive_id: int,
    *,
    half: int = 1,
    live_logs=None,
) -> dict:
    """
    Ensure pointer is on this drive. New drive → play 1.
    Same drive → keep play_n (or bump past max logged if somehow behind).
    """
    state = load_booth_snap()
    did = int(drive_id)
    if state.get("drive_id") != did:
        max_n = max_play_n_for_drive(live_logs, did) if live_logs is not None else 0
        return reset_booth_snap_for_drive(
            opponent,
            did,
            half=half,
            play_n=(max_n + 1) if max_n else 1,
        )
    # Keep ahead of anything already in the log
    if live_logs is not None:
        max_n = max_play_n_for_drive(live_logs, did)
        cur = int(state.get("play_n") or 1)
        if max_n >= cur:
            # Pointer should be the next open slot after highest complete-ish play,
            # but if taggers created stubs at cur, stay on cur until Main logs.
            # Only bump if every play through max_n exists and pointer is stale empty.
            pass
    new_opp = opponent or state.get("opponent")
    new_half = int(half or state.get("half") or 1)
    if state.get("opponent") == new_opp and int(state.get("half") or 1) == new_half:
        return state
    state["opponent"] = new_opp
    state["half"] = new_half
    save_booth_snap(state)
    return state


def advance_booth_snap(drive_id: int | None = None) -> dict:
    """After Main LOGs the current play — move to next play # on this drive."""
    state = load_booth_snap()
    if drive_id is not None and state.get("drive_id") is not None:
        if int(state["drive_id"]) != int(drive_id):
            return state
    state["play_n"] = int(state.get("play_n") or 1) + 1
    save_booth_snap(state)
    return state


def set_booth_snap_play(
    drive_id: int,
    play_n: int,
    *,
    opponent: str | None = None,
    half: int | None = None,
) -> dict:
    """Move the shared pointer (Main / catch-up)."""
    state = load_booth_snap()
    state["drive_id"] = int(drive_id)
    state["play_n"] = max(1, int(play_n))
    if opponent:
        state["opponent"] = opponent
    if half is not None:
        state["half"] = int(half)
    save_booth_snap(state)
    return state


def _as_int(val) -> int | None:
    try:
        if val is None or (isinstance(val, float) and val != val):
            return None
        return int(float(val))
    except (TypeError, ValueError):
        return None


def max_play_n_for_drive(live_logs, drive_id: int) -> int:
    if live_logs is None or getattr(live_logs, "empty", True):
        return 0
    if "drive_id" not in live_logs.columns:
        return 0
    did = int(drive_id)
    mask = live_logs["drive_id"].map(_as_int) == did
    sub = live_logs.loc[mask]
    if sub.empty:
        return 0
    if "play_n" in sub.columns:
        nums = [n for n in sub["play_n"].map(_as_int) if n is not None]
        if nums:
            return max(nums)
    # Legacy rows without play_n: treat order within drive as 1..n
    return int(len(sub))


def find_snap_index(live_logs, drive_id: int, play_n: int) -> int | None:
    """Return 0-based row index for drive_id + play_n, or None."""
    if live_logs is None or getattr(live_logs, "empty", True):
        return None
    if "drive_id" not in live_logs.columns:
        return None
    did, pn = int(drive_id), int(play_n)
    df = live_logs.reset_index(drop=True)
    for i, row in df.iterrows():
        if _as_int(row.get("drive_id")) != did:
            continue
        row_pn = _as_int(row.get("play_n")) if "play_n" in df.columns else None
        if row_pn is None:
            # Legacy: nth row in this drive (1-based)
            drive_rows = [
                j
                for j in range(len(df))
                if _as_int(df.loc[j].get("drive_id")) == did
            ]
            try:
                pos = drive_rows.index(int(i)) + 1
            except ValueError:
                continue
            if pos == pn:
                return int(i)
        elif row_pn == pn:
            return int(i)
    return None


def snap_label(drive_id: int | None, play_n: int | None) -> str:
    if drive_id is None:
        return "No drive"
    return f"Drive #{int(drive_id)} · Play #{int(play_n or 1)}"


def merge_snap_values(existing: dict, incoming: dict) -> dict:
    """
    Merge tagger/Main fields onto one snap.
    Non-empty incoming wins; empty incoming keeps existing (protects parallel tags).
    """
    out = dict(existing or {})
    for key, val in (incoming or {}).items():
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            # Don't wipe a parallel tagger's field with blank
            if key in out and str(out.get(key) or "").strip():
                continue
            out[key] = val
            continue
        out[key] = val
    return out


def upsert_live_snap(
    *,
    drive_id: int,
    play_n: int,
    updates: dict[str, Any],
    opponent: str,
    half: int = 1,
    append_fn=None,
    update_at_fn=None,
    load_fn=None,
) -> tuple[bool, int | None, str]:
    """
    Create or merge a live_log row keyed by drive_id + play_n.

    append_fn / update_at_fn / load_fn injected from step4 to avoid circular imports.
    Returns (ok, row_index, message).
    """
    if load_fn is None or append_fn is None or update_at_fn is None:
        return False, None, "upsert not wired"

    logs = load_fn()
    idx = find_snap_index(logs, drive_id, play_n)
    base = {
        "opponent": opponent,
        "half": int(half),
        "drive_id": int(drive_id),
        "play_n": int(play_n),
        "unit": "Offense",
        "film_pending": "Yes",
    }
    if idx is not None and logs is not None and not logs.empty:
        row = logs.reset_index(drop=True).loc[idx].to_dict()
        merged = merge_snap_values(row, {**base, **updates})
        # Recompute film_pending from film fields if present
        front = str(merged.get("def_front") or "").strip()
        cov = str(merged.get("coverage") or "").strip()
        # Front + Coverage is enough for the 1-tagger pack (blitz optional)
        if front and cov:
            merged["film_pending"] = "No"
        elif updates.get("film_pending") is not None:
            merged["film_pending"] = updates["film_pending"]
        ok = update_at_fn(int(idx), merged)
        return ok, int(idx), ("updated" if ok else "update failed")

    stub = merge_snap_values(base, updates)
    if "timestamp" not in stub or not stub.get("timestamp"):
        from datetime import datetime

        stub["timestamp"] = datetime.now().isoformat(timespec="seconds")
    append_fn(stub)
    # Re-find index
    logs2 = load_fn()
    idx2 = find_snap_index(logs2, drive_id, play_n)
    return True, idx2, "created"

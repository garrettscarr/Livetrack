"""
Multi-device booth helpers: station roles + bookmarkable query params.

Roles
-----
- full     — coach / main device: entire Live Track (log, lineup, film, drives)
- call     — snap logger only (phrase / Fast Log)
- defense  — Fill Film only (front / coverage / blitz)

Bookmark iPads with ?station=call or ?station=defense so they open locked
to their job and cannot flip into Full from the UI.
"""

from __future__ import annotations

from typing import Literal

BoothStation = Literal["full", "call", "defense"]

STATION_LABELS: dict[str, str] = {
    "full": "Full — everything",
    "call": "Call — log snaps",
    "defense": "Defense — Fill Film",
}

STATION_HELP = (
    "You (Full): whole booth. "
    "Extra taggers: open ?station=call or ?station=defense — they only see their job."
)


def normalize_station(raw: str | None) -> BoothStation:
    s = str(raw or "").strip().lower()
    if s in {"call", "log", "offense", "phrase"}:
        return "call"
    if s in {"defense", "film", "def", "coverage"}:
        return "defense"
    return "full"


def is_tagger_station(station: str | None) -> bool:
    """Call / Defense are locked tagger views (not Full)."""
    return normalize_station(station) in {"call", "defense"}


def station_from_query(params) -> BoothStation | None:
    """Read ?station= from Streamlit query_params (Mapping-like)."""
    if params is None:
        return None
    try:
        raw = params.get("station")
    except Exception:
        raw = None
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if not raw:
        return None
    return normalize_station(str(raw))


def resolve_booth_station(session_state, query_params) -> BoothStation:
    """
    Prefer bookmark ?station= (locks tagger devices).
    Full can still change role in-session via the station radio.
    """
    qp = station_from_query(query_params)
    if qp and is_tagger_station(qp):
        # Locked from URL — taggers stay on their job
        session_state["booth_station"] = qp
        session_state["booth_station_locked"] = True
        return qp

    if "booth_station" not in session_state:
        session_state["booth_station"] = qp or "full"
    session_state["booth_station_locked"] = False
    return normalize_station(session_state.get("booth_station"))

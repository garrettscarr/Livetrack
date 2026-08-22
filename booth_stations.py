"""
Multi-device booth helpers: station roles + bookmarkable query params.

Call laptop logs snaps; Defense iPad(s) live on Fill Film against the same
hosted live_log.csv. Stations are per-browser; the shared source of truth
is still the server data/ folder (volume on hosted deploys).
"""

from __future__ import annotations

from typing import Literal

BoothStation = Literal["full", "call", "defense"]

STATION_LABELS: dict[str, str] = {
    "full": "Full booth",
    "call": "Call — log snaps",
    "defense": "Defense — Fill Film",
}

STATION_HELP = (
    "Same website link on every device. "
    "Call logs formation/play/result; Defense tags front/coverage/blitz on pending snaps. "
    "Bookmark with ?station=call or ?station=defense so the iPad opens straight to its job."
)


def normalize_station(raw: str | None) -> BoothStation:
    s = str(raw or "").strip().lower()
    if s in {"call", "log", "offense", "phrase"}:
        return "call"
    if s in {"defense", "film", "def", "coverage"}:
        return "defense"
    return "full"


def station_from_query(params) -> BoothStation | None:
    """Read ?station= from Streamlit query_params (Mapping-like)."""
    if params is None:
        return None
    try:
        raw = params.get("station")
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if not raw:
        return None
    return normalize_station(str(raw))

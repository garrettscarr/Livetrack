"""
Multi-device booth helpers: master (Full) vs taggers with chosen focuses.

Master
------
Open the plain app URL (no ?station=) → Full booth (everything).

Taggers
-------
Open ?station=tag then pick what they tag, or bookmark focuses:

  ?station=tag&focus=front
  ?station=tag&focus=coverage
  ?station=tag&focus=blitz
  ?station=tag&focus=snaps
  ?station=tag&focus=front,coverage

Legacy bookmarks still work:
  ?station=call     → snaps
  ?station=defense  → front + coverage + blitz
"""

from __future__ import annotations

from typing import Literal

BoothStation = Literal["full", "call", "defense", "tag"]

STATION_LABELS: dict[str, str] = {
    "full": "Full — everything",
    "call": "Call — log snaps",
    "defense": "Defense — all film",
    "tag": "Tagger — choose focuses",
}

# Keys stored in session / URL
FOCUS_SNAPS = "snaps"
FOCUS_FRONT = "front"
FOCUS_COVERAGE = "coverage"
FOCUS_BLITZ = "blitz"

ALL_FOCUSES: tuple[str, ...] = (
    FOCUS_SNAPS,
    FOCUS_FRONT,
    FOCUS_COVERAGE,
    FOCUS_BLITZ,
)

FOCUS_LABELS: dict[str, str] = {
    FOCUS_SNAPS: "Snap log (formation / play / result)",
    FOCUS_FRONT: "Front",
    FOCUS_COVERAGE: "Coverage",
    FOCUS_BLITZ: "Blitz",
}

FILM_FOCUSES: frozenset[str] = frozenset(
    {FOCUS_FRONT, FOCUS_COVERAGE, FOCUS_BLITZ}
)

STATION_HELP = (
    "You (Full): whole booth. "
    "Extras: open ?station=tag and pick Front / Coverage / Blitz / Snap log "
    "(or bookmark ?station=tag&focus=front)."
)


def normalize_station(raw: str | None) -> BoothStation:
    s = str(raw or "").strip().lower()
    if s in {"call", "log", "offense", "phrase"}:
        return "call"
    if s in {"defense", "film", "def"}:
        return "defense"
    if s in {"tag", "tagger", "extra", "helper"}:
        return "tag"
    return "full"


def is_tagger_station(station: str | None) -> bool:
    """Call / Defense / Tag are locked tagger views (not Full)."""
    return normalize_station(station) in {"call", "defense", "tag"}


def normalize_focuses(raw) -> list[str]:
    """Parse focus list from URL, session, or comma/space-separated string."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        parts = [str(x) for x in raw]
    else:
        text = str(raw).strip()
        if not text:
            return []
        parts = [p for p in text.replace(";", ",").replace(" ", ",").split(",") if p]
    out: list[str] = []
    aliases = {
        "snap": FOCUS_SNAPS,
        "snaps": FOCUS_SNAPS,
        "call": FOCUS_SNAPS,
        "log": FOCUS_SNAPS,
        "front": FOCUS_FRONT,
        "def_front": FOCUS_FRONT,
        "coverage": FOCUS_COVERAGE,
        "cover": FOCUS_COVERAGE,
        "cov": FOCUS_COVERAGE,
        "blitz": FOCUS_BLITZ,
    }
    for p in parts:
        key = aliases.get(p.strip().lower())
        if key and key not in out:
            out.append(key)
    return out


def focuses_from_query(params) -> list[str] | None:
    """Read ?focus= from query params. None if not set."""
    if params is None:
        return None
    try:
        raw = params.get("focus")
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        raw = ",".join(str(x) for x in raw if x)
    parsed = normalize_focuses(raw)
    return parsed  # may be empty list if focus= was present but invalid


def default_focuses_for_station(station: BoothStation) -> list[str]:
    if station == "call":
        return [FOCUS_SNAPS]
    if station == "defense":
        return [FOCUS_FRONT, FOCUS_COVERAGE, FOCUS_BLITZ]
    return []


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
        session_state["booth_station"] = qp
        session_state["booth_station_locked"] = True
        return qp

    if "booth_station" not in session_state:
        session_state["booth_station"] = qp or "full"
    session_state["booth_station_locked"] = False
    return normalize_station(session_state.get("booth_station"))


def resolve_tag_focuses(session_state, query_params, station: BoothStation) -> list[str]:
    """
    What this device is tagging.
    Master (full) → all focuses.
    Taggers → URL ?focus=, else session picker, else station defaults.
    """
    if not is_tagger_station(station):
        return list(ALL_FOCUSES)

    qf = focuses_from_query(query_params)
    if qf:
        session_state["tag_focuses"] = qf
        return qf

    preset = default_focuses_for_station(station)
    if preset and station in {"call", "defense"}:
        session_state["tag_focuses"] = preset
        return preset

    stored = normalize_focuses(session_state.get("tag_focuses"))
    return stored


def has_film_focus(focuses: list[str] | None) -> bool:
    return bool(FILM_FOCUSES.intersection(focuses or []))


def has_snaps_focus(focuses: list[str] | None) -> bool:
    return FOCUS_SNAPS in (focuses or [])


def focus_summary(focuses: list[str] | None) -> str:
    if not focuses:
        return "nothing chosen yet"
    if set(focuses) >= set(ALL_FOCUSES):
        return "everything"
    return " · ".join(FOCUS_LABELS.get(f, f) for f in focuses if f in FOCUS_LABELS)

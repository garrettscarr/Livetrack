"""
Booth roles: Main (full app) vs Tagger (pick focuses → simplified UI).

On load the app asks Main or Tagger (unless a bookmark sets ?station=).

Tagger bookmarks:
  ?station=tag&focus=front
  ?station=tag&focus=coverage,blitz
  ?station=call     → snaps
  ?station=defense  → all film
"""

from __future__ import annotations

from typing import Literal

BoothRole = Literal["main", "tagger"]
BoothStation = Literal["full", "call", "defense", "tag"]

FOCUS_SNAPS = "snaps"
FOCUS_FRONT = "front"
FOCUS_COVERAGE = "coverage"
FOCUS_BLITZ = "blitz"
FOCUS_MOTION = "motion"
FOCUS_BALL = "ball"

ALL_FOCUSES: tuple[str, ...] = (
    FOCUS_SNAPS,
    FOCUS_FRONT,
    FOCUS_COVERAGE,
    FOCUS_BLITZ,
    FOCUS_MOTION,
    FOCUS_BALL,
)

FOCUS_LABELS: dict[str, str] = {
    FOCUS_SNAPS: "Snap log",
    FOCUS_FRONT: "Front",
    FOCUS_COVERAGE: "Coverage",
    FOCUS_BLITZ: "Blitz",
    FOCUS_MOTION: "Motion",
    FOCUS_BALL: "Ball carrier",
}

FOCUS_HELP: dict[str, str] = {
    FOCUS_SNAPS: "Down, distance, formation, call, result, yards (Main)",
    FOCUS_FRONT: "Pre-snap — Even / Odd / Bear / 3-3 Stack",
    FOCUS_COVERAGE: "Pre-snap — Cover 2 / 3 / 4 / …",
    FOCUS_BLITZ: "Post-snap — No / Inside / Outside / Cross",
    FOCUS_MOTION: "Post-snap — motion / shift",
    FOCUS_BALL: "Pass → QB + WR · Run → ball carrier",
}

# Timing buckets so packs balance load across the snap
PRE_SNAP_FOCUSES: frozenset[str] = frozenset({FOCUS_FRONT, FOCUS_COVERAGE})
POST_SNAP_FOCUSES: frozenset[str] = frozenset({FOCUS_BLITZ, FOCUS_MOTION})

FILM_FOCUSES: frozenset[str] = frozenset(
    {FOCUS_FRONT, FOCUS_COVERAGE, FOCUS_BLITZ, FOCUS_MOTION}
)

# Normal booth: 2 taggers, each one pre-snap + one post-snap job (Main logs the call)
TAGGER_PACKS: tuple[dict, ...] = (
    {
        "id": "front_blitz",
        "label": "Tagger 1 · Front + Blitz",
        "subtitle": "Pre-snap front · post-snap blitz (No / Inside / Outside / Cross)",
        "focuses": (FOCUS_FRONT, FOCUS_BLITZ),
        "slot": 1,
    },
    {
        "id": "coverage_ball",
        "label": "Tagger 2 · Coverage + Ball",
        "subtitle": "Pre-snap coverage · post-snap ball carrier",
        "focuses": (FOCUS_COVERAGE, FOCUS_BALL),
        "slot": 2,
    },
)

# Backup when only one tagger shows up
TAGGER_PACK_SOLO: dict = {
    "id": "film_ball",
    "label": "Only 1 tagger · Film + Ball",
    "subtitle": "Front · Coverage · Blitz · ball carrier on one phone",
    "focuses": (FOCUS_FRONT, FOCUS_COVERAGE, FOCUS_BLITZ, FOCUS_BALL),
    "slot": 0,
}

# Optional extra helper phone — motion only
TAGGER_PACK_THIRD: dict = {
    "id": "motion_only",
    "label": "Motion (extra phone)",
    "subtitle": "Post-snap motion only — if a third helper is available",
    "focuses": (FOCUS_MOTION,),
    "slot": 3,
}

TAGGER_JOBS: tuple[str, ...] = (
    FOCUS_FRONT,
    FOCUS_COVERAGE,
    FOCUS_BLITZ,
    FOCUS_BALL,
    FOCUS_MOTION,
)

TAGGER_SPLIT_HELP = (
    "2 taggers: Tagger 1 tags Front + Blitz, Tagger 2 tags Coverage + ball carrier "
    "(Pass → QB + WR · Run → carrier). If only one shows, use the 1-tagger pack. "
    "Main (headset) logs down, distance, formation, call, result, and yards."
)

STATION_LABELS: dict[str, str] = {
    "full": "Main",
    "call": "Snap log",
    "defense": "All film",
    "tag": "Tagger",
}


def normalize_station(raw: str | None) -> BoothStation:
    s = str(raw or "").strip().lower()
    if s in {"call", "log", "offense", "phrase"}:
        return "call"
    if s in {"defense", "film", "def"}:
        return "defense"
    if s in {"tag", "tagger", "extra", "helper"}:
        return "tag"
    if s in {"main", "full", "coach", "master"}:
        return "full"
    return "full"


def is_tagger_station(station: str | None) -> bool:
    return normalize_station(station) in {"call", "defense", "tag"}


def normalize_focuses(raw) -> list[str]:
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
        "motion": FOCUS_MOTION,
        "ball": FOCUS_BALL,
        "carrier": FOCUS_BALL,
        "ball_carrier": FOCUS_BALL,
        # Pack shortcuts
        "front_coverage": "__pack_front_coverage__",
        "film_ball": "__pack_film_ball__",
        "front_blitz": "__pack_front_blitz__",
        "coverage_motion": "__pack_coverage_motion__",
        "coverage_blitz": "__pack_coverage_blitz__",
        "coverage_ball": "__pack_coverage_ball__",
        "blitz_motion": "__pack_blitz_motion__",
        "solo": "__pack_film_ball__",
        "pack1": "__pack_front_blitz__",
        "pack2": "__pack_coverage_ball__",
        "pack3": "__pack_film_ball__",
    }
    pack_map = {
        "__pack_front_coverage__": [FOCUS_FRONT, FOCUS_COVERAGE],
        "__pack_film_ball__": [FOCUS_FRONT, FOCUS_COVERAGE, FOCUS_BLITZ, FOCUS_BALL],
        "__pack_front_blitz__": [FOCUS_FRONT, FOCUS_BLITZ],
        "__pack_coverage_ball__": [FOCUS_COVERAGE, FOCUS_BALL],
        "__pack_coverage_motion__": [FOCUS_COVERAGE, FOCUS_MOTION],
        "__pack_coverage_blitz__": [FOCUS_COVERAGE, FOCUS_BLITZ],
        "__pack_blitz_motion__": [FOCUS_BLITZ, FOCUS_MOTION],
    }
    for p in parts:
        key = aliases.get(p.strip().lower(), p.strip().lower())
        if key in pack_map:
            for f in pack_map[key]:
                if f not in out:
                    out.append(f)
            continue
        if key in {
            FOCUS_SNAPS,
            FOCUS_FRONT,
            FOCUS_COVERAGE,
            FOCUS_BLITZ,
            FOCUS_MOTION,
            FOCUS_BALL,
        } and key not in out:
            out.append(key)
    return out


def focuses_from_query(params) -> list[str] | None:
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
    return normalize_focuses(raw)


def default_focuses_for_station(station: BoothStation) -> list[str]:
    if station == "call":
        return [FOCUS_SNAPS]
    if station == "defense":
        return [FOCUS_FRONT, FOCUS_COVERAGE, FOCUS_BLITZ, FOCUS_BALL]
    # station=tag with no focus → tagger picks a job on their phone
    return []


def station_from_query(params) -> BoothStation | None:
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


def apply_bookmark_role(session_state, query_params) -> bool:
    """
    If URL has ?station=tagger-style, lock role without showing Main/Tagger gate.
    Returns True if a bookmark applied.
    """
    qp = station_from_query(query_params)
    if not qp:
        return False
    if qp == "full" or str(query_params.get("station") or "").lower() in {
        "main",
        "full",
        "coach",
        "master",
    }:
        session_state["booth_role"] = "main"
        session_state["booth_station"] = "full"
        session_state["booth_station_locked"] = False
        session_state["tag_focuses"] = list(ALL_FOCUSES)
        return True
    if is_tagger_station(qp):
        session_state["booth_role"] = "tagger"
        session_state["booth_station"] = qp
        session_state["booth_station_locked"] = True
        qf = focuses_from_query(query_params)
        if qf:
            session_state["tag_focuses"] = qf
        else:
            preset = default_focuses_for_station(qp)
            if preset:
                session_state["tag_focuses"] = preset
        return True
    return False


def resolve_booth_station(session_state, query_params) -> BoothStation:
    role = str(session_state.get("booth_role") or "").strip().lower()
    if role == "main":
        session_state["booth_station"] = "full"
        session_state["booth_station_locked"] = False
        return "full"
    if role == "tagger":
        session_state["booth_station_locked"] = True
        stored = normalize_station(session_state.get("booth_station") or "tag")
        if stored == "full":
            stored = "tag"
        session_state["booth_station"] = stored
        return stored

    # Legacy / bookmark path
    apply_bookmark_role(session_state, query_params)
    if session_state.get("booth_role") == "main":
        return "full"
    if session_state.get("booth_role") == "tagger":
        return normalize_station(session_state.get("booth_station") or "tag")

    if "booth_station" not in session_state:
        session_state["booth_station"] = "full"
    session_state["booth_station_locked"] = False
    return normalize_station(session_state.get("booth_station"))


def resolve_tag_focuses(session_state, query_params, station: BoothStation) -> list[str]:
    if str(session_state.get("booth_role") or "").lower() == "main":
        return list(ALL_FOCUSES)
    if not is_tagger_station(station) and str(session_state.get("booth_role") or "") != "tagger":
        return list(ALL_FOCUSES)

    qf = focuses_from_query(query_params)
    if qf:
        session_state["tag_focuses"] = qf
        return qf

    preset = default_focuses_for_station(station)
    if preset and station in {"call", "defense"}:
        if not session_state.get("tag_focuses"):
            session_state["tag_focuses"] = preset
            return preset

    return normalize_focuses(session_state.get("tag_focuses"))


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


def role_chosen(session_state) -> bool:
    return str(session_state.get("booth_role") or "").lower() in {"main", "tagger"}


def normalize_base_url(url: str | None) -> str:
    base = str(url or "").strip().rstrip("/")
    if not base:
        return ""
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    return base.rstrip("/")


def tagger_invite_url(base_url: str, focuses: list[str] | None = None) -> str:
    """Build a bookmark that opens as Tagger (optional pre-selected focuses)."""
    base = normalize_base_url(base_url)
    if not base:
        return ""
    foc = normalize_focuses(focuses)
    if foc:
        return f"{base}/?station=tag&focus={','.join(foc)}"
    return f"{base}/?station=tag"


def main_invite_url(base_url: str) -> str:
    base = normalize_base_url(base_url)
    if not base:
        return ""
    return f"{base}/?station=main"


# Back-compat alias (older Home pages / partial deploys)
def build_invite_url(base_url: str, focuses: list[str] | None = None) -> str:
    return tagger_invite_url(base_url, focuses)

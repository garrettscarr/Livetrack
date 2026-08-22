"""
Team / product configuration (multi-staff foundation).

Edit data/team_config.json to change aliases, booth PIN, and team identity
without forking code.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_DIR / "data" / "team_config.json"

_DEFAULTS = {
    "team_name": "Home",
    "booth_pin": "0851",
    "play_word_aliases": {"axel": "Axle", "axle": "Axle", "bare": "Bear"},
    "phrase_token_aliases": {
        "tricks": "trix",
        "trick": "trix",
        "wright": "right",
        "write": "right",
        "axel": "axle",
        "bare": "bear",
    },
    "week1_opponent": "Farmersville",
    "season": {
        "id": "25-26",
        "label": "2025-26",
        "current_aliases": ["current", "25-26", ""],
        "note": (
            "Roster, Game Review, and Scout default to this season. "
            "Prior years still feed EPA / tagged play calls."
        ),
    },
    "product_surface": {"halftime_path": "live_track"},
}


@lru_cache(maxsize=1)
def load_team_config() -> dict:
    if not CONFIG_FILE.exists():
        return dict(_DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULTS)
    out = dict(_DEFAULTS)
    out.update(data or {})
    # nested merge for alias maps + season block
    for key in ("play_word_aliases", "phrase_token_aliases"):
        merged = dict(_DEFAULTS.get(key) or {})
        merged.update((data or {}).get(key) or {})
        out[key] = merged
    season_merged = dict(_DEFAULTS.get("season") or {})
    season_merged.update((data or {}).get("season") or {})
    out["season"] = season_merged
    return out


def reload_team_config() -> dict:
    load_team_config.cache_clear()
    return load_team_config()


def booth_pin() -> str:
    return str(load_team_config().get("booth_pin") or "").strip()


def play_word_aliases() -> dict[str, str]:
    raw = load_team_config().get("play_word_aliases") or {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def phrase_token_aliases() -> dict[str, str]:
    raw = load_team_config().get("phrase_token_aliases") or {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def week1_opponent() -> str:
    return str(load_team_config().get("week1_opponent") or "Farmersville").strip()


def season_block() -> dict:
    return dict(load_team_config().get("season") or _DEFAULTS["season"])


def current_season_id() -> str:
    return str(season_block().get("id") or "25-26").strip() or "25-26"


def current_season_label() -> str:
    return str(season_block().get("label") or current_season_id()).strip()


def current_season_aliases() -> set[str]:
    """Values that mean 'this season' in DB / scout / roster files."""
    raw = season_block().get("current_aliases") or ["current", "25-26", ""]
    aliases = {str(a).strip().lower() for a in raw}
    aliases.add(current_season_id().lower())
    aliases.add("current")
    aliases.add("")
    return aliases


def is_current_season_value(value) -> bool:
    s = "" if value is None else str(value).strip().lower()
    if s in {"nan", "none"}:
        s = ""
    return s in current_season_aliases()


def set_current_season(season_id: str, label: str | None = None) -> dict:
    """
    Persist a new active season id/label into team_config.json.
    Prior season id is stored as prior_id and removed from current_aliases.
    """
    sid = str(season_id or "").strip()
    if not sid:
        raise ValueError("season_id is required")
    lab = str(label or sid).strip() or sid

    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}

    prev = dict(data.get("season") or {})
    prev_id = str(prev.get("id") or "").strip()
    data["season"] = {
        **prev,
        "id": sid,
        "label": lab,
        "current_aliases": ["current", sid.lower(), ""],
        "prior_id": prev_id if prev_id and prev_id.lower() != sid.lower() else prev.get("prior_id") or "",
    }

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return reload_team_config()
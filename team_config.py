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
    "play_word_aliases": {"axel": "Axle", "axle": "Axle"},
    "phrase_token_aliases": {
        "tricks": "trix",
        "trick": "trix",
        "trips": "trix",
        "wright": "right",
        "write": "right",
        "axel": "axle",
    },
    "week1_opponent": "Farmersville",
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
    # nested merge for alias maps
    for key in ("play_word_aliases", "phrase_token_aliases"):
        merged = dict(_DEFAULTS.get(key) or {})
        merged.update((data or {}).get(key) or {})
        out[key] = merged
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

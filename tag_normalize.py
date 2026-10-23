"""Canonical tag spelling for play calls (shared by ingest + Live Track)."""

from __future__ import annotations

import re

from team_config import play_word_aliases

UNKNOWN_TOKENS = {
    "",
    "unknown",
    "nan",
    "none",
    "?",
    "—",
    "-",
    "n/a",
    "na",
    "(blank)",
    "(none)",
    "null",
}
_UNKNOWN_TOKENS = UNKNOWN_TOKENS  # back-compat


# Booth blitz tags. Taggers pick a lane; Main / Fill Film may also log bare "Yes".
BLITZ_LANES: tuple[str, ...] = ("Inside", "Outside", "Cross")
BLITZ_TAGGER_CHOICES: tuple[str, ...] = ("No",) + BLITZ_LANES
BLITZ_FORM_CHOICES: tuple[str, ...] = ("No", "Yes") + BLITZ_LANES

_BLITZ_BLANK = UNKNOWN_TOKENS
_BLITZ_NO = {"no", "n", "0", "false", "no blitz", "none"}
_BLITZ_YES = {"yes", "y", "1", "true", "blitz"}
_BLITZ_LANE_WORDS = {
    "inside": "Inside",
    "in": "Inside",
    "inside blitz": "Inside",
    "outside": "Outside",
    "out": "Outside",
    "edge": "Outside",
    "outside blitz": "Outside",
    "cross": "Cross",
    "cross blitz": "Cross",
}


def normalize_blitz(value) -> str:
    """
    Canonical blitz tag: "" (untagged), "No", "Yes", "Inside", "Outside", "Cross",
    or a Hudl package name kept as-is (e.g. "BANDIT STAB").
    """
    s = " ".join(str(value if value is not None else "").split())
    low = s.lower()
    if not s or low in _BLITZ_BLANK:
        return ""
    if low in _BLITZ_NO:
        return "No"
    if low in _BLITZ_LANE_WORDS:
        return _BLITZ_LANE_WORDS[low]
    if low in _BLITZ_YES:
        return "Yes"
    return s


def blitz_tagged(value) -> bool:
    """True when someone recorded a blitz answer (including No)."""
    return normalize_blitz(value) != ""


def blitz_is_pressure(value) -> bool:
    """True when the defense brought pressure (Yes, a lane, or a named package)."""
    return normalize_blitz(value) not in {"", "No"}


def blitz_lane(value) -> str:
    """
    'inside' / 'outside' / 'cross', or '' when no pressure or lane unknown (bare Yes).

    Hudl packages: CROSS → cross, STAB / SMOKE → outside, any other named send → inside.
    """
    tag = normalize_blitz(value)
    if tag in {"", "No", "Yes"}:
        return ""
    if tag in BLITZ_LANES:
        return tag.lower()
    up = tag.upper()
    if re.search(r"\bCROSS\b", up):
        return "cross"
    if re.search(r"\bSTAB\b|\bSMOKE\b", up):
        return "outside"
    return "inside"


def normalize_play_call(name: str | None) -> str:
    """Apply configured word aliases (e.g. Axel / AXLE / axle → Axle)."""
    s = str(name or "").strip()
    if not s or s.lower() in _UNKNOWN_TOKENS:
        return s
    aliases = play_word_aliases()
    if not aliases:
        return s

    def _repl(m: re.Match) -> str:
        word = m.group(0)
        canon = aliases.get(word.lower())
        return canon if canon else word

    # Match whole words that appear as alias keys
    keys = sorted(aliases.keys(), key=len, reverse=True)
    if not keys:
        return s
    pattern = r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b"
    return re.sub(pattern, _repl, s, flags=re.I)

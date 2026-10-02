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
}
_UNKNOWN_TOKENS = UNKNOWN_TOKENS  # back-compat


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

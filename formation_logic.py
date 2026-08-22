"""
Offense formation book — notes / breakdown / GameCast layout keys.

Compass: East = right, West = left (from the offense).
H-align tags: Dip = 1-WR side · Trig = 2-WR side · Fox = 3-WR side
Fever = Fox shape with attached TE instead of H.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
BOOK_FILE = PROJECT_DIR / "data" / "formation_book.json"

# Family id → short coach note (fallback if JSON missing)
_FAMILY_DEFAULTS: dict[str, dict] = {
    "east": {
        "label": "East",
        "family": "trips",
        "note": "Trips right (East = compass right)",
        "layout": "TripsRight",
        "side": "right",
    },
    "west": {
        "label": "West",
        "family": "trips",
        "note": "Trips left (West = compass left)",
        "layout": "TripsLeft",
        "side": "left",
    },
    "slot_dip": {
        "label": "Slot Dip",
        "family": "slot",
        "note": "Slot · H to the 1-WR side (Dip)",
        "layout": "SlotDip",
        "h_align": "1_wr",
    },
    "slot_trig": {
        "label": "Slot Trig",
        "family": "slot",
        "note": "Slot · H to the 2-WR side (Trig)",
        "layout": "SlotTrig",
        "h_align": "2_wr",
    },
    "dot": {
        "label": "Dot",
        "family": "doubles",
        "note": "Doubles (2×2)",
        "layout": "Doubles",
    },
    "empty": {
        "label": "Empty",
        "family": "empty",
        "note": "Empty",
        "layout": "Empty",
        "personnel": "10/11 empty",
    },
    "trix": {
        "label": "Trix",
        "family": "trix",
        "note": "TE attached to the boundary · trips to the field",
        "layout": "Trix",
    },
    "fox": {
        "label": "Fox",
        "family": "fox",
        "note": "H to the 3-WR side (Fox)",
        "layout": "Fox",
        "h_align": "3_wr",
    },
    "fever": {
        "label": "Fever",
        "family": "fever",
        "note": "Same as Fox, but attached TE (not H) to the 3-WR side",
        "layout": "Fever",
        "h_align": "3_wr_te",
    },
    "pack": {
        "label": "Pack",
        "family": "bunch",
        "note": "Bunch (Pack)",
        "layout": "Pack",
    },
    "cowboy": {
        "label": "Cowboy",
        "family": "empty_bunch",
        "note": "Empty Bunch (Cowboy)",
        "layout": "Cowboy",
        "personnel": "empty bunch",
    },
    "texas": {
        "label": "Texas",
        "family": "12",
        "note": "12 personnel (2 TE/H)",
        "layout": "Texas",
        "personnel": "12",
    },
    "nasty": {
        "label": "Nasty",
        "family": "jumbo",
        "note": "6 OL + TE (Nasty)",
        "layout": "Nasty",
        "personnel": "6 OL + TE",
    },
}

# Longer phrase keys first
_FAMILY_PATTERNS: list[tuple[str, str]] = [
    (r"\bslot\s+dip\b", "slot_dip"),
    (r"\bslot\s+trig\b", "slot_trig"),
    (r"\b34\s+dot\b", "dot"),
    (r"\beast\b", "east"),
    (r"\bwest\b", "west"),
    (r"\bdot\b", "dot"),
    (r"\bempty\b", "empty"),
    (r"\btrix\b", "trix"),
    (r"\bfox\b", "fox"),
    (r"\bfever\b", "fever"),
    (r"\bpack\b", "pack"),
    (r"\bcowboy\b", "cowboy"),
    (r"\btexas\b", "texas"),
    (r"\bnasty\b", "nasty"),
]


def _norm(text: str) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"[,;:]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


@lru_cache(maxsize=1)
def load_formation_book() -> dict:
    """Optional override JSON; falls back to built-in defaults."""
    if not BOOK_FILE.exists():
        return {"families": _FAMILY_DEFAULTS}
    try:
        import json

        raw = json.loads(BOOK_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"families": _FAMILY_DEFAULTS}
        families = raw.get("families") if isinstance(raw.get("families"), dict) else {}
        merged = {**_FAMILY_DEFAULTS, **{str(k).lower(): v for k, v in families.items()}}
        return {"families": merged, "raw": raw}
    except Exception:
        return {"families": _FAMILY_DEFAULTS}


def parse_formation_side(text: str) -> str | None:
    """Return 'right' | 'left' | None from East/West / RT/LT."""
    low = _norm(text)
    if re.search(r"\beast\b|\bright\b|\brt\b", low):
        return "right"
    if re.search(r"\bwest\b|\bleft\b|\blt\b", low):
        return "left"
    m = re.search(r"\b(?:fox|fever|pack|trix)\s+([rl])\b", low)
    if m:
        return "right" if m.group(1) == "r" else "left"
    return None


def detect_formation_family(formation: str) -> str | None:
    low = _norm(formation)
    if not low:
        return None
    for pat, fid in _FAMILY_PATTERNS:
        if re.search(pat, low):
            return fid
    return None


def _side_word(side: str | None) -> str:
    if side == "right":
        return "right (East)"
    if side == "left":
        return "left (West)"
    return ""


def _layout_for(family_id: str, side: str | None, meta: dict) -> str:
    base = str(meta.get("layout") or "Base")
    # Families that flip with compass / RT-LT
    sided = {
        "fox": ("FoxRight", "FoxLeft"),
        "fever": ("FeverRight", "FeverLeft"),
        "pack": ("PackRight", "PackLeft"),
        "slot_dip": ("SlotDipRight", "SlotDipLeft"),
        "slot_trig": ("SlotTrigRight", "SlotTrigLeft"),
        "trix": ("TrixFieldRight", "TrixFieldLeft"),  # trips-to-field default by tag
        "east": ("TripsRight", "TripsRight"),
        "west": ("TripsLeft", "TripsLeft"),
    }
    if family_id in sided:
        right_key, left_key = sided[family_id]
        if family_id == "east":
            return right_key
        if family_id == "west":
            return left_key
        if side == "left":
            return left_key
        if side == "right":
            return right_key
        # Default strength right when unspecified (common booth default)
        return right_key
    return base


def formation_breakdown(
    formation: str = "",
    variant: str = "",
) -> dict:
    """
    Structured notes for a called formation (+ optional variant).

    Keys: family_id, label, family, side, h_align, personnel, note, layout,
          known (bool), parts (list of note fragments)
    """
    book = load_formation_book().get("families") or _FAMILY_DEFAULTS
    raw = " ".join(p for p in (str(formation or "").strip(), str(variant or "").strip()) if p)
    family_id = detect_formation_family(raw) or detect_formation_family(formation)
    side = parse_formation_side(raw)

    if not family_id:
        label = str(formation or "").strip() or "—"
        note = f"{label}" + (f" · {variant}" if variant else "")
        return {
            "family_id": "",
            "label": label,
            "family": "unknown",
            "side": side,
            "h_align": "",
            "personnel": "",
            "note": note.strip(" ·"),
            "layout": "Base",
            "known": False,
            "parts": [note] if note else [],
        }

    meta = dict(book.get(family_id) or _FAMILY_DEFAULTS.get(family_id) or {})
    # East/West imply side even if parse missed
    if family_id == "east":
        side = "right"
    elif family_id == "west":
        side = "left"

    parts: list[str] = []
    label = str(meta.get("label") or family_id)
    base_note = str(meta.get("note") or "").strip()
    # Prefer the coach note; include call label when it adds side (Fox RT, etc.)
    call = str(formation or "").strip()
    if call and call.lower() not in {label.lower(), base_note.lower()}:
        parts.append(call)
    elif not base_note:
        parts.append(label)
    if base_note:
        parts.append(base_note)

    sw = _side_word(side)
    if sw and family_id not in {"east", "west"}:
        blob = " ".join(parts).lower()
        if not re.search(r"\b(right|left|east|west|\brt\b|\blt\b)\b", blob):
            parts.append(f"Strength {sw}")

    if variant and str(variant).strip():
        parts.append(f"Variant {str(variant).strip()}")

    # Dedupe while preserving order
    seen: set[str] = set()
    clean_parts: list[str] = []
    for p in parts:
        p = re.sub(r"\s+", " ", str(p or "").strip())
        if not p or p.lower() in seen:
            continue
        seen.add(p.lower())
        clean_parts.append(p)

    note = " · ".join(clean_parts)
    layout = _layout_for(family_id, side, meta)
    fam = str(meta.get("family") or "")

    return {
        "family_id": family_id,
        "label": label,
        "family": fam,
        "side": side,
        "h_align": str(meta.get("h_align") or ""),
        "personnel": str(meta.get("personnel") or ""),
        "note": note,
        "layout": layout,
        "known": True,
        "parts": clean_parts,
    }


def formation_note(formation: str = "", variant: str = "") -> str:
    return str(formation_breakdown(formation, variant).get("note") or "")


def formation_layout_key(formation: str = "", variant: str = "") -> str:
    return str(formation_breakdown(formation, variant).get("layout") or "Base")


def formation_glossary() -> list[dict]:
    """Rows for a UI glossary / Database help."""
    book = load_formation_book().get("families") or _FAMILY_DEFAULTS
    rows = []
    for fid, meta in book.items():
        rows.append(
            {
                "id": fid,
                "label": meta.get("label") or fid,
                "note": meta.get("note") or "",
                "family": meta.get("family") or "",
                "personnel": meta.get("personnel") or "",
            }
        )
    return sorted(rows, key=lambda r: str(r["label"]).lower())

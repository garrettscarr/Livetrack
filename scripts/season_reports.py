#!/usr/bin/env python3
"""
Shareable offense reports (Markdown + PDF) for the active season.

  python scripts/season_reports.py                    # full season + play-caller split
  python scripts/season_reports.py --new-caller-game 7

Writes to data/season_reports/:
  {season}_Season_Situation_Report.md / .pdf
  {season}_Play_Caller_Change_Report.md / .pdf
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from team_config import current_season_id, current_season_label  # noqa: E402

DB = ROOT / "data" / "football.db"
OUT_DIR = ROOT / "data" / "season_reports"

# Booth typos seen in Hudl exports — merged for reporting only.
FORMATION_FIXES = {
    "SLOT TIRG": "SLOT TRIG",
    "SOXT TRIG": "SLOT TRIG",
    "TRIG": "SLOT TRIG",
    "SDIP": "SLOT DIP",
    "DIP": "SLOT DIP",
}
CALL_WORD_FIXES = {
    "IREALND": "IRELAND",
    "RELAND": "IRELAND",
    "ILLINIOS": "ILLINOIS",
    "IILLINOIS": "ILLINOIS",
    "SUPERMN": "SUPERMAN",
    "BRNOCO": "BRONCO",
    "DEVILS": "DEVIL",
}
ZONES = [
    ("backed_up", "Backed up (own 1–20)"),
    ("own_territory", "Own territory (21–40)"),
    ("midfield", "Midfield (41–opp 40)"),
    ("opp_territory", "Opp territory (39–21)"),
    ("red_zone", "Red zone (opp 20–1)"),
]


# --------------------------------------------------------------------------- data


def _blank(s) -> str:
    t = " ".join(str(s or "").upper().split())
    return "" if t in {"", "NAN", "NONE", "UNKNOWN"} else t


def _norm_form(s) -> str:
    t = _blank(s)
    return FORMATION_FIXES.get(t, t)


def _norm_call(s) -> str:
    t = _blank(s)
    return " ".join(CALL_WORD_FIXES.get(w, w) for w in t.split())


def _band(x) -> str:
    if pd.isna(x):
        return ""
    if x <= 3:
        return "1-3"
    if x <= 6:
        return "4-6"
    if x <= 9:
        return "7-9"
    return "10+"


def load_season(season: str) -> pd.DataFrame:
    with sqlite3.connect(DB) as conn:
        df = pd.read_sql(
            "SELECT * FROM offense_plays_epa WHERE season = ?", conn, params=(season,)
        )
    for c in (
        "down", "distance", "yards_gained", "epa", "is_success", "is_turnover",
        "is_touchdown", "is_penalty", "game_id", "play_num",
    ):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["form"] = df["formation"].map(_norm_form)
    df["call"] = df["play_call"].map(_norm_call)
    df["phase"] = df["play_type"].fillna("").astype(str).str.strip().str.lower()
    df["to"] = df["is_turnover"].fillna(0).astype(int)
    df["band"] = df["distance"].map(_band)
    df["bucket"] = df["distance_bucket"].fillna("").astype(str).str.lower()
    df["back"] = df["backfield"].map(_blank)
    df = df.sort_values(["game_id", "play_num"]).reset_index(drop=True)
    df["next_down"] = df.groupby("game_id")["down"].shift(-1)
    df["next_dist"] = df.groupby("game_id")["distance"].shift(-1)
    return df


def stats(g: pd.DataFrame) -> dict:
    n = int(len(g))
    if n == 0:
        return {"n": 0, "epa": np.nan, "sr": np.nan, "yds": np.nan, "exp": np.nan,
                "neg": np.nan, "td": 0, "to": 0, "run": np.nan, "to_epa": 0.0}
    y = g["yards_gained"]
    rp = g[g["phase"].isin(["run", "pass"])]
    return {
        "n": n,
        "epa": float(g["epa"].mean()),
        # Expected points given away on turnover snaps (negative = lost)
        "to_epa": float(g.loc[g["to"] == 1, "epa"].sum()),
        "sr": float(g["is_success"].mean()),
        "yds": float(y.mean()) if y.notna().any() else np.nan,
        "exp": float((y >= 10).mean()),
        "neg": float((y <= 0).mean()),
        "td": int(g["is_touchdown"].fillna(0).sum()),
        "to": int(g["to"].sum()),
        "run": float((rp["phase"] == "run").mean()) if len(rp) else np.nan,
    }


def first_down_chain(g: pd.DataFrame) -> dict:
    """1st-and-8+ (no turnover): EPA and what 2nd down it leaves."""
    s = g[(g["down"] == 1) & (g["distance"] >= 8) & g["phase"].isin(["run", "pass"]) & (g["to"] == 0)]
    into = s[s["next_down"] == 2]
    return {
        "n": int(len(s)),
        "epa": float(s["epa"].mean()) if len(s) else np.nan,
        "yds": float(s["yards_gained"].mean()) if len(s) else np.nan,
        "short": float((into["next_dist"] <= 6).mean()) if len(into) else np.nan,
        "long": float((into["next_dist"] >= 10).mean()) if len(into) else np.nan,
    }


# --------------------------------------------------------------------------- format


def pct(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{round(100 * float(v))}%"


def epa_s(v) -> str:
    return "—" if v is None or pd.isna(v) else f"{float(v):+.3f}"


def num(v, d: int = 1) -> str:
    return "—" if v is None or pd.isna(v) else f"{float(v):.{d}f}"


def ordinal(d) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(int(d), f"{int(d)}th")


def arrow(old, new, kind: str = "pct") -> str:
    """'52% → 32%' style change cell."""
    f = pct if kind == "pct" else epa_s if kind == "epa" else (lambda v: num(v))
    return f"{f(old)} → {f(new)}"


# --------------------------------------------------------------------------- render

# Signed or decimal numbers only, so "n=11" and snap counts stay uncolored.
_EPA_NUM = re.compile(r"(?<![\w.])[+\-−]?\d+\.\d+|(?<![\w.])[+\-−]\d+(?![\w.])")
_NEUTRAL = (0x6B, 0x72, 0x80)
_POS_TEXT, _NEG_TEXT = (0x05, 0x6B, 0x2E), (0xB9, 0x1C, 0x1C)
_POS_BG, _NEG_BG = (0x86, 0xEF, 0xAC), (0xFC, 0xA5, 0xA5)
_WHITE = (0xFF, 0xFF, 0xFF)


def _mix(a: tuple, b: tuple, t: float) -> str:
    t = max(0.0, min(1.0, t))
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def _epa_scale(label: str) -> float:
    """EPA value that reaches full color: per-play vs per-game / season totals."""
    low = label.lower()
    if "lost" in low or "pts" in low:
        return 10.0
    if "one turnover" in low:
        return 5.0
    return 0.5


def _epa_colored(text: str, scale: float) -> tuple[str, str | None]:
    """Wrap each EPA number in a green/red font tag. Returns (markup, cell bg or None)."""
    values: list[float] = []

    def _sub(m: re.Match) -> str:
        v = float(m.group(0).replace("−", "-"))
        values.append(v)
        if v == 0:
            return f'<font color="{_mix(_NEUTRAL, _NEUTRAL, 0)}">{m.group(0)}</font>'
        t = min(abs(v) / scale, 1.0) ** 0.75
        color = _mix(_NEUTRAL, _POS_TEXT if v > 0 else _NEG_TEXT, 0.35 + 0.65 * t)
        return f'<font color="{color}"><b>{m.group(0)}</b></font>'

    markup = _EPA_NUM.sub(_sub, text)
    bg = None
    if len(values) == 1 and values[0] != 0:
        v = values[0]
        bg = _mix(_WHITE, _POS_BG if v > 0 else _NEG_BG, 0.12 + 0.6 * min(abs(v) / scale, 1.0))
    return markup, bg


def _is_epa_label(label: str) -> bool:
    return bool(re.search(r"epa|turnover cost|points lost|pts lost|cost of one", label, re.I))


class Doc:
    """Ordered blocks rendered to both Markdown and PDF."""

    def __init__(self, title: str, subtitle: str):
        self.title = title
        self.subtitle = subtitle
        self.blocks: list[tuple] = []

    def h(self, text: str):
        self.blocks.append(("h", text))

    def p(self, text: str):
        self.blocks.append(("p", text))

    def bullets(self, items: list[str]):
        self.blocks.append(("ul", items))

    def table(self, headers: list[str], rows: list[list], widths: list[float]):
        self.blocks.append(("t", headers, [[str(c) for c in r] for r in rows], widths))

    def markdown(self) -> str:
        out = [f"# {self.title}", "", self.subtitle, ""]
        for b in self.blocks:
            if b[0] == "h":
                out += [f"## {b[1]}", ""]
            elif b[0] == "p":
                out += [b[1].replace("<b>", "**").replace("</b>", "**"), ""]
            elif b[0] == "ul":
                out += [f"- {i.replace('<b>', '**').replace('</b>', '**')}" for i in b[1]] + [""]
            elif b[0] == "t":
                headers, rows = b[1], b[2]
                out.append("| " + " | ".join(headers) + " |")
                out.append("| " + " | ".join([":---"] + [":---:"] * (len(headers) - 1)) + " |")
                out += ["| " + " | ".join(r) + " |" for r in rows]
                out.append("")
        return "\n".join(out) + "\n"

    def pdf(self, path: Path, footer: str):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas as pdfcanvas
        from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        brand = colors.HexColor("#1B4332")
        muted = colors.HexColor("#64748B")
        bg = colors.HexColor("#F8FAFC")
        border = colors.HexColor("#CBD5E1")
        ss = getSampleStyleSheet()
        st_title = ParagraphStyle("T", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=16,
                                  textColor=brand, leading=20, spaceAfter=2)
        st_sub = ParagraphStyle("S", parent=ss["Normal"], fontSize=8.5, textColor=muted, leading=11, spaceAfter=6)
        st_h = ParagraphStyle("H", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12,
                              textColor=brand, spaceBefore=9, spaceAfter=3)
        st_p = ParagraphStyle("B", parent=ss["Normal"], fontSize=9, leading=12,
                              textColor=colors.HexColor("#1F2937"), spaceAfter=4)
        st_li = ParagraphStyle("L", parent=st_p, leftIndent=12, spaceAfter=2)
        st_cell = ParagraphStyle("C", parent=st_p, fontSize=7.6, leading=9.5, spaceAfter=0)
        st_th = ParagraphStyle("TH", parent=st_cell, textColor=colors.white, fontName="Helvetica-Bold")

        story = [Paragraph(self.title, st_title), Paragraph(self.subtitle.replace("\n", "<br/>"), st_sub)]
        pending_h = None
        for b in self.blocks:
            if b[0] == "h":
                pending_h = Paragraph(b[1], st_h)
                continue
            if b[0] == "p":
                flow = [Paragraph(b[1], st_p)]
            elif b[0] == "ul":
                flow = [Paragraph(f"• {i}", st_li) for i in b[1]]
            else:
                headers, rows, widths = b[1], b[2], b[3]
                epa_cols = {j for j, h in enumerate(headers) if j > 0 and _is_epa_label(h)}
                cell_bgs: list[tuple] = []
                body = []
                for i, r in enumerate(rows):
                    # Row-label tables ("Performance EPA / play" | value | value)
                    row_epa = bool(r) and _is_epa_label(r[0])
                    cells = []
                    for j, c in enumerate(r):
                        if j > 0 and (j in epa_cols or row_epa):
                            label = r[0] if row_epa else headers[j]
                            markup, cbg = _epa_colored(c, _epa_scale(label))
                            cells.append(Paragraph(markup, st_cell))
                            if cbg:
                                cell_bgs.append(("BACKGROUND", (j, i + 1), (j, i + 1), colors.HexColor(cbg)))
                        else:
                            cells.append(Paragraph(c, st_cell))
                    body.append(cells)
                data = [[Paragraph(h, st_th) for h in headers]] + body
                t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), brand),
                    ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("GRID", (0, 0), (-1, -1), 0.3, border),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, bg]),
                ] + cell_bgs))
                flow = [t, Spacer(1, 5)]
            if pending_h is not None:
                story.append(KeepTogether([pending_h] + flow[:1]))
                story.extend(flow[1:])
                pending_h = None
            else:
                story.extend(flow)

        class _Numbered(pdfcanvas.Canvas):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self._pages = []

            def showPage(self):
                self._pages.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                total = len(self._pages)
                for state in self._pages:
                    self.__dict__.update(state)
                    self.saveState()
                    self.setFont("Helvetica", 8)
                    self.setFillColor(muted)
                    self.drawString(0.6 * inch, 0.38 * inch, footer)
                    self.drawRightString(7.9 * inch, 0.38 * inch, f"Page {self._pageNumber} of {total}")
                    self.restoreState()
                    super().showPage()
                super().save()

        SimpleDocTemplate(
            str(path), pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
            topMargin=0.5 * inch, bottomMargin=0.6 * inch, title=self.title,
        ).build(story, canvasmaker=_Numbered)


# --------------------------------------------------------------------------- reports


GAME_HEADERS = ["Game", "Caller", "Snaps", "Perf. EPA", "Call EPA", "TO", "Pts lost to TO",
                "Success", "Yds", "TD", "Run %"]
GAME_WIDTHS = [1.55, 0.5, 0.45, 0.65, 0.65, 0.35, 0.75, 0.6, 0.45, 0.35, 0.5]


def _games_rows(df: pd.DataFrame, new_from: int | None) -> list[list]:
    rows = []
    for (gid, opp, notes), g in df.groupby(["game_id", "opponent", "game_notes"], dropna=False):
        s, s_nt = stats(g), stats(g[g["to"] == 0])
        caller = ""
        if new_from is not None:
            caller = "New" if int(gid) >= new_from else "Old"
        rows.append((int(gid), [
            f"{opp} ({notes})" if notes else str(opp), caller, s["n"], epa_s(s["epa"]),
            epa_s(s_nt["epa"]), s["to"], num(s["to_epa"]) if s["to"] else "0.0",
            pct(s["sr"]), num(s["yds"]), s["td"], pct(s["run"]),
        ]))
    return [r for _, r in sorted(rows)]


def _turnover_cost_rows(g: pd.DataFrame) -> list[list]:
    """Performance vs call-sheet EPA and what turnovers cost."""
    s, s_nt = stats(g), stats(g[g["to"] == 0])
    games = max(int(g["game_id"].nunique()), 1)
    gap = s["epa"] - s_nt["epa"] if s["n"] and s_nt["n"] else np.nan
    return [
        ["Performance EPA / play (turnovers in)", epa_s(s["epa"])],
        ["Call-sheet EPA / play (turnovers out)", epa_s(s_nt["epa"])],
        ["Turnover cost per play", epa_s(gap)],
        ["Turnovers", f"{s['to']} ({num(s['to'] / games)} per game)"],
        ["Expected points lost to turnovers", f"{num(s['to_epa'])} ({num(s['to_epa'] / games)} per game)"],
        ["Average cost of one turnover", num(s["to_epa"] / s["to"]) if s["to"] else "—"],
    ]


def _combo_rows(g: pd.DataFrame, min_n: int, *, best: bool, limit: int) -> list[list]:
    tagged = g[(g["form"] != "") & (g["call"] != "")]
    rows = []
    for (f, c), gg in tagged.groupby(["form", "call"]):
        if len(gg) < min_n:
            continue
        s = stats(gg)
        rows.append((s["epa"], f"{f} · {c}", s))
    rows.sort(key=lambda r: r[0], reverse=best)
    return [[name, s["n"], epa_s(s["epa"]), pct(s["sr"]), num(s["yds"])] for _, name, s in rows[:limit]]


def _form_rows(g: pd.DataFrame, min_n: int, limit: int | None = None) -> list[list]:
    rows = []
    for f, gg in g[g["form"] != ""].groupby("form"):
        if len(gg) < min_n:
            continue
        s = stats(gg)
        rows.append((s["epa"], f, s))
    rows.sort(key=lambda r: r[0], reverse=True)
    if limit:
        rows = rows[:limit]
    return [[f, s["n"], epa_s(s["epa"]), pct(s["sr"]), num(s["yds"]), pct(s["exp"])] for _, f, s in rows]


def build_season_report(df: pd.DataFrame, season_label: str, new_from: int | None) -> Doc:
    games = ", ".join(df.drop_duplicates("game_id")["opponent"].astype(str))
    k, k_nt = stats(df), stats(df[df["to"] == 0])
    stamp = datetime.now().strftime("%B %d, %Y · %I:%M %p").replace(" 0", " ")
    doc = Doc(
        f"{season_label} Season Situation Report",
        f"{k['n']} snaps · {df['game_id'].nunique()} games: {games}\n"
        f"Generated {stamp}. Scrimmages excluded.",
    )

    doc.h("Scoreboard")
    doc.table(
        ["Metric", "All snaps (performance)", "Turnovers removed (call sheet)"],
        [
            ["EPA / play", epa_s(k["epa"]), epa_s(k_nt["epa"])],
            ["Success rate", pct(k["sr"]), pct(k_nt["sr"])],
            ["Yards / play", num(k["yds"]), num(k_nt["yds"])],
            ["Explosive (10+)", pct(k["exp"]), pct(k_nt["exp"])],
            ["Gained nothing", pct(k["neg"]), pct(k_nt["neg"])],
            ["Touchdowns / turnovers", f"{k['td']} / {k['to']}", f"{k_nt['td']} / —"],
            ["Run rate", pct(k["run"]), pct(k_nt["run"])],
        ],
        [2.4, 2.3, 2.6],
    )

    doc.h("What turnovers are costing")
    doc.p(
        "<b>Performance EPA</b> counts every snap, turnovers included — it is how the offense actually "
        "played. <b>Call-sheet EPA</b> drops turnover snaps to grade the calls. The gap between the two "
        "is what ball security is costing. Expected points lost is the EPA on the turnover snaps: "
        "the points we were expected to get from that drive plus the field position handed over."
    )
    doc.table(["", "Season"], _turnover_cost_rows(df), [4.0, 3.3])

    doc.h("Games")
    doc.p(
        "Perf. EPA includes turnovers. Call EPA removes them. Pts lost to TO is the expected points "
        "given away on that game's turnovers."
    )
    headers, widths = list(GAME_HEADERS), list(GAME_WIDTHS)
    rows = _games_rows(df, new_from)
    if new_from is None:
        headers.pop(1)
        widths[0] += widths.pop(1)
        rows = [r[:1] + r[2:] for r in rows]
    doc.table(headers, rows, widths)

    doc.h("Down and distance")
    rows = []
    for d, g in df.groupby("down"):
        if pd.isna(d):
            continue
        s = stats(g)
        rows.append([ordinal(d), s["n"], epa_s(s["epa"]), pct(s["sr"]), num(s["yds"]), pct(s["run"])])
    doc.table(["Down", "Snaps", "EPA", "Success", "Yds", "Run %"], rows, [1.3, 1.1, 1.2, 1.2, 1.1, 1.3])
    rows = []
    for d in (1, 2, 3, 4):
        for b, lbl in (("short", "1–3"), ("medium", "4–6"), ("long", "7+")):
            g = df[(df["down"] == d) & (df["bucket"] == b)]
            if g.empty:
                continue
            s = stats(g)
            rows.append([f"{ordinal(d)} & {lbl}", s["n"], epa_s(s["epa"]), pct(s["sr"]),
                         num(s["yds"]), pct(s["neg"]), pct(s["run"])])
    doc.table(["Situation", "Snaps", "EPA", "Success", "Yds", "Nothing", "Run %"], rows,
              [1.4, 0.9, 1.0, 1.0, 0.9, 1.0, 1.1])

    doc.h("Field zone")
    rows = []
    for z, lbl in ZONES:
        g = df[df["field_zone"] == z]
        if g.empty:
            continue
        s = stats(g)
        rows.append([lbl, s["n"], epa_s(s["epa"]), pct(s["sr"]), num(s["yds"]), pct(s["run"])])
    doc.table(["Zone", "Snaps", "EPA", "Success", "Yds", "Run %"], rows, [2.3, 0.9, 1.0, 1.0, 0.9, 1.2])

    for phase, label, noun in (("run", "Run game", "carries"), ("pass", "Pass game", "attempts")):
        g = df[df["phase"] == phase]
        s = stats(g)
        doc.h(label)
        doc.p(
            f"<b>{s['n']} {noun}</b> · EPA {epa_s(s['epa'])} · {pct(s['sr'])} success · "
            f"{num(s['yds'])} yds · {s['td']} TD · {pct(s['exp'])} explosive · {pct(s['neg'])} gained nothing"
        )
        rows = [r[:5] for r in _form_rows(g, 4, limit=12)]
        if rows:
            doc.table(["Formation", noun.title(), "EPA", "Success", "Yds"], rows, [2.6, 1.0, 1.2, 1.2, 1.3])

    doc.h("Run / pass by down")
    rows = []
    for d in (1, 2, 3, 4):
        for ph in ("run", "pass"):
            g = df[(df["down"] == d) & (df["phase"] == ph)]
            if len(g) < 3:
                continue
            s = stats(g)
            rows.append([f"{ordinal(d)} · {ph.title()}", s["n"], epa_s(s["epa"]), pct(s["sr"]), num(s["yds"])])
    doc.table(["Situation", "Snaps", "EPA", "Success", "Yds"], rows, [2.0, 1.2, 1.4, 1.4, 1.3])

    doc.h("Formations (5+ snaps)")
    doc.table(["Formation", "Snaps", "EPA", "Success", "Yds", "Explosive"], _form_rows(df, 5),
              [2.4, 0.9, 1.0, 1.0, 0.9, 1.1])

    doc.h("Formation · play — feature (4+ snaps)")
    doc.table(["Combo", "Snaps", "EPA", "Success", "Yds"], _combo_rows(df, 4, best=True, limit=12),
              [3.3, 0.9, 1.0, 1.0, 1.1])
    doc.h("Formation · play — shelve (4+ snaps)")
    doc.table(["Combo", "Snaps", "EPA", "Success", "Yds"], _combo_rows(df, 4, best=False, limit=10),
              [3.3, 0.9, 1.0, 1.0, 1.1])
    return doc


def build_change_report(df: pd.DataFrame, season_label: str, new_from: int) -> Doc:
    old, new = df[df["game_id"] < new_from], df[df["game_id"] >= new_from]
    old_nt, new_nt = old[old["to"] == 0], new[new["to"] == 0]
    old_games = ", ".join(old.drop_duplicates("game_id")["opponent"].astype(str))
    new_games = ", ".join(new.drop_duplicates("game_id")["opponent"].astype(str))
    so, sn = stats(old), stats(new)
    so_nt, sn_nt = stats(old_nt), stats(new_nt)
    stamp = datetime.now().strftime("%B %d, %Y · %I:%M %p").replace(" 0", " ")
    doc = Doc(
        f"{season_label} Play Caller Change Report",
        f"Before: {old_games} ({so['n']} snaps, {old['game_id'].nunique()} games)\n"
        f"After: {new_games} ({sn['n']} snaps, {new['game_id'].nunique()} games)\n"
        f"Generated {stamp}.",
    )
    doc.p(
        "Efficiency tables remove turnover snaps, so the call sheet is graded on what the call produced. "
        "Tendency tables (run rate, formation and call usage) use every snap. "
        f"The new-caller sample is {new['game_id'].nunique()} games — read rows with fewer than "
        "5 snaps as a lean, not a rule."
    )

    # ---- headline facts (largest moves)
    o_ch, n_ch = first_down_chain(old), first_down_chain(new)
    g_old, g_new = max(old["game_id"].nunique(), 1), max(new["game_id"].nunique(), 1)
    facts = [
        f"Call-sheet EPA (turnovers removed): <b>{arrow(so_nt['epa'], sn_nt['epa'], 'epa')}</b>. "
        f"Performance EPA (turnovers in): <b>{arrow(so['epa'], sn['epa'], 'epa')}</b>.",
        f"Turnovers per game: <b>{num(so['to'] / g_old)} → {num(sn['to'] / g_new)}</b>. "
        f"Expected points lost to turnovers per game: <b>{num(so['to_epa'] / g_old)} → "
        f"{num(sn['to_epa'] / g_new)}</b>.",
        f"Run rate: <b>{arrow(so['run'], sn['run'])}</b>. Yards per play: {arrow(so['yds'], sn['yds'], 'num')}.",
        f"1st-and-10 EPA: <b>{arrow(o_ch['epa'], n_ch['epa'], 'epa')}</b>, but 1st downs that leave "
        f"2nd-and-6 or less: <b>{arrow(o_ch['short'], n_ch['short'])}</b>.",
    ]
    for d in (2, 3):
        o_rp = old[(old["down"] == d) & old["phase"].isin(["run", "pass"])]
        n_rp = new[(new["down"] == d) & new["phase"].isin(["run", "pass"])]
        o_r = (o_rp["phase"] == "run").mean() if len(o_rp) else np.nan
        n_r = (n_rp["phase"] == "run").mean() if len(n_rp) else np.nan
        facts.append(f"{ordinal(d)}-down run rate: <b>{arrow(o_r, n_r)}</b>.")
    doc.h("What changed")
    doc.bullets(facts)

    doc.h("Scoreboard")
    doc.table(
        ["Metric", "Before", "After", "Before (no TO)", "After (no TO)"],
        [
            ["Snaps", so["n"], sn["n"], so_nt["n"], sn_nt["n"]],
            ["EPA / play", epa_s(so["epa"]), epa_s(sn["epa"]), epa_s(so_nt["epa"]), epa_s(sn_nt["epa"])],
            ["Success rate", pct(so["sr"]), pct(sn["sr"]), pct(so_nt["sr"]), pct(sn_nt["sr"])],
            ["Yards / play", num(so["yds"]), num(sn["yds"]), num(so_nt["yds"]), num(sn_nt["yds"])],
            ["Explosive (10+)", pct(so["exp"]), pct(sn["exp"]), pct(so_nt["exp"]), pct(sn_nt["exp"])],
            ["Gained nothing", pct(so["neg"]), pct(sn["neg"]), pct(so_nt["neg"]), pct(sn_nt["neg"])],
            ["TD per game", num(so["td"] / g_old), num(sn["td"] / g_new), "", ""],
        ],
        [1.9, 1.2, 1.2, 1.5, 1.5],
    )

    doc.h("What turnovers are costing")
    doc.p(
        "<b>Performance EPA</b> counts every snap. <b>Call-sheet EPA</b> drops turnover snaps. "
        "The gap is what ball security is costing on top of the calls."
    )
    before_rows, after_rows = _turnover_cost_rows(old), _turnover_cost_rows(new)
    doc.table(
        ["", "Before", "After"],
        [[a[0], a[1], b[1]] for a, b in zip(before_rows, after_rows)],
        [3.1, 2.1, 2.1],
    )

    doc.h("Game by game")
    doc.table(list(GAME_HEADERS), _games_rows(df, new_from), list(GAME_WIDTHS))

    doc.h("Efficiency by down (turnovers removed)")
    rows = []
    for d in (1, 2, 3, 4):
        a, b = stats(old_nt[old_nt["down"] == d]), stats(new_nt[new_nt["down"] == d])
        rows.append([ordinal(d), f"{a['n']} / {b['n']}", arrow(a["epa"], b["epa"], "epa"),
                     arrow(a["sr"], b["sr"]), arrow(a["yds"], b["yds"], "num")])
    doc.table(["Down", "Snaps (before / after)", "EPA", "Success", "Yds"], rows, [0.8, 1.5, 1.8, 1.5, 1.7])

    doc.h("Run vs pass (turnovers removed)")
    rows = []
    for ph in ("run", "pass"):
        a, b = stats(old_nt[old_nt["phase"] == ph]), stats(new_nt[new_nt["phase"] == ph])
        rows.append([ph.title(), f"{a['n']} / {b['n']}", arrow(a["epa"], b["epa"], "epa"), arrow(a["sr"], b["sr"]),
                     arrow(a["yds"], b["yds"], "num"), arrow(a["neg"], b["neg"]), arrow(a["exp"], b["exp"])])
    doc.table(["", "Snaps", "EPA", "Success", "Yds", "Gained nothing", "Explosive"], rows,
              [0.6, 0.8, 1.4, 1.0, 1.0, 1.2, 1.3])

    doc.h("Run rate by down and distance (every snap)")
    rows = []
    rp = df[df["phase"].isin(["run", "pass"])]
    for d in (1, 2, 3, 4):
        for b in ("1-3", "4-6", "7-9", "10+"):
            a = rp[(rp["game_id"] < new_from) & (rp["down"] == d) & (rp["band"] == b)]
            c = rp[(rp["game_id"] >= new_from) & (rp["down"] == d) & (rp["band"] == b)]
            if len(a) + len(c) < 8:
                continue
            ra = (a["phase"] == "run").mean() if len(a) else np.nan
            rc = (c["phase"] == "run").mean() if len(c) else np.nan
            ea, ec = stats(a[a["to"] == 0]), stats(c[c["to"] == 0])
            rows.append([f"{ordinal(d)} & {b}", f"{len(a)} / {len(c)}", arrow(ra, rc),
                         arrow(ea["sr"], ec["sr"]), arrow(ea["epa"], ec["epa"], "epa")])
    doc.table(["Situation", "Snaps", "Run rate", "Success (no TO)", "EPA (no TO)"], rows,
              [1.2, 1.0, 1.6, 1.7, 1.8])

    doc.h("1st-and-10 — staying on schedule")
    doc.table(
        ["", "Before", "After"],
        [
            ["Snaps (no TO)", o_ch["n"], n_ch["n"]],
            ["EPA / play", epa_s(o_ch["epa"]), epa_s(n_ch["epa"])],
            ["Yards / play", num(o_ch["yds"]), num(n_ch["yds"])],
            ["Leaves 2nd & 6 or less", pct(o_ch["short"]), pct(n_ch["short"])],
            ["Leaves 2nd & 10+", pct(o_ch["long"]), pct(n_ch["long"])],
        ],
        [2.8, 2.2, 2.3],
    )

    doc.h("Field zone")
    rows = []
    for z, lbl in ZONES:
        a, c = old[old["field_zone"] == z], new[new["field_zone"] == z]
        if len(a) + len(c) < 6:
            continue
        sa, sc = stats(a), stats(c)
        ea, ec = stats(a[a["to"] == 0]), stats(c[c["to"] == 0])
        rows.append([lbl, f"{sa['n']} / {sc['n']}", arrow(sa["run"], sc["run"]),
                     arrow(ea["epa"], ec["epa"], "epa"), arrow(ea["sr"], ec["sr"])])
    doc.table(["Zone", "Snaps", "Run rate", "EPA (no TO)", "Success (no TO)"], rows,
              [2.0, 0.9, 1.4, 1.6, 1.4])

    doc.h("Formation usage")
    rows = []
    forms = sorted(set(df["form"]) - {""})
    for f in forms:
        a, c = old[old["form"] == f], new[new["form"] == f]
        sa_share, sc_share = len(a) / max(len(old), 1), len(c) / max(len(new), 1)
        if max(sa_share, sc_share) < 0.03:
            continue
        ec = stats(c[c["to"] == 0])
        rows.append((sc_share - sa_share, [f, arrow(sa_share, sc_share), len(c),
                                          pct(ec["run"]) if len(c) else "—",
                                          epa_s(ec["epa"]) if len(c) else "—"]))
    rows.sort(key=lambda r: r[0], reverse=True)
    doc.table(["Formation", "Share of snaps", "After snaps", "After run %", "After EPA (no TO)"],
              [r for _, r in rows], [1.8, 1.6, 1.1, 1.2, 1.6])

    doc.h("Backfield")
    rows = []
    backs = (old["back"].replace("", "(not tagged)").value_counts(normalize=True)
             .add(new["back"].replace("", "(not tagged)").value_counts(normalize=True), fill_value=0)
             .sort_values(ascending=False).index[:7])
    for bk in backs:
        a = (old["back"].replace("", "(not tagged)") == bk).mean()
        c = (new["back"].replace("", "(not tagged)") == bk).mean()
        rows.append([bk, arrow(a, c)])
    untagged_new = (new["back"] == "").mean()
    if untagged_new >= 0.4:
        doc.p(
            f"{pct(untagged_new)} of snaps since the change have no backfield tag, so part of this "
            "shift is how the film was tagged, not only what was called."
        )
    doc.table(["Backfield", "Share of snaps (before → after)"], rows, [2.5, 4.8])

    doc.h("Play-call usage")
    rows = []
    for cl in sorted(set(df["call"]) - {""}):
        a, c = (old["call"] == cl).sum(), (new["call"] == cl).sum()
        if a + c < 8:
            continue
        sa_share, sc_share = a / max(len(old), 1), c / max(len(new), 1)
        rows.append((abs(sc_share - sa_share), [cl, arrow(sa_share, sc_share), f"{a} / {c}"]))
    rows.sort(key=lambda r: r[0], reverse=True)
    doc.table(["Call", "Share of snaps", "Snaps (before / after)"], [r for _, r in rows[:16]], [2.4, 2.6, 2.3])

    doc.h("New caller — calls with 4+ snaps (turnovers removed, best to worst)")
    rows = []
    for cl, g in new_nt[new_nt["call"] != ""].groupby("call"):
        if len(g) < 4:
            continue
        s = stats(g)
        before = stats(old_nt[old_nt["call"] == cl])
        rows.append((s["epa"], [cl, s["n"], epa_s(s["epa"]), pct(s["sr"]), num(s["yds"]),
                                f"{epa_s(before['epa'])} (n={before['n']})" if before["n"] else "new"]))
    rows.sort(key=lambda r: r[0], reverse=True)
    doc.table(["Call", "Snaps", "EPA", "Success", "Yds", "Before EPA"], [r for _, r in rows],
              [1.7, 0.7, 1.0, 1.0, 0.8, 2.1])

    doc.h("Turnovers since the change")
    rows = []
    for _, r in new[new["to"] == 1].iterrows():
        rows.append([str(r["opponent"]), f"{ordinal(r['down'])} & {int(r['distance'])}" if pd.notna(r["distance"]) else "—",
                     r["phase"].title() or "—", r["form"] or "—", r["call"] or "—", str(r["result"] or ""), epa_s(r["epa"])])
    doc.table(["Game", "Situation", "Type", "Formation", "Call", "Result", "EPA"], rows,
              [1.0, 0.9, 0.6, 1.2, 1.4, 1.3, 0.8])
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=current_season_id())
    ap.add_argument("--new-caller-game", type=int, default=7,
                    help="First game_id called by the new play caller (Howe = 7).")
    args = ap.parse_args()

    df = load_season(args.season)
    if df.empty:
        print(f"No offense snaps for season {args.season}")
        return 1
    label = args.season
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    footer_label = current_season_label() or label

    season_doc = build_season_report(df, label, args.new_caller_game)
    base = OUT_DIR / f"{label}_Season_Situation_Report"
    base.with_suffix(".md").write_text(season_doc.markdown(), encoding="utf-8")
    season_doc.pdf(base.with_suffix(".pdf"), f"Football EPA · {footer_label} · Season Situation Report")
    print("wrote", base.with_suffix(".pdf"))

    if (df["game_id"] >= args.new_caller_game).any():
        change_doc = build_change_report(df, label, args.new_caller_game)
        base = OUT_DIR / f"{label}_Play_Caller_Change_Report"
        base.with_suffix(".md").write_text(change_doc.markdown(), encoding="utf-8")
        change_doc.pdf(base.with_suffix(".pdf"), f"Football EPA · {footer_label} · Play Caller Change")
        print("wrote", base.with_suffix(".pdf"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

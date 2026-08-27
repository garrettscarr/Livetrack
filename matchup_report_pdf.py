"""
Scout matchup report → printable PDF with charts.

Season EPA is primary; career EPA shown alongside when available.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

# Non-interactive backend for server / Streamlit
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BRAND = colors.HexColor("#1B4332")
BRAND_LIGHT = colors.HexColor("#2D6A4F")
MUTED = colors.HexColor("#5c6b62")
EDGE = colors.HexColor("#40916C")
TRAP = colors.HexColor("#dc2626")


def _epa_fmt(val) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):+.3f}"
    except (TypeError, ValueError):
        return "—"


def _chart_scout_tendency(rows: list[dict], title: str) -> BytesIO | None:
    """Horizontal bar chart — how often they show each look."""
    if not rows:
        return None
    top = rows[:6]
    labels = [str(r.get("look") or "")[:18] for r in top]
    pcts = [float(r.get("scout_pct") or 0) for r in top]
    if not any(pcts):
        return None

    fig, ax = plt.subplots(figsize=(7.2, max(2.8, 0.45 * len(labels) + 1.2)))
    y_pos = range(len(labels))
    ax.barh(list(y_pos), pcts, color="#2D6A4F", height=0.62)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("Scout %", fontsize=10)
    ax.set_title(title, fontsize=12, fontweight="bold", color="#1B4332", loc="left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=144, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_epa_dual(rows: list[dict], title: str, season_label: str) -> BytesIO | None:
    """Grouped bars — season vs career EPA per look."""
    usable = [
        r
        for r in rows[:6]
        if r.get("avg_epa") is not None or r.get("avg_epa_all") is not None
    ]
    if not usable:
        return None

    labels = [str(r.get("look") or "")[:14] for r in usable]
    season_epa = [
        float(r["avg_epa"]) if r.get("avg_epa") is not None else 0.0 for r in usable
    ]
    career_epa = [
        float(r["avg_epa_all"]) if r.get("avg_epa_all") is not None else 0.0
        for r in usable
    ]

    x = range(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    ax.bar([i - width / 2 for i in x], season_epa, width, label=season_label[:20], color="#40916C")
    ax.bar([i + width / 2 for i in x], career_epa, width, label="Career", color="#95D5B2")
    ax.axhline(0, color="#333", linewidth=0.8, alpha=0.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=28, ha="right", fontsize=9)
    ax.set_ylabel("Avg EPA", fontsize=10)
    ax.set_title(title, fontsize=12, fontweight="bold", color="#1B4332", loc="left")
    ax.legend(fontsize=9, frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=144, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _bullets(items: list[str], style: ParagraphStyle) -> list[Any]:
    out: list[Any] = []
    for line in items:
        if line.strip():
            out.append(Paragraph(f"• {line}", style))
    return out


def _look_table_rows(rows: list[dict], season_label: str) -> list[list[str]]:
    header = [
        "Look",
        "Scout %",
        f"EPA ({season_label[:12]})",
        "EPA (career)",
        "Verdict",
    ]
    body = [header]
    for r in rows[:10]:
        body.append(
            [
                str(r.get("look") or "")[:22],
                f"{r.get('scout_pct', 0)}%",
                _epa_fmt(r.get("avg_epa")),
                _epa_fmt(r.get("avg_epa_all")),
                str(r.get("verdict") or "—"),
            ]
        )
    return body


def build_matchup_report_pdf(report: dict) -> bytes:
    """Render a coach-ready PDF with summary, charts, and tables."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=f"Matchup vs {report.get('opponent', 'Opponent')}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RptTitle",
        parent=styles["Heading1"],
        fontSize=20,
        textColor=BRAND,
        spaceAfter=6,
        alignment=TA_LEFT,
    )
    sub_style = ParagraphStyle(
        "RptSub",
        parent=styles["Normal"],
        fontSize=10,
        textColor=MUTED,
        spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "RptH2",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=BRAND_LIGHT,
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "RptBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.black,
    )
    cue_style = ParagraphStyle(
        "RptCue",
        parent=body_style,
        fontSize=11,
        leading=15,
        leftIndent=8,
    )

    opp = str(report.get("opponent") or "Opponent")
    season_label = str(report.get("primary_season_label") or "This season")
    generated = datetime.now().strftime("%b %d, %Y · %I:%M %p")

    story: list[Any] = []
    story.append(Paragraph(f"Scout Matchup · vs {opp}", title_style))
    story.append(Paragraph(str(report.get("summary") or ""), sub_style))
    story.append(
        Paragraph(
            f"Generated {generated} · Scout snaps {report.get('scout_snaps', 0):,} · "
            f"Season n={report.get('our_plays_sampled', 0):,} · "
            f"Career n={report.get('our_plays_all_time', 0):,}",
            sub_style,
        )
    )
    for note in report.get("notes") or []:
        story.append(Paragraph(str(note), sub_style))

    # Call sheet cues (formations & plays vs their looks)
    cs = report.get("call_sheet") or {}
    cues: list[str] = []
    for e in cs.get("featured") or []:
        msg = str(e.get("message") or "").replace("**", "")
        cues.append(msg)
    for e in cs.get("avoid") or []:
        msg = "AVOID · " + str(e.get("message") or "").replace("**", "")
        cues.append(msg)
    if not cues:
        for r in report.get("edges") or []:
            cues.append(
                f"EDGE {r['look']} — they show {r['scout_pct']}% · "
                f"EPA {_epa_fmt(r.get('avg_epa'))}"
            )

    if cues:
        story.append(Spacer(1, 0.12 * inch))
        story.append(Paragraph("Call sheet", h2_style))
        story.extend(_bullets(cues[:8], cue_style))

    featured = cs.get("featured") or []
    if featured:
        chart_calls = _chart_scout_tendency(
            [
                {
                    "look": f"{r.get('when_look')} → {str(r.get('label') or '')[:16]}",
                    "scout_pct": abs(float(r.get("avg_epa") or 0)) * 100,
                }
                for r in featured[:6]
            ],
            f"Best calls vs their looks ({season_label[:14]})",
        )
        if chart_calls:
            story.append(Spacer(1, 0.08 * inch))
            story.append(Image(chart_calls, width=6.9 * inch, height=2.5 * inch))
        rows = [["Their look", "Formation / play", "EPA", "Sample"]]
        for e in featured[:10]:
            basis = str(e.get("basis") or "season")
            n = e.get("plays") or ""
            if basis == "all_time":
                sample = f"career n={n}"
            elif basis == "season_thin":
                sample = f"n={n} season"
            else:
                sample = f"n={n} this year"
            rows.append(
                [
                    f"{e.get('when_look')} ({e.get('scout_pct')}%)",
                    str(e.get("label") or "")[:28],
                    _epa_fmt(e.get("avg_epa")),
                    sample,
                ]
            )
        tbl = Table(rows, colWidths=[1.65 * inch, 2.35 * inch, 0.85 * inch, 0.55 * inch])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7F5")]),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8E2DC")),
                ]
            )
        )
        story.append(Spacer(1, 0.06 * inch))
        story.append(tbl)
        story.append(Spacer(1, 0.1 * inch))

    # Scout tendency charts
    fronts = report.get("fronts") or []
    covs = report.get("coverages") or []
    front_title = (
        "Their booth fronts (scout %)"
        if report.get("booth_front_mode") == "even_42"
        else "Their fronts (scout %)"
    )
    chart_front = _chart_scout_tendency(fronts, front_title)
    if chart_front:
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph("Tendencies", h2_style))
        story.append(Image(chart_front, width=6.9 * inch, height=2.6 * inch))

    chart_cov = _chart_scout_tendency(covs, "Their coverages (scout %)")
    if chart_cov:
        story.append(Image(chart_cov, width=6.9 * inch, height=2.4 * inch))

    pool = list(fronts) + list(covs)
    chart_epa = _chart_epa_dual(pool, "Our EPA vs their looks", season_label)
    if chart_epa:
        story.append(Spacer(1, 0.08 * inch))
        story.append(Paragraph("Our success", h2_style))
        story.append(Image(chart_epa, width=6.9 * inch, height=2.8 * inch))

    # Tables
    def _add_table(rows: list[dict], heading: str) -> None:
        if not rows:
            return
        story.append(Paragraph(heading, h2_style))
        data = _look_table_rows(rows, season_label)
        tbl = Table(data, colWidths=[1.55 * inch, 0.75 * inch, 1.05 * inch, 1.05 * inch, 0.95 * inch])
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F7F5")]),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D8E2DC")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(tbl)
        story.append(Spacer(1, 0.08 * inch))

    _add_table(fronts, front_title.replace(" (scout %)", " · detail"))
    _add_table(covs, "Coverages · detail")

    story.append(Spacer(1, 0.15 * inch))
    story.append(
        Paragraph(
            f"<para alignment='center'><font size='8' color='#5c6b62'>"
            f"Each call uses season EPA when it has ≥10 tagged snaps this year ({season_label}); "
            f"otherwise career (all-time). * = verdict from career sample.</font></para>",
            ParagraphStyle("Footer", alignment=TA_CENTER, fontSize=8),
        )
    )

    doc.build(story)
    return buf.getvalue()

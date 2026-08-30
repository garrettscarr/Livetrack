"""
Post-game breakdown report → printable multi-page PDF with graphs, tables, and coach notes.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

# Non-interactive backend for server / Streamlit
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BRAND = colors.HexColor("#1B4332")
BRAND_LIGHT = colors.HexColor("#2D6A4F")
BRAND_ACCENT = colors.HexColor("#40916C")
GOLD = colors.HexColor("#C9A227")
MUTED = colors.HexColor("#52796F")
EDGE = colors.HexColor("#2D6A4F")
TRAP = colors.HexColor("#DC2626")
BG_LIGHT = colors.HexColor("#F4F7F5")
BORDER_LIGHT = colors.HexColor("#D8E2DC")


def _chart_down_efficiency(downs: list[dict]) -> BytesIO | None:
    """Grouped bar chart: Avg Yards & Success Rate % by Down."""
    if not downs:
        return None
    labels = [f"Down {d.get('down')}" for d in downs]
    avg_yds = [float(d.get("avg_yards", 0) or 0) for d in downs]
    succ_rate = [float(d.get("success_rate", 0) or 0) * 100 for d in downs]

    fig, ax1 = plt.subplots(figsize=(6.8, 2.5))
    x = np.arange(len(labels))
    width = 0.35

    bars1 = ax1.bar(x - width / 2, avg_yds, width, label="Avg Yds / Play", color="#2D6A4F")
    ax1.set_ylabel("Yards / Play", color="#1B4332", fontsize=9, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9, fontweight="bold")
    ax1.tick_params(axis="y", labelcolor="#1B4332", labelsize=8)
    ax1.grid(axis="y", linestyle="--", alpha=0.3)
    ax1.axhline(0, color="#888", linewidth=0.7)

    # 2nd axis for success rate
    ax2 = ax1.twinx()
    bars2 = ax2.bar(x + width / 2, succ_rate, width, label="Success Rate %", color="#C9A227")
    ax2.set_ylabel("Success Rate %", color="#854D0E", fontsize=9, fontweight="bold")
    ax2.tick_params(axis="y", labelcolor="#854D0E", labelsize=8)
    ax2.set_ylim(0, max(100, max(succ_rate + [60]) * 1.15))

    # Add values on top of bars
    for bar in bars1:
        h = bar.get_height()
        va = "bottom" if h >= 0 else "top"
        ax1.annotate(f"{h:+.1f}", xy=(bar.get_x() + bar.get_width() / 2, h),
                     xytext=(0, 2 if h >= 0 else -8), textcoords="offset points",
                     ha="center", va=va, fontsize=7.5, fontweight="bold", color="#1B4332")

    for bar in bars2:
        h = bar.get_height()
        ax2.annotate(f"{h:.0f}%", xy=(bar.get_x() + bar.get_width() / 2, h),
                     xytext=(0, 2), textcoords="offset points",
                     ha="center", va="bottom", fontsize=7.5, fontweight="bold", color="#854D0E")

    plt.title("Down & Distance Efficiency (Yards & Success Rate)", fontsize=10, fontweight="bold", color="#1B4332", loc="left")
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_formation_production(formations: list[dict]) -> BytesIO | None:
    """Horizontal bar chart: Formation Snaps & Avg Yards color coded."""
    if not formations:
        return None
    top = formations[:7]
    labels = [str(f.get("formation") or "")[:15] for f in top]
    snaps = [int(f.get("plays", 0) or 0) for f in top]
    avg_yds = [float(f.get("avg_yards", 0) or 0) for f in top]
    verdicts = [str(f.get("verdict", "")).upper() for f in top]

    # Color by verdict
    bar_colors = []
    for v in verdicts:
        if "FEATURE" in v:
            bar_colors.append("#2D6A4F")  # Green
        elif "SHELVE" in v or "ADJUST" in v:
            bar_colors.append("#DC2626")  # Red
        else:
            bar_colors.append("#52796F")  # Slate green

    fig, ax = plt.subplots(figsize=(6.8, max(2.2, 0.38 * len(labels) + 0.8)))
    y_pos = np.arange(len(labels))

    bars = ax.barh(y_pos, avg_yds, color=bar_colors, height=0.55)
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"{l} (n={s})" for l, s in zip(labels, snaps)], fontsize=8.5, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xlabel("Avg Yards / Play", fontsize=9, fontweight="bold", color="#1B4332")
    ax.axvline(0, color="#666", linewidth=0.8)
    ax.grid(axis="x", linestyle="--", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for bar, y_val in zip(bars, avg_yds):
        w = bar.get_width()
        ha = "left" if w >= 0 else "right"
        offset = 0.2 if w >= 0 else -0.2
        ax.annotate(f"{w:+.1f} yds", xy=(w + offset, bar.get_y() + bar.get_height() / 2),
                    va="center", ha=ha, fontsize=8, fontweight="bold", color="#1B4332")

    plt.title("Formation Production (Avg Yards / Play & Snaps)", fontsize=10, fontweight="bold", color="#1B4332", loc="left")
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_phase_and_looks(phase_data: dict, looks_data: dict) -> BytesIO | None:
    """Side-by-side chart: Phase Yards (Run vs Pass) & Defensive Coverage Distribution."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.8, 2.2))

    # Left: Run vs Pass
    phases = ["Run Game", "Pass Game"]
    yds = [phase_data.get("run_yds", 0), phase_data.get("pass_yds", 0)]
    colors_list = ["#40916C", "#2D6A4F"]
    ax1.bar(phases, yds, color=colors_list, width=0.48)
    ax1.set_ylabel("Total Yards", fontsize=8.5, fontweight="bold", color="#1B4332")
    ax1.set_title("Total Yards by Phase", fontsize=9.5, fontweight="bold", color="#1B4332", loc="left")
    ax1.grid(axis="y", linestyle="--", alpha=0.3)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    for i, v in enumerate(yds):
        ax1.annotate(f"{v} yds", xy=(i, v), xytext=(0, 2), textcoords="offset points",
                     ha="center", va="bottom", fontsize=8, fontweight="bold", color="#1B4332")

    # Right: Coverage distribution pie/bar
    covs = looks_data.get("coverages", [])[:4]
    if covs:
        cov_labels = [f"{c.get('coverage')}" for c in covs]
        cov_pcts = [float(c.get("pct", 0)) for c in covs]
        ax2.barh(np.arange(len(cov_labels)), cov_pcts, color="#C9A227", height=0.5)
        ax2.set_yticks(np.arange(len(cov_labels)))
        ax2.set_yticklabels(cov_labels, fontsize=8, fontweight="bold")
        ax2.invert_yaxis()
        ax2.set_xlabel("% of Snaps", fontsize=8.5, fontweight="bold", color="#1B4332")
        ax2.set_title("Opponent Coverage Shown", fontsize=9.5, fontweight="bold", color="#1B4332", loc="left")
        ax2.grid(axis="x", linestyle="--", alpha=0.3)
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)
        for i, (pct, c) in enumerate(zip(cov_pcts, covs)):
            ax2.annotate(f"{pct:.0f}% ({c.get('plays')}x)", xy=(pct + 1, i), va="center",
                         fontsize=7.5, fontweight="bold", color="#854D0E")

    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def build_post_game_pdf(report: dict) -> bytes:
    """Render comprehensive Coach Post-Game PDF Report with KPI header, charts, and detailed tables."""
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        title=f"Post Game Report - {report.get('opponent', 'Game')}",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "RptTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        textColor=BRAND,
        spaceAfter=2,
        alignment=TA_LEFT,
    )
    sub_style = ParagraphStyle(
        "RptSub",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=MUTED,
        spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "RptH2",
        parent=styles["Heading2"],
        fontSize=11,
        leading=14,
        textColor=BRAND,
        spaceBefore=8,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "RptBody",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#1A202C"),
    )
    bullet_style = ParagraphStyle(
        "RptBullet",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1A202C"),
        leftIndent=10,
    )
    kpi_num_style = ParagraphStyle(
        "KpiNum",
        alignment=TA_CENTER,
        fontSize=13,
        leading=15,
        fontName="Helvetica-Bold",
        textColor=BRAND,
    )
    kpi_label_style = ParagraphStyle(
        "KpiLabel",
        alignment=TA_CENTER,
        fontSize=7.5,
        leading=9,
        textColor=MUTED,
    )

    story: list[Any] = []

    # Title & Metadata
    opp = report.get("opponent", "Opponent")
    season = report.get("season", "26-27")
    game_label = report.get("game_label", f"{opp} (Week 1)")
    stamp = report.get("generated_at", datetime.now().strftime("%B %d, %Y"))

    story.append(Paragraph(f"📋 Post-Game Performance Report: {opp}", title_style))
    story.append(
        Paragraph(
            f"<b>Game:</b> {game_label} &nbsp;·&nbsp; <b>Season:</b> {season} &nbsp;·&nbsp; "
            f"<b>Film Source:</b> {report.get('source_file', 'Hudl Export')} ({report.get('plays', 0)} plays) &nbsp;·&nbsp; "
            f"<b>Generated:</b> {stamp}",
            sub_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.5, color=BRAND, spaceBefore=2, spaceAfter=6))

    # KPI Summary Cards Block (2 rows of 4 metrics)
    kpis = report.get("summary_kpis", {})
    actual_pts = kpis.get("actual_points", 0)
    xpoints = kpis.get("xpoints", 0.0)
    luck = kpis.get("luck", 0.0)
    luck_str = f"{luck:+.1f}" if luck != 0 else "0.0"
    luck_color = "#2D6A4F" if luck >= 0 else "#DC2626"

    kpi_row1 = [
        [
            Paragraph(f"{kpis.get('touchdowns', 0)} TDs", kpi_num_style),
            Paragraph(f"{kpis.get('total_yards', 0)} yds", kpi_num_style),
            Paragraph(f"{kpis.get('avg_yards', 0.0):.1f}", kpi_num_style),
            Paragraph(f"{kpis.get('total_epa', 0.0):+.2f}", kpi_num_style),
        ],
        [
            Paragraph("Points Scored (6/TD)", kpi_label_style),
            Paragraph("Total Offense", kpi_label_style),
            Paragraph("Yards / Play", kpi_label_style),
            Paragraph("Total EPA (Process)", kpi_label_style),
        ],
    ]
    kpi_row2 = [
        [
            Paragraph(f"{xpoints:.1f}", kpi_num_style),
            Paragraph(f"<font color='{luck_color}'>{luck_str}</font>", kpi_num_style),
            Paragraph(f"{kpis.get('explosive_count', 0)} ({kpis.get('explosive_pct', 0):.0f}%)", kpi_num_style),
            Paragraph(f"{kpis.get('negative_count', 0)} ({kpis.get('negative_pct', 0):.0f}%)", kpi_num_style),
        ],
        [
            Paragraph("Expected Points (xP)", kpi_label_style),
            Paragraph("Finishing Luck", kpi_label_style),
            Paragraph("Explosive Plays (10+ yds)", kpi_label_style),
            Paragraph("Negative / 0-Gain Plays", kpi_label_style),
        ],
    ]

    card_data = [
        kpi_row1[0],
        kpi_row1[1],
        kpi_row2[0],
        kpi_row2[1],
    ]
    card_table = Table(card_data, colWidths=[1.8 * inch, 1.8 * inch, 1.8 * inch, 1.8 * inch])
    card_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
                ("BOX", (0, 0), (-1, -1), 1, BORDER_LIGHT),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(card_table)
    story.append(Spacer(1, 0.08 * inch))

    # Key Coach Action Items Block
    takeaways = report.get("coach_takeaways", [])
    if takeaways:
        story.append(Paragraph("💡 Key Takeaways & Week 2 Adjustments", h2_style))
        for t in takeaways:
            story.append(Paragraph(f"• {t}", bullet_style))
        story.append(Spacer(1, 0.08 * inch))

    # Visual Graphs Section
    story.append(Paragraph("📊 Visual Performance Charts", h2_style))

    downs_list = report.get("down_efficiency", [])
    chart_down = _chart_down_efficiency(downs_list)
    if chart_down:
        story.append(Image(chart_down, width=7.2 * inch, height=2.4 * inch))
        story.append(Spacer(1, 0.05 * inch))

    form_list = report.get("formation_defense", [])
    chart_form = _chart_formation_production(form_list)
    if chart_form:
        story.append(Image(chart_form, width=7.2 * inch, height=2.3 * inch))
        story.append(Spacer(1, 0.05 * inch))

    phase_data = report.get("phase_data", {})
    looks_data = report.get("looks_faced", {})
    chart_phase = _chart_phase_and_looks(phase_data, looks_data)
    if chart_phase:
        story.append(Image(chart_phase, width=7.2 * inch, height=2.2 * inch))
        story.append(Spacer(1, 0.08 * inch))

    # Down & Distance Table
    if downs_list:
        story.append(Paragraph("📉 Down & Distance Efficiency Breakdown", h2_style))
        down_headers = ["Down", "Plays", "Total Yds", "Avg Yds", "Avg EPA", "Success Rate", "Key Takeaway / Tendency"]
        down_rows = [down_headers]
        for d in downs_list:
            down_rows.append(
                [
                    str(d.get("label", f"Down {d.get('down')}")),
                    str(d.get("plays", 0)),
                    f"{d.get('total_yards', 0):+d}" if d.get("total_yards") is not None else "0",
                    f"{d.get('avg_yards', 0.0):+.1f}",
                    f"{d.get('avg_epa', 0.0):+.2f}",
                    f"{float(d.get('success_rate', 0.0))*100:.0f}%",
                    str(d.get("notes", "")),
                ]
            )
        down_tbl = Table(down_rows, colWidths=[0.85 * inch, 0.55 * inch, 0.75 * inch, 0.75 * inch, 0.75 * inch, 0.9 * inch, 2.65 * inch])
        down_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(down_tbl)
        story.append(Spacer(1, 0.08 * inch))

    # Formation Defense Breakdown
    if form_list:
        story.append(Paragraph("🛡️ How They Defended Our Formations", h2_style))
        form_headers = ["Formation", "Snaps", "Total Yds", "Avg Yds", "Success %", "Looks Shown", "Verdict", "Best Call"]
        form_rows = [form_headers]
        for f in form_list:
            bp = f.get("best_play")
            bp_str = f"{bp['play_call']} ({bp['avg_yards']:+.1f}y)" if bp else "—"
            verdict = str(f.get("verdict", "SOLID")).upper()
            form_rows.append(
                [
                    str(f.get("formation", "")),
                    str(f.get("plays", 0)),
                    f"{f.get('total_yards', 0)}",
                    f"{f.get('avg_yards', 0.0):+.1f}",
                    f"{float(f.get('success_rate', 0.0))*100:.0f}%",
                    str(f.get("tell_summary", "")),
                    verdict,
                    bp_str,
                ]
            )
        form_tbl = Table(form_rows, colWidths=[1.15 * inch, 0.5 * inch, 0.65 * inch, 0.65 * inch, 0.75 * inch, 1.65 * inch, 0.85 * inch, 1.0 * inch])
        form_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(form_tbl)
        story.append(Spacer(1, 0.08 * inch))

    # Formation + Play Combos (Feature vs Shelve)
    combos = report.get("formation_combos", [])
    if combos:
        story.append(Paragraph("⚡ Formation + Play Combinations (Feature vs Shelve)", h2_style))
        combo_headers = ["Combo", "Snaps", "Yards (Avg)", "Success %", "Outcomes", "Look Faced", "Verdict & Coach Note"]
        combo_rows = [combo_headers]
        for c in combos[:12]:
            combo_rows.append(
                [
                    str(c.get("combo", "")),
                    str(c.get("plays", 0)),
                    f"{c.get('avg_yards', 0.0):+.1f} yds",
                    f"{float(c.get('success_rate', 0.0))*100:.0f}%",
                    str(c.get("outcomes_str", "")[:24]),
                    str(c.get("look_summary", "")[:20]),
                    f"[{c.get('verdict', 'SOLID')}] {c.get('coach_tip', '')[:45]}",
                ]
            )
        combo_tbl = Table(combo_rows, colWidths=[1.3 * inch, 0.45 * inch, 0.8 * inch, 0.7 * inch, 1.15 * inch, 1.05 * inch, 1.75 * inch])
        combo_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(combo_tbl)
        story.append(Spacer(1, 0.08 * inch))

    # Explosive & Scoring Plays Log
    explosives = report.get("explosive_plays", [])
    if explosives:
        story.append(Paragraph("🎬 Explosive (10+ Yds) & Scoring Plays Log", h2_style))
        exp_headers = ["Play #", "Down & Dist", "Formation", "Play Call", "Result", "Gain", "Def Look"]
        exp_rows = [exp_headers]
        for ep in explosives[:15]:
            exp_rows.append(
                [
                    f"#{ep.get('play_num', '')}",
                    str(ep.get("situation", "")),
                    str(ep.get("formation", "")),
                    str(ep.get("play_call", "")),
                    str(ep.get("result", "")),
                    f"{ep.get('yards_gained', 0):+d} yds",
                    str(ep.get("look", "")),
                ]
            )
        exp_tbl = Table(exp_rows, colWidths=[0.6 * inch, 0.9 * inch, 1.25 * inch, 1.45 * inch, 1.15 * inch, 0.8 * inch, 1.05 * inch])
        exp_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(exp_tbl)
        story.append(Spacer(1, 0.1 * inch))

    # Footer note
    story.append(
        Paragraph(
            "<para alignment='center'><font size='7.5' color='#52796F'>"
            "Football EPA Post-Game Review · Process vs Outcome Analytics · Confidential for Coaching Staff</font></para>",
            ParagraphStyle("Footer", alignment=TA_CENTER, fontSize=7.5),
        )
    )

    doc.build(story)
    return buf.getvalue()

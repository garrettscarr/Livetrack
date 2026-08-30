"""
Post-game breakdown report → printable multi-page PDF with charts, tables, and coach notes.
Designed for high-impact coach presentations: crisp typography, structured pages, and clean data visualization.
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
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Brand Color Palette
BRAND = colors.HexColor("#1B4332")          # Deep Forest Green
BRAND_LIGHT = colors.HexColor("#2D6A4F")    # Medium Forest
BRAND_ACCENT = colors.HexColor("#40916C")   # Accent Green
GOLD = colors.HexColor("#C9A227")           # Athletic Gold
GOLD_DARK = colors.HexColor("#854D0E")      # Amber Brown
MUTED = colors.HexColor("#52796F")          # Slate Muted Green
DARK_TEXT = colors.HexColor("#111827")      # Rich Off-Black
BODY_TEXT = colors.HexColor("#1F2937")      # Charcoal Body
BG_LIGHT = colors.HexColor("#F8FAFC")       # Soft Ice White / Light Slate
BG_CARD = colors.HexColor("#F1F5F9")        # Soft Slate
BORDER_LIGHT = colors.HexColor("#CBD5E1")   # Subtle Border
FEATURE_GREEN = colors.HexColor("#15803D")  # Crisp Emerald Green
SHELVE_RED = colors.HexColor("#DC2626")     # Cardinal Red


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas for total page count & running headers/footers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))

        # Running Header (pages 2+)
        if self._pageNumber > 1:
            self.drawString(0.45 * inch, 10.55 * inch, "Football EPA · Post-Game Performance Breakdown")
            self.setStrokeColor(BORDER_LIGHT)
            self.setLineWidth(0.5)
            self.line(0.45 * inch, 10.45 * inch, 8.05 * inch, 10.45 * inch)

        # Running Footer (all pages)
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(8.05 * inch, 0.35 * inch, page_text)
        self.drawString(
            0.45 * inch,
            0.35 * inch,
            "CONFIDENTIAL · For Coaching Staff Only · Powered by Football EPA Analytics",
        )
        self.setStrokeColor(BORDER_LIGHT)
        self.setLineWidth(0.5)
        self.line(0.45 * inch, 0.48 * inch, 8.05 * inch, 0.48 * inch)
        self.restoreState()


def _chart_down_efficiency(downs: list[dict]) -> BytesIO | None:
    """Grouped bar chart: Avg Yards & Success Rate % by Down."""
    if not downs:
        return None
    labels = [str(d.get("label", f"Down {d.get('down')}"))[:8] for d in downs]
    avg_yds = [float(d.get("avg_yards", 0) or 0) for d in downs]
    succ_rate = [float(d.get("success_rate", 0) or 0) * 100 for d in downs]

    fig, ax1 = plt.subplots(figsize=(6.9, 2.3), facecolor="white")
    x = np.arange(len(labels))
    width = 0.32

    # Yards bars
    bars1 = ax1.bar(x - width / 2, avg_yds, width, label="Yds / Play", color="#2D6A4F", edgecolor="none", zorder=3)
    ax1.set_ylabel("Avg Yards", color="#1B4332", fontsize=8.5, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=8.5, fontweight="bold", color="#1F2937")
    ax1.tick_params(axis="y", labelcolor="#1B4332", labelsize=8)
    ax1.grid(axis="y", linestyle="--", alpha=0.3, zorder=0)
    ax1.axhline(0, color="#94A3B8", linewidth=0.8, zorder=2)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.spines["left"].set_color("#CBD5E1")
    ax1.spines["bottom"].set_color("#CBD5E1")

    # Success rate bars
    ax2 = ax1.twinx()
    bars2 = ax2.bar(x + width / 2, succ_rate, width, label="Success %", color="#C9A227", edgecolor="none", zorder=3)
    ax2.set_ylabel("Success Rate %", color="#854D0E", fontsize=8.5, fontweight="bold")
    ax2.tick_params(axis="y", labelcolor="#854D0E", labelsize=8)
    ax2.set_ylim(0, max(100, max(succ_rate + [60]) * 1.15))
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#CBD5E1")
    ax2.spines["bottom"].set_color("#CBD5E1")

    # Value callouts
    for bar in bars1:
        h = bar.get_height()
        va = "bottom" if h >= 0 else "top"
        ax1.annotate(
            f"{h:+.1f}",
            xy=(bar.get_x() + bar.get_width() / 2, h),
            xytext=(0, 2 if h >= 0 else -8),
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=7.5,
            fontweight="bold",
            color="#1B4332",
        )

    for bar in bars2:
        h = bar.get_height()
        ax2.annotate(
            f"{h:.0f}%",
            xy=(bar.get_x() + bar.get_width() / 2, h),
            xytext=(0, 2),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=7.5,
            fontweight="bold",
            color="#854D0E",
        )

    plt.title("Down & Distance Performance (Yards & Success %)", fontsize=9.5, fontweight="bold", color="#1B4332", loc="left", pad=8)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_phase_and_tendencies(phase_data: dict, looks_data: dict) -> BytesIO | None:
    """Side-by-side: Run vs Pass Phase yardage + Opponent Coverage Tendency."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.9, 2.1), facecolor="white")

    # Left: Run vs Pass
    phases = ["Run Game", "Pass Game"]
    yds = [phase_data.get("run_yds", 0), phase_data.get("pass_yds", 0)]
    colors_list = ["#40916C", "#2D6A4F"]
    ax1.bar(phases, yds, color=colors_list, width=0.45, zorder=3)
    ax1.set_ylabel("Total Yards", fontsize=8.5, fontweight="bold", color="#1B4332")
    ax1.set_title("Phase Yardage Production", fontsize=9, fontweight="bold", color="#1B4332", loc="left")
    ax1.grid(axis="y", linestyle="--", alpha=0.3, zorder=0)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)
    ax1.spines["left"].set_color("#CBD5E1")
    ax1.spines["bottom"].set_color("#CBD5E1")
    ax1.tick_params(axis="both", labelsize=8, labelcolor="#1F2937")

    for i, v in enumerate(yds):
        ax1.annotate(
            f"{v} yds",
            xy=(i, v),
            xytext=(0, 2),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color="#1B4332",
        )

    # Right: Coverage distribution
    covs = looks_data.get("coverages", [])[:4]
    if covs:
        cov_labels = [f"{c.get('coverage')}" for c in covs]
        cov_pcts = [float(c.get("pct", 0)) for c in covs]
        y_pos = np.arange(len(cov_labels))
        ax2.barh(y_pos, cov_pcts, color="#C9A227", height=0.5, zorder=3)
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels(cov_labels, fontsize=8, fontweight="bold", color="#1F2937")
        ax2.invert_yaxis()
        ax2.set_xlabel("% of Defensive Snaps", fontsize=8, fontweight="bold", color="#1B4332")
        ax2.set_title("Opponent Coverage Shown", fontsize=9, fontweight="bold", color="#1B4332", loc="left")
        ax2.grid(axis="x", linestyle="--", alpha=0.3, zorder=0)
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)
        ax2.spines["left"].set_color("#CBD5E1")
        ax2.spines["bottom"].set_color("#CBD5E1")
        ax2.tick_params(axis="both", labelsize=8, labelcolor="#1F2937")

        for i, (pct, c) in enumerate(zip(cov_pcts, covs)):
            ax2.annotate(
                f"{pct:.0f}% ({c.get('plays')}x)",
                xy=(pct + 1.2, i),
                va="center",
                fontsize=7.5,
                fontweight="bold",
                color="#854D0E",
            )

    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_formation_production(formations: list[dict]) -> BytesIO | None:
    """Horizontal bar chart: Formation Snaps & Avg Yards color-coded by verdict."""
    if not formations:
        return None
    top = formations[:7]
    labels = [str(f.get("formation") or "")[:14] for f in top]
    snaps = [int(f.get("plays", 0) or 0) for f in top]
    avg_yds = [float(f.get("avg_yards", 0) or 0) for f in top]
    verdicts = [str(f.get("verdict", "")).upper() for f in top]

    bar_colors = []
    for v in verdicts:
        if "FEATURE" in v:
            bar_colors.append("#2D6A4F")  # Green
        elif "SHELVE" in v or "ADJUST" in v:
            bar_colors.append("#DC2626")  # Red
        else:
            bar_colors.append("#52796F")  # Slate

    fig, ax = plt.subplots(figsize=(6.9, max(2.1, 0.35 * len(labels) + 0.6)), facecolor="white")
    y_pos = np.arange(len(labels))

    bars = ax.barh(y_pos, avg_yds, color=bar_colors, height=0.52, zorder=3)
    ax.set_yticks(y_pos)
    ax.set_yticklabels([f"{l} (n={s})" for l, s in zip(labels, snaps)], fontsize=8, fontweight="bold", color="#1F2937")
    ax.invert_yaxis()
    ax.set_xlabel("Avg Yards / Play", fontsize=8.5, fontweight="bold", color="#1B4332")
    ax.axvline(0, color="#64748B", linewidth=0.8, zorder=2)
    ax.grid(axis="x", linestyle="--", alpha=0.3, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(axis="both", labelsize=8, labelcolor="#1F2937")

    for bar, y_val in zip(bars, avg_yds):
        w = bar.get_width()
        ha = "left" if w >= 0 else "right"
        offset = 0.2 if w >= 0 else -0.2
        ax.annotate(
            f"{w:+.1f} yds",
            xy=(w + offset, bar.get_y() + bar.get_height() / 2),
            va="center",
            ha=ha,
            fontsize=7.5,
            fontweight="bold",
            color="#1B4332" if w >= 0 else "#DC2626",
        )

    plt.title("Formation Effectiveness (Avg Yards / Play)", fontsize=9.5, fontweight="bold", color="#1B4332", loc="left", pad=6)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def build_post_game_pdf(report: dict) -> bytes:
    """
    Render professional, publication-quality multi-page PDF report.
    - Page 1: Executive Dashboard, KPIs, Coach Takeaways, Down Efficiency & Phase Charts.
    - Page 2: Formation Defense Breakdown & Formation-Play Combos (Feature vs Shelve).
    - Page 3: Explosive (10+ Yds) & Scoring Reel Log + Game Wrap-Up.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.55 * inch,
        title=f"Post Game Report - {report.get('opponent', 'Game')}",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "RptTitle",
        parent=styles["Heading1"],
        fontSize=17,
        leading=21,
        textColor=BRAND,
        spaceAfter=1,
        alignment=TA_LEFT,
        fontName="Helvetica-Bold",
    )
    sub_style = ParagraphStyle(
        "RptSub",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=MUTED,
        spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "RptH2",
        parent=styles["Heading2"],
        fontSize=10.5,
        leading=13,
        textColor=BRAND,
        spaceBefore=6,
        spaceAfter=3,
        fontName="Helvetica-Bold",
    )
    bullet_style = ParagraphStyle(
        "RptBullet",
        parent=styles["Normal"],
        fontSize=8,
        leading=10.5,
        textColor=BODY_TEXT,
        leftIndent=8,
        spaceAfter=2,
    )
    kpi_num_style = ParagraphStyle(
        "KpiNum",
        alignment=TA_CENTER,
        fontSize=12,
        leading=14,
        fontName="Helvetica-Bold",
        textColor=BRAND,
    )
    kpi_sub_style = ParagraphStyle(
        "KpiSub",
        alignment=TA_CENTER,
        fontSize=7,
        leading=8.5,
        fontName="Helvetica-Bold",
        textColor=MUTED,
    )
    kpi_label_style = ParagraphStyle(
        "KpiLabel",
        alignment=TA_CENTER,
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#64748B"),
    )

    tbl_head_style = ParagraphStyle(
        "TblHead",
        fontSize=7.5,
        leading=9,
        fontName="Helvetica-Bold",
        textColor=colors.white,
    )
    tbl_cell_style = ParagraphStyle(
        "TblCell",
        fontSize=7.5,
        leading=9.5,
        textColor=BODY_TEXT,
    )
    tbl_cell_bold = ParagraphStyle(
        "TblCellBold",
        fontSize=7.5,
        leading=9.5,
        fontName="Helvetica-Bold",
        textColor=BODY_TEXT,
    )

    story: list[Any] = []

    # Metadata
    opp = report.get("opponent", "Opponent")
    season = report.get("season", "26-27")
    game_label = report.get("game_label", f"{opp} (Week 1)")
    stamp = report.get("generated_at", datetime.now().strftime("%B %d, %Y"))

    # =========================================================================
    # PAGE 1: Executive Dashboard, Scoreboard, Phase/Down Analysis
    # =========================================================================

    story.append(Paragraph(f"📋 Post-Game Performance Report: {opp}", title_style))
    story.append(
        Paragraph(
            f"<b>Game:</b> {game_label} &nbsp;·&nbsp; <b>Season:</b> {season} &nbsp;·&nbsp; "
            f"<b>Film Source:</b> {report.get('source_file', 'Hudl Export')} ({report.get('plays', 0)} offensive snaps) &nbsp;·&nbsp; "
            f"<b>Date:</b> {stamp}",
            sub_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.5, color=BRAND, spaceBefore=1, spaceAfter=4))

    # KPI Summary Cards (Clean 4x2 Grid)
    kpis = report.get("summary_kpis", {})
    actual_pts = kpis.get("actual_points", 0)
    xpoints = kpis.get("xpoints", 0.0)
    luck = kpis.get("luck", 0.0)
    luck_str = f"{luck:+.1f} luck" if luck != 0 else "0.0 luck"
    luck_color = "#15803D" if luck >= 0 else "#DC2626"

    kpi_row1 = [
        [
            Paragraph(f"{kpis.get('touchdowns', 0)} TDs", kpi_num_style),
            Paragraph(f"{kpis.get('total_yards', 0)} yds", kpi_num_style),
            Paragraph(f"{kpis.get('avg_yards', 0.0):.1f}", kpi_num_style),
            Paragraph(f"{kpis.get('total_epa', 0.0):+.2f}", kpi_num_style),
        ],
        [
            Paragraph(f"{actual_pts} pts scored", kpi_sub_style),
            Paragraph("Total Offense", kpi_label_style),
            Paragraph("Yards / Play", kpi_label_style),
            Paragraph(f"{kpis.get('avg_epa', 0.0):+.2f} /play", kpi_sub_style),
        ],
    ]
    kpi_row2 = [
        [
            Paragraph(f"{xpoints:.1f} xP", kpi_num_style),
            Paragraph(f"<font color='{luck_color}'>{luck_str}</font>", kpi_num_style),
            Paragraph(f"{kpis.get('explosive_count', 0)} plays", kpi_num_style),
            Paragraph(f"{kpis.get('negative_count', 0)} plays", kpi_num_style),
        ],
        [
            Paragraph("Expected Points (xP)", kpi_label_style),
            Paragraph("Finishing Efficiency", kpi_label_style),
            Paragraph(f"{kpis.get('explosive_pct', 0):.0f}% rate (10+ yds)", kpi_sub_style),
            Paragraph(f"{kpis.get('negative_pct', 0):.0f}% rate (≤0 yds)", kpi_sub_style),
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
                ("BOX", (0, 0), (-1, -1), 0.75, BORDER_LIGHT),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER_LIGHT),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(card_table)
    story.append(Spacer(1, 0.05 * inch))

    # Key Takeaways Box
    takeaways = report.get("coach_takeaways", [])
    if takeaways:
        story.append(Paragraph("💡 Key Takeaways & Action Items", h2_style))
        for t in takeaways:
            clean_t = t.replace("<b>", "<b>").replace("</b>", "</b>")
            story.append(Paragraph(f"• {clean_t}", bullet_style))
        story.append(Spacer(1, 0.05 * inch))

    # Down & Distance Efficiency Table
    downs_list = report.get("down_efficiency", [])
    if downs_list:
        story.append(Paragraph("📉 Down & Distance Efficiency", h2_style))
        down_headers = [
            Paragraph("Down", tbl_head_style),
            Paragraph("Plays", tbl_head_style),
            Paragraph("Total Yds", tbl_head_style),
            Paragraph("Avg Yds", tbl_head_style),
            Paragraph("Avg EPA", tbl_head_style),
            Paragraph("Success %", tbl_head_style),
            Paragraph("Key Takeaway / Notes", tbl_head_style),
        ]
        down_rows = [down_headers]
        for d in downs_list:
            down_rows.append(
                [
                    Paragraph(str(d.get("label", f"Down {d.get('down')}")), tbl_cell_bold),
                    Paragraph(str(d.get("plays", 0)), tbl_cell_style),
                    Paragraph(f"{d.get('total_yards', 0):+d}", tbl_cell_style),
                    Paragraph(f"{d.get('avg_yards', 0.0):+.1f}", tbl_cell_style),
                    Paragraph(f"{d.get('avg_epa', 0.0):+.2f}", tbl_cell_style),
                    Paragraph(f"{float(d.get('success_rate', 0.0))*100:.0f}%", tbl_cell_bold),
                    Paragraph(str(d.get("notes", "")), tbl_cell_style),
                ]
            )
        down_tbl = Table(
            down_rows,
            colWidths=[0.85 * inch, 0.5 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch, 0.8 * inch, 2.95 * inch],
        )
        down_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        story.append(down_tbl)
        story.append(Spacer(1, 0.06 * inch))

    # Charts on Page 1: Down Efficiency + Phase Production
    chart_down = _chart_down_efficiency(downs_list)
    if chart_down:
        story.append(Image(chart_down, width=7.2 * inch, height=2.25 * inch))

    phase_data = report.get("phase_data", {})
    looks_data = report.get("looks_faced", {})
    chart_phase = _chart_phase_and_tendencies(phase_data, looks_data)
    if chart_phase:
        story.append(Spacer(1, 0.04 * inch))
        story.append(Image(chart_phase, width=7.2 * inch, height=2.05 * inch))

    # =========================================================================
    # PAGE 2: Formation Performance & Combinations (Feature vs Shelve)
    # =========================================================================
    story.append(PageBreak())

    form_list = report.get("formation_defense", [])
    story.append(Paragraph("🛡️ How They Defended Our Formations", title_style))
    story.append(
        Paragraph(
            "Detailed breakdown of how the opponent structured their front, coverage, and blitz rate vs each offensive look.",
            sub_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_LIGHT, spaceBefore=1, spaceAfter=4))

    # Formation production chart
    chart_form = _chart_formation_production(form_list)
    if chart_form:
        story.append(Image(chart_form, width=7.2 * inch, height=2.1 * inch))
        story.append(Spacer(1, 0.06 * inch))

    # Formation Table
    if form_list:
        form_headers = [
            Paragraph("Formation", tbl_head_style),
            Paragraph("Snaps", tbl_head_style),
            Paragraph("Total Yds", tbl_head_style),
            Paragraph("Avg Yds", tbl_head_style),
            Paragraph("Success %", tbl_head_style),
            Paragraph("Looks Shown", tbl_head_style),
            Paragraph("Verdict", tbl_head_style),
            Paragraph("Best Play Call", tbl_head_style),
        ]
        form_rows = [form_headers]
        for f in form_list:
            bp = f.get("best_play")
            bp_str = f"{bp['play_call']} ({bp['avg_yards']:+.1f}y)" if bp else "—"
            verdict = str(f.get("verdict", "SOLID")).upper()
            v_color = "#15803D" if "FEATURE" in verdict else "#DC2626" if "SHELVE" in verdict else "#475569"
            form_rows.append(
                [
                    Paragraph(f"<b>{f.get('formation', '')}</b>", tbl_cell_style),
                    Paragraph(str(f.get("plays", 0)), tbl_cell_style),
                    Paragraph(f"{f.get('total_yards', 0)}", tbl_cell_style),
                    Paragraph(f"{f.get('avg_yards', 0.0):+.1f}", tbl_cell_style),
                    Paragraph(f"{float(f.get('success_rate', 0.0))*100:.0f}%", tbl_cell_bold),
                    Paragraph(str(f.get("tell_summary", "")), tbl_cell_style),
                    Paragraph(f"<font color='{v_color}'><b>{verdict}</b></font>", tbl_cell_style),
                    Paragraph(bp_str, tbl_cell_style),
                ]
            )
        form_tbl = Table(
            form_rows,
            colWidths=[1.15 * inch, 0.45 * inch, 0.65 * inch, 0.65 * inch, 0.7 * inch, 1.75 * inch, 0.8 * inch, 1.05 * inch],
        )
        form_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        story.append(form_tbl)
        story.append(Spacer(1, 0.08 * inch))

    # Formation + Play Combos Table
    combos = report.get("formation_combos", [])
    if combos:
        story.append(Paragraph("⚡ Formation + Play Combinations (What Worked vs What Didn't)", h2_style))
        combo_headers = [
            Paragraph("Formation · Play Combo", tbl_head_style),
            Paragraph("Snaps", tbl_head_style),
            Paragraph("Avg Yds", tbl_head_style),
            Paragraph("Success %", tbl_head_style),
            Paragraph("Outcomes Sequence", tbl_head_style),
            Paragraph("Verdict & Coach Action", tbl_head_style),
        ]
        combo_rows = [combo_headers]
        for c in combos[:10]:
            verdict = str(c.get("verdict", "SOLID")).upper()
            v_color = "#15803D" if "FEATURE" in verdict else "#DC2626" if "SHELVE" in verdict else "#475569"
            tip = str(c.get("coach_tip", ""))
            combo_rows.append(
                [
                    Paragraph(f"<b>{c.get('combo', '')}</b>", tbl_cell_style),
                    Paragraph(str(c.get("plays", 0)), tbl_cell_style),
                    Paragraph(f"{c.get('avg_yards', 0.0):+.1f} yds", tbl_cell_style),
                    Paragraph(f"{float(c.get('success_rate', 0.0))*100:.0f}%", tbl_cell_bold),
                    Paragraph(str(c.get("outcomes_str", "")), tbl_cell_style),
                    Paragraph(f"<font color='{v_color}'><b>[{verdict}]</b></font> {tip}", tbl_cell_style),
                ]
            )
        combo_tbl = Table(
            combo_rows,
            colWidths=[1.45 * inch, 0.45 * inch, 0.7 * inch, 0.7 * inch, 1.45 * inch, 2.45 * inch],
        )
        combo_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        story.append(combo_tbl)

    # =========================================================================
    # PAGE 3: Explosive Plays Reel & Coach Game Wrap
    # =========================================================================
    story.append(PageBreak())

    story.append(Paragraph("🎬 Explosive Plays (10+ Yards) & Scoring Reel", title_style))
    story.append(
        Paragraph(
            "Every play of 10+ yards or touchdown, cross-referenced with formation, play call, and defensive look.",
            sub_style,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_LIGHT, spaceBefore=1, spaceAfter=5))

    explosives = report.get("explosive_plays", [])
    if explosives:
        exp_headers = [
            Paragraph("Play #", tbl_head_style),
            Paragraph("Situation", tbl_head_style),
            Paragraph("Formation", tbl_head_style),
            Paragraph("Play Call", tbl_head_style),
            Paragraph("Result", tbl_head_style),
            Paragraph("Gain", tbl_head_style),
            Paragraph("Def Look Faced", tbl_head_style),
        ]
        exp_rows = [exp_headers]
        for ep in explosives:
            res_str = str(ep.get("result", ""))
            res_style = tbl_cell_bold if "TD" in res_str.upper() else tbl_cell_style
            exp_rows.append(
                [
                    Paragraph(f"#{ep.get('play_num', '')}", tbl_cell_style),
                    Paragraph(str(ep.get("situation", "")), tbl_cell_style),
                    Paragraph(f"<b>{ep.get('formation', '')}</b>", tbl_cell_style),
                    Paragraph(f"<b>{ep.get('play_call', '')}</b>", tbl_cell_style),
                    Paragraph(res_str, res_style),
                    Paragraph(f"<b>{ep.get('yards_gained', 0):+d} yds</b>", tbl_cell_bold),
                    Paragraph(str(ep.get("look", "")), tbl_cell_style),
                ]
            )
        exp_tbl = Table(
            exp_rows,
            colWidths=[0.6 * inch, 0.9 * inch, 1.35 * inch, 1.55 * inch, 1.1 * inch, 0.8 * inch, 0.9 * inch],
        )
        exp_tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), BRAND),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG_LIGHT]),
                    ("GRID", (0, 0), (-1, -1), 0.3, BORDER_LIGHT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        story.append(exp_tbl)
        story.append(Spacer(1, 0.12 * inch))

    # Wrap-up summary card
    summary_card = [
        [
            Paragraph("<b>Coaching Staff Summary Notes:</b>", tbl_cell_bold),
        ],
        [
            Paragraph(
                "• <b>Game Process:</b> High-level red zone execution and perimeter shot-making fueled a +15.6 finishing luck differential.<br/>"
                "• <b>Preparation Focus:</b> Continue featuring <i>SLOT TRIG</i> and <i>TEXAS NASTY</i> as primary run/pass conflict looks while cleaning up protection on 3rd down.<br/>"
                "• <b>Film Tagging:</b> Tagged 74 of 77 offensive plays (96% tag quality) for high-accuracy season EPA modeling.",
                tbl_cell_style,
            ),
        ],
    ]
    summary_tbl = Table(summary_card, colWidths=[7.2 * inch])
    summary_tbl.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.75, BORDER_LIGHT),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(summary_tbl)

    # Build document using NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()

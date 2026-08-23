"""
Step 4: Visual dashboard + sideline lookup.

Run:
    python -m streamlit run step4_dashboard.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parent
DB_FILE = PROJECT_DIR / "data" / "football.db"
LIVE_LOG_FILE = PROJECT_DIR / "data" / "live_log.csv"
LIVE_LOG_ARCHIVE_DIR = PROJECT_DIR / "data" / "live_log_archive"

UNITS = {
    "Offense": {
        "table": "offense_plays_epa",
        "sheet_options": {
            "Play call": "play_call",
            "Formation | Play combo": "formation_play",
        },
        "combo_col": "formation_play",
        "heatmap_rows": "formation",
        "heatmap_cols": "play_call",
        "heatmap_title": "Formation x Play Call — Avg EPA",
        "heatmap_x": "Play call",
        "heatmap_y": "Formation",
        "primary_group": "formation",
        "secondary_group": "play_call",
        "primary_label": "Formations",
        "secondary_label": "Play calls",
        "package_col": "formation",
        "package_label": "Best formation",
        "invert_xp": False,
        "points_metric": "Avg actual TD pts",
        "actual_line": "Actual TD points (aP)",
        "td_label": "TDs",
        "combo_page_title": "Formation + Play Call Combos",
        "call_sheet_title": "Prospective Play Call Sheet",
        "lean_label": "Run/Pass lean",
        "sideline_left": "Best formation | play combos",
        "sideline_right": "Best play calls",
    },
    "Defense": {
        "table": "defense_plays_epa",
        "sheet_options": {
            "Front | Coverage": "def_call",
            "Front only": "def_front",
            "Coverage only": "coverage",
        },
        "combo_col": "def_call",
        "heatmap_rows": "def_front",
        "heatmap_cols": "coverage",
        "heatmap_title": "Front x Coverage — Avg EPA",
        "heatmap_x": "Coverage",
        "heatmap_y": "Front",
        "primary_group": "def_front",
        "secondary_group": "coverage",
        "primary_label": "Fronts",
        "secondary_label": "Coverages",
        "package_col": "def_front",
        "package_label": "Best front",
        "invert_xp": True,
        "points_metric": "Avg pts allowed",
        "actual_line": "Points allowed (aP)",
        "td_label": "TDs allowed",
        "combo_page_title": "Front + Coverage Combos",
        "call_sheet_title": "Prospective Defensive Call Sheet",
        "lean_label": "Opp run/pass",
        "sideline_left": "Best front | coverage",
        "sideline_right": "Best coverages",
    },
}

CHART_TEMPLATE = "plotly_white"
# Low value = red, high value = green (used when POSITIVE is good for the selected unit)
GREEN_SCALE = [[0.0, "#7f1d1d"], [0.5, "#9ca3af"], [1.0, "#15803d"]]
# Defense luck only: low/negative luck = green (held them below expectation)
DEFENSE_LUCK_SCALE = [[0.0, "#15803d"], [0.5, "#9ca3af"], [1.0, "#7f1d1d"]]


def epa_color_scale(unit_cfg: dict) -> list:
    """Offense and defense EPA: positive = good, so green = high values."""
    return GREEN_SCALE


def luck_color_scale(unit_cfg: dict) -> list:
    """Offense: positive luck good. Defense: negative luck good."""
    if unit_cfg["invert_xp"]:
        return DEFENSE_LUCK_SCALE
    return GREEN_SCALE


def show_defense_legend() -> None:
    st.info(
        "**Reading defense charts:** **Green / positive EPA = good stop** (INT, TFL, incomplete). "
        "**Red / negative EPA = bad** (gain, TD). We flip opponent EPA so higher is always better for your unit."
    )
CHART_LAYOUT = {
    "paper_bgcolor": "#FFFFFF",
    "plot_bgcolor": "#EEF2EF",
    "font": {"color": "#14201a", "size": 13},
    "title": {"font": {"color": "#14201a", "size": 16}},
    "xaxis": {
        "gridcolor": "#D5DED8",
        "linecolor": "#9AA89F",
        "tickfont": {"color": "#3d4f45"},
        "title_font": {"color": "#3d4f45"},
    },
    "yaxis": {
        "gridcolor": "#D5DED8",
        "linecolor": "#9AA89F",
        "tickfont": {"color": "#3d4f45"},
        "title_font": {"color": "#3d4f45"},
    },
    "legend": {"font": {"color": "#14201a"}, "bgcolor": "rgba(255,255,255,0.85)"},
}


def apply_chart_style(fig: go.Figure, title: str | None = None, height: int = 420) -> go.Figure:
    # Prefer explicit layout over plotly_white — that template can wash out custom trace colors
    fig.update_layout(
        **CHART_LAYOUT,
        template="simple_white",
        height=height,
        colorway=["#1B4332", "#C9A227", "#1D4ED8", "#B45309", "#0F766E"],
    )
    if title:
        fig.update_layout(title=title)
    return fig


def smooth_line_chart(
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    name: str,
    color: str,
    *,
    dash: str = "solid",
    width: float = 3.5,
    show_labels: bool = False,
    curved: bool = True,
) -> go.Scatter:
    line: dict = {
        "color": color,
        "width": width,
        "dash": dash,
    }
    if curved:
        line["shape"] = "spline"
        line["smoothing"] = 0.85
    else:
        line["shape"] = "linear"
    return go.Scatter(
        x=df[x_col],
        y=df[y_col],
        name=name,
        mode="lines+markers+text" if show_labels else "lines+markers",
        text=[f"{v:.0f}" for v in df[y_col]] if show_labels else None,
        textposition="top center",
        textfont={"size": 12, "color": color, "family": "Arial Black, Arial, sans-serif"},
        line=line,
        marker={
            "size": 12,
            "color": color,
            "line": {"width": 2, "color": color},
            "symbol": "circle",
        },
        hovertemplate=f"{name}: %{{y:.1f}}<extra></extra>",
    )


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
            background-color: #FFFFFF;
            color: #14201a;
        }
        [data-testid="stSidebar"] {
            background-color: #F4F7F5;
            border-right: 1px solid #D8E2DC;
        }
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] .stMarkdown {
            color: #1e3328 !important;
        }
        /* Sidebar primary buttons stay white-on-green */
        [data-testid="stSidebar"] button[kind="primary"],
        [data-testid="stSidebar"] button[kind="primary"] *,
        [data-testid="stSidebar"] button[data-testid*="primary"],
        [data-testid="stSidebar"] button[data-testid*="primary"] * {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        .block-container {
            padding-top: 0.75rem;
            color: #14201a;
        }
        /* Body copy only — do NOT paint every span (breaks green button labels) */
        h1, h2, h3, h4, .stMarkdown {
            color: #14201a !important;
        }
        /* Exclude .mb-board — dark green situation board needs light text */
        [data-testid="stMarkdownContainer"] p:not(.mb-board-sit):not(.mb-board-sub),
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stWidgetLabel"] p,
        [data-testid="stWidgetLabel"],
        label[data-testid="stWidgetLabel"] {
            color: #14201a !important;
        }
        [data-testid="stMarkdownContainer"] .mb-board,
        [data-testid="stMarkdownContainer"] .mb-board p,
        [data-testid="stMarkdownContainer"] .mb-board .mb-board-label {
            color: #F2F7F4 !important;
            -webkit-text-fill-color: #F2F7F4 !important;
        }
        [data-testid="stMarkdownContainer"] .mb-board .mb-board-label {
            color: #95D5B2 !important;
            -webkit-text-fill-color: #95D5B2 !important;
        }
        [data-testid="stMarkdownContainer"] .mb-board p.mb-board-sit {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        [data-testid="stMarkdownContainer"] .mb-board p.mb-board-sub {
            color: #C5D5CC !important;
            -webkit-text-fill-color: #C5D5CC !important;
        }
        div[data-testid="stMetric"] {
            background: #F4F7F5;
            border: 1px solid #D8E2DC;
            border-radius: 10px;
            padding: 0.5rem 0.75rem;
        }
        div[data-testid="stMetric"] label {
            color: #5c6b62 !important;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #14201a !important;
            font-size: 1.6rem !important;
            font-weight: 700 !important;
        }
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
            color: #3d4f45 !important;
        }
        [data-testid="stDataFrame"] {
            background: #F4F7F5;
            border: 1px solid #D8E2DC;
            border-radius: 8px;
        }
        [data-testid="stDataFrame"] div {
            color: #14201a !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            background-color: #F4F7F5;
            border-radius: 8px;
            padding: 4px;
        }
        .stTabs [data-baseweb="tab"] {
            color: #5c6b62 !important;
        }
        .stTabs [aria-selected="true"],
        .stTabs [aria-selected="true"] * {
            background-color: #1B4332 !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
        }
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] {
            background-color: #F4F7F5 !important;
            color: #14201a !important;
            border-color: #D0DAD4 !important;
        }
        .stAlert {
            background-color: #F4F7F5;
            color: #1e3328;
            border: 1px solid #D8E2DC;
        }
        /* Live Assistant */
        .live-title {
            font-size: 1.35rem !important;
            font-weight: 800 !important;
            margin: 0 0 0.15rem 0 !important;
            line-height: 1.2 !important;
        }
        .live-situation {
            font-size: 1.05rem !important;
            color: #1B4332 !important;
            font-weight: 700 !important;
            margin: 0.2rem 0 0.35rem 0 !important;
        }
        .gc-spot {
            background: #F4F7F5;
            border: 1px solid #D8E2DC;
            border-radius: 10px;
            padding: 0.55rem 0.4rem;
            text-align: center;
            font-weight: 900;
            font-size: 1.05rem;
            color: #C2410C !important;
            margin-top: 1.35rem;
        }
        .gc-plays {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin: 0.25rem 0 0.45rem 0;
        }
        .gc-play {
            display: inline-block;
            border-radius: 999px;
            padding: 0.28rem 0.7rem;
            font-size: 0.88rem;
            font-weight: 800;
            border: 1px solid #D8E2DC;
            background: #F4F7F5;
            color: #1e3328 !important;
        }
        .gc-play.up {
            border-color: #52B788;
            background: #E8F5E9;
            color: #1B4332 !important;
        }
        .gc-play.down {
            border-color: #E76F51;
            background: #FDECEA;
            color: #B91C1C !important;
        }
        .gc-ballto {
            background: #F4F7F5;
            border: 1px solid #F4A261;
            border-radius: 8px;
            padding: 0.35rem 0.65rem;
            margin: 0.25rem 0 0.35rem 0;
            color: #1e3328 !important;
            font-size: 0.92rem;
        }
        .gc-ballto b { color: #C2410C !important; }
        .live-card {
            background: #F4F7F5;
            border: 1px solid #D8E2DC;
            border-radius: 12px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.6rem;
        }
        .live-rank {
            font-size: 1.6rem;
            font-weight: 800;
            color: #52B788;
        }
        .live-call {
            font-size: 1.35rem;
            font-weight: 700;
            color: #14201a;
        }
        .live-meta {
            font-size: 1rem;
            color: #5c6b62;
        }
        .live-good { color: #1B4332 !important; font-weight: 700; }
        .live-bad { color: #dc2626 !important; font-weight: 700; }
        .live-spot {
            background: #F4F7F5;
            border: 1px solid #D8E2DC;
            border-radius: 12px;
            padding: 0.85rem 1rem;
            margin-bottom: 0.75rem;
        }
        .live-spot-label {
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: #5c6b62;
            margin-bottom: 0.35rem;
        }
        .live-spot-value {
            font-size: 1.2rem;
            font-weight: 700;
            color: #14201a;
            line-height: 1.35;
        }
        .live-spot-meta {
            font-size: 0.95rem;
            color: #5c6b62;
            margin-top: 0.25rem;
        }
        .live-spot-accent {
            border-color: #1B4332;
        }
        /* Madden-style depth chart (compact) */
        .dc-field {
            background:
              repeating-linear-gradient(
                90deg,
                rgba(255,255,255,0.04) 0px,
                rgba(255,255,255,0.04) 1px,
                transparent 1px,
                transparent 48px
              ),
              linear-gradient(180deg, #1a7a3a 0%, #14632e 40%, #0b3d1c 100%);
            border: 2px solid #f8fafc;
            border-radius: 12px;
            padding: 0.55rem 0.5rem 0.65rem;
            margin: 0.25rem 0 0.5rem 0;
            box-shadow: 0 6px 16px rgba(0,0,0,0.28), inset 0 0 40px rgba(0,0,0,0.18);
        }
        .dc-header {
            color: #f8fafc;
            font-weight: 900;
            font-size: 0.88rem;
            margin-bottom: 0.4rem;
            text-align: center;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            text-shadow: 0 2px 4px rgba(0,0,0,0.4);
        }
        .dc-pos-col {
            background: rgba(0,0,0,0.28);
            border: 1px solid rgba(255,255,255,0.2);
            border-radius: 8px;
            padding: 0.25rem 0.2rem 0.3rem;
            min-height: 0;
            text-align: center;
        }
        .dc-pos-label {
            color: #B7E4C7;
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            text-align: center;
            margin-bottom: 0.15rem;
            padding-bottom: 0.1rem;
            border-bottom: 1px solid rgba(183,228,199,0.35);
        }
        .dc-active {
            color: #f8fafc;
            font-weight: 800;
            font-size: 0.88rem;
            background: #FFFFFF;
            border: 1px solid #74C69D;
            border-radius: 6px;
            padding: 0.2rem 0.25rem;
            margin-bottom: 0.15rem;
            box-shadow: none;
            word-break: break-word;
            line-height: 1.15;
        }
        .dc-empty {
            color: rgba(226,232,240,0.55);
            font-weight: 700;
            font-size: 0.88rem;
            border: 1px dashed rgba(255,255,255,0.25);
            border-radius: 6px;
            padding: 0.2rem 0.25rem;
            margin-bottom: 0.15rem;
        }
        .dc-yardline {
            border-top: 1px solid rgba(255,255,255,0.28);
            margin: 0.25rem 0;
        }
        .dc-chip {
            display: inline-block;
            background: #F4F7F5;
            border: 1px solid #8A9A8E;
            color: #f8fafc;
            border-radius: 999px;
            padding: 0.2rem 0.5rem;
            margin: 0.1rem 0.15rem 0.1rem 0;
            font-weight: 700;
            font-size: 0.85rem;
        }
        .dc-chip-on {
            border-color: #1B4332;
            box-shadow: 0 0 8px rgba(116,198,157,0.35);
            background: #FFFFFF;
        }
        .dc-chip-pos {
            color: #B7E4C7;
            font-size: 0.75rem;
            font-weight: 800;
            margin-left: 0.25rem;
        }
        /* Readable selectboxes + open menus (Live Track / formation) */
        div[data-testid="stSelectbox"] label,
        div[data-testid="stSelectbox"] p {
            font-size: 0.95rem !important;
        }
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            min-height: 2.35rem;
            font-size: 0.95rem !important;
            padding-top: 0.2rem;
            padding-bottom: 0.2rem;
        }
        div[data-testid="stSelectbox"] span,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] * {
            font-size: 0.95rem !important;
            line-height: 1.25 !important;
        }
        ul[role="listbox"] {
            max-height: 18rem !important;
        }
        ul[role="listbox"] li,
        div[role="listbox"] li,
        li[role="option"] {
            font-size: 1rem !important;
            min-height: 2.1rem !important;
            padding-top: 0.3rem !important;
            padding-bottom: 0.3rem !important;
            line-height: 1.25 !important;
        }
        div[data-testid="stNumberInput"] input,
        div[data-testid="stTextInput"] input {
            font-size: 0.95rem !important;
            min-height: 2.25rem;
        }
        div[data-testid="stRadio"] label {
            font-size: 0.95rem !important;
        }
        div[data-testid="stButton"] > button {
            min-height: 2.25rem;
            font-size: 0.95rem;
            font-weight: 700;
            border-radius: 8px;
        }
        /* Quick Log — pace banners */
        .ql-banner {
            background: #E8F5E9;
            border: 1px solid #2D6A4F;
            border-radius: 12px;
            padding: 0.65rem 0.85rem;
            margin: 0.35rem 0 0.75rem 0;
            color: #14201a !important;
            font-weight: 600;
        }
        .ql-banner.warn {
            background: #FFF8E7;
            border-color: #f59e0b;
            color: #3d4f45 !important;
        }
        .ql-drive {
            background: #F4F7F5;
            border: 1px solid #D8E2DC;
            border-radius: 8px;
            padding: 0.3rem 0.55rem;
            margin: 0.1rem 0 0.25rem 0;
            color: #3d4f45 !important;
            font-weight: 700;
            font-size: 0.92rem;
        }
        .ql-drive.open { border-color: #40916C; }
        .ql-sticky {
            background: #FFFFFF;
            border: 1px solid #74C69D;
            border-radius: 8px;
            padding: 0.3rem 0.55rem;
            margin: 0.2rem 0 0.35rem 0;
            color: #3d4f45 !important;
            font-weight: 800;
            font-size: 1rem;
        }
        /* Tablet / iPad — tappable but not oversized */
        .ql-tablet div[data-testid="stButton"] > button {
            min-height: 2.55rem !important;
            font-size: 1rem !important;
            border-radius: 10px !important;
        }
        .ql-tablet div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            min-height: 2.45rem !important;
            font-size: 1rem !important;
        }
        .ql-tablet div[data-testid="stNumberInput"] input,
        .ql-tablet div[data-testid="stTextInput"] input {
            min-height: 2.45rem !important;
            font-size: 1rem !important;
        }
        .ql-tablet .block-container {
            padding-left: 0.75rem;
            padding-right: 0.75rem;
            max-width: 920px;
        }
        @media (pointer: coarse) {
            div[data-testid="stButton"] > button {
                min-height: 2.55rem !important;
                font-size: 1rem !important;
            }
        }
        /* Halftime report — light cards, high contrast */
        .ht-wrap { margin: 0.25rem 0 1rem 0; }
        .ht-title {
            font-size: 1.4rem;
            font-weight: 900;
            letter-spacing: 0.04em;
            margin: 0 0 0.75rem 0;
            color: #14201a !important;
        }
        .ht-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.6rem;
            margin-bottom: 1rem;
        }
        .ht-stat {
            background: #F4F7F5;
            color: #14201a !important;
            border: 1px solid #D8E2DC;
            border-radius: 12px;
            padding: 0.75rem 0.85rem;
            text-align: center;
        }
        .ht-stat .n {
            font-size: 1.7rem;
            font-weight: 900;
            line-height: 1.1;
            color: #1B4332 !important;
        }
        .ht-stat .l {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #5c6b62 !important;
            margin-top: 0.2rem;
        }
        .ht-sec {
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #1B4332 !important;
            margin: 0.65rem 0 0.35rem 0;
        }
        .ht-blurb {
            font-size: 0.95rem;
            color: #3d4f45 !important;
            margin: 0 0 0.6rem 0;
            line-height: 1.35;
        }
        .ht-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin-bottom: 0.35rem;
        }
        .ht-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            background: #FFFFFF;
            border: 1px solid #D0DAD4;
            border-radius: 999px;
            padding: 0.25rem 0.65rem;
            font-size: 0.85rem;
            font-weight: 700;
            color: #14201a !important;
        }
        .ht-chip.up { border-color: #2D6A4F; color: #1B4332 !important; }
        .ht-chip.down { border-color: #ef4444; color: #b91c1c !important; }
        .ht-chip .n { color: #5c6b62 !important; font-weight: 600; font-size: 0.78rem; }
        .ht-col-title {
            font-size: 1rem;
            font-weight: 800;
            margin-bottom: 0.45rem;
            color: #1e3328 !important;
        }
        .ht-card {
            border-radius: 10px;
            padding: 0.6rem 0.75rem;
            margin-bottom: 0.45rem;
            border: 1px solid #D0DAD4;
            background: #FFFFFF;
            color: #14201a !important;
        }
        .ht-card .tag {
            display: inline-block;
            font-size: 0.7rem;
            font-weight: 900;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            padding: 0.14rem 0.45rem;
            border-radius: 999px;
            margin-right: 0.4rem;
            color: #ffffff !important;
        }
        .ht-card .call {
            font-weight: 800;
            font-size: 1.05rem;
            color: #14201a !important;
        }
        .ht-card .meta {
            font-size: 0.88rem;
            color: #5c6b62 !important;
            margin-top: 0.2rem;
        }
        .ht-kill { background: #FDECEA; border-color: #ef4444; }
        .ht-kill .tag { background: #dc2626; color: #fff !important; }
        .ht-lean { background: #E8F5E9; border-color: #2D6A4F; }
        .ht-lean .tag { background: #E8F5E9; color: #fff !important; }
        .ht-test { background: #FFF8E7; border-color: #f59e0b; }
        .ht-test .tag { background: #d97706; color: #fff !important; }
        .ht-hot { background: #FFFFFF; border-color: #2D6A4F; }
        .ht-hot .tag { background: #E8F5E9; color: #fff !important; }
        .ht-cold { background: #F4F7F5; border-color: #5c6b62; }
        .ht-cold .tag { background: #6b7280; color: #fff !important; }
        .ht-pin {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            padding: 0.5rem 0.7rem;
            border-radius: 10px;
            background: #FFFFFF;
            border: 1px solid #D0DAD4;
            margin-bottom: 0.4rem;
            color: #14201a !important;
        }
        .ht-pin .name { font-weight: 700; font-size: 0.98rem; color: #14201a !important; }
        .ht-badge {
            font-size: 0.72rem;
            font-weight: 900;
            letter-spacing: 0.05em;
            padding: 0.2rem 0.5rem;
            border-radius: 999px;
            white-space: nowrap;
            color: #ffffff !important;
        }
        .ht-badge-confirmed { background: #E8F5E9; color: #fff !important; }
        .ht-badge-kill { background: #dc2626; color: #fff !important; }
        .ht-badge-unproven { background: #6b7280; color: #fff !important; }
        .ht-player {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 0.4rem 0.55rem;
            border-bottom: 1px solid #E2E8E4;
            font-size: 0.98rem;
            color: #1e3328 !important;
            background: #FFFFFF;
        }
        .ht-player small { color: #5c6b62 !important; }
        .ht-player .pm-up { color: #1B4332 !important; font-weight: 800; }
        .ht-player .pm-down { color: #dc2626 !important; font-weight: 800; }
        /* Keep expanders / plotly readable (no white-on-white) */
        [data-testid="stExpander"] {
            background-color: #F4F7F5 !important;
            border: 1px solid #D8E2DC !important;
            border-radius: 10px;
        }
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] p,
        [data-testid="stExpander"] span,
        [data-testid="stExpander"] label {
            color: #14201a !important;
        }
        .stPlotlyChart, .js-plotly-plot, .plot-container {
            background-color: #EEF2EF !important;
            color: #14201a !important;
        }
        /* Never force color onto Plotly SVG children — stroke uses currentColor when remapped */
        .js-plotly-plot .legendtext {
            fill: #14201a !important;
        }
        div[data-testid="stCaptionContainer"] p,
        div[data-testid="stCaptionContainer"] span {
            color: #5c6b62 !important;
        }

        /* School primary / green buttons — white label (beat global span color rules) */
        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stButton"] > button[kind="primary"] *,
        div[data-testid="stButton"] > button[data-testid="baseButton-primary"],
        div[data-testid="stButton"] > button[data-testid="baseButton-primary"] *,
        button[data-testid="baseButton-primary"],
        button[data-testid="baseButton-primary"] *,
        div[data-testid="stForm"] button[data-testid="baseButton-primaryFormSubmit"],
        div[data-testid="stForm"] button[data-testid="baseButton-primaryFormSubmit"] *,
        div[data-testid="stForm"] div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stForm"] div[data-testid="stButton"] > button[kind="primary"] * {
            background-color: #1B4332 !important;
            border-color: #2D6A4F !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        div[data-testid="stButton"] > button[kind="primary"]:hover,
        div[data-testid="stButton"] > button[kind="primary"]:hover *,
        div[data-testid="stButton"] > button[data-testid="baseButton-primary"]:hover,
        div[data-testid="stButton"] > button[data-testid="baseButton-primary"]:hover *,
        button[data-testid="baseButton-primary"]:hover,
        button[data-testid="baseButton-primary"]:hover * {
            background-color: #2D6A4F !important;
            border-color: #40916C !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }

        /* FINAL OVERRIDE — white text on every green / primary control (Streamlit 1.3x–1.6x testids) */
        button[kind="primary"],
        button[kind="primary"] *,
        button[data-testid*="primary"],
        button[data-testid*="primary"] *,
        button[data-testid*="Primary"],
        button[data-testid*="Primary"] *,
        [data-testid="stDownloadButton"] button,
        [data-testid="stDownloadButton"] button *,
        [data-testid="stFormSubmitButton"] button,
        [data-testid="stFormSubmitButton"] button *,
        [data-testid="stPopover"] button[kind="primary"],
        [data-testid="stPopover"] button[kind="primary"] *,
        div[data-testid="stButton"] button[kind="primary"],
        div[data-testid="stButton"] button[kind="primary"] p,
        div[data-testid="stButton"] button[kind="primary"] span,
        div[data-testid="stButton"] button[kind="primary"] div,
        div[data-testid="stButton"] button[data-testid*="primary"],
        div[data-testid="stButton"] button[data-testid*="primary"] p,
        div[data-testid="stButton"] button[data-testid*="primary"] span,
        div[data-testid="stButton"] button[data-testid*="primary"] div {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
            fill: #FFFFFF !important;
        }
        /* Compact Database roster */
        [data-testid="stDataFrame"] td,
        [data-testid="stDataFrame"] th,
        [data-testid="stDataEditor"] td,
        [data-testid="stDataEditor"] th {
            padding-top: 0.15rem !important;
            padding-bottom: 0.15rem !important;
            line-height: 1.2 !important;
        }
        div[data-testid="stExpander"] summary {
            padding: 0.35rem 0.5rem !important;
        }
        div[data-testid="stForm"] {
            border: 1px solid #D8E2DC !important;
            background: #F4F7F5 !important;
            padding: 0.55rem 0.75rem !important;
            border-radius: 10px;
        }
        @media (max-width: 900px) {
            .ht-strip { grid-template-columns: 1fr 1fr; }
        }

        /* LAST RULE IN FILE — white on green must win over earlier span/label colors */
        button[kind="primary"],
        button[kind="primary"] *,
        button[data-testid*="primary"],
        button[data-testid*="primary"] *,
        button[data-testid*="Primary"],
        button[data-testid*="Primary"] *,
        [data-testid="stDownloadButton"] button,
        [data-testid="stDownloadButton"] button *,
        [data-testid="stFormSubmitButton"] button,
        [data-testid="stFormSubmitButton"] button *,
        [data-testid="baseButton-primary"],
        [data-testid="baseButton-primary"] *,
        [data-testid="baseButton-primaryFormSubmit"],
        [data-testid="baseButton-primaryFormSubmit"] *,
        .stTabs [aria-selected="true"],
        .stTabs [aria-selected="true"] * {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        /* Dark situation board — light text (overrides markdown p dark) */
        .mb-board,
        .mb-board *,
        [data-testid="stMarkdownContainer"] .mb-board,
        [data-testid="stMarkdownContainer"] .mb-board * {
            color: #F2F7F4 !important;
            -webkit-text-fill-color: #F2F7F4 !important;
        }
        .mb-board-label,
        [data-testid="stMarkdownContainer"] .mb-board-label {
            color: #95D5B2 !important;
            -webkit-text-fill-color: #95D5B2 !important;
        }
        p.mb-board-sit,
        .mb-board-sit,
        [data-testid="stMarkdownContainer"] p.mb-board-sit {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        p.mb-board-sub,
        .mb-board-sub,
        [data-testid="stMarkdownContainer"] p.mb-board-sub {
            color: #C5D5CC !important;
            -webkit-text-fill-color: #C5D5CC !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _is_current_season_mask(season: pd.Series) -> pd.Series:
    """True for current-season rows (or legacy rows with no season column value).

    Not cached — `current` aliases change with team_config / season rollover.
    """
    return season.map(_season_api().is_current_season_value)


def _season_api():
    """team_config with season helpers (reload if Streamlit held a stale module)."""
    import importlib

    import team_config as tc

    needed = (
        "is_current_season_value",
        "current_season_label",
        "current_season_id",
        "set_current_season",
    )
    if any(not hasattr(tc, name) for name in needed):
        tc = importlib.reload(tc)
    return tc


def current_season_plays(df: pd.DataFrame) -> pd.DataFrame:
    """Game Review / formation boards: current season only."""
    if df is None or df.empty or "season" not in df.columns:
        return df
    return df[_is_current_season_mask(df["season"])].copy()


def prior_season_plays(df: pd.DataFrame) -> pd.DataFrame:
    """Rows stamped as a prior season (not current)."""
    if df is None or df.empty or "season" not in df.columns:
        return pd.DataFrame()
    return df[~_is_current_season_mask(df["season"])].copy()


@st.cache_data(show_spinner=False)
def _load_plays_cached(unit: str, mtime: float, size: int) -> pd.DataFrame:
    """Cached season table; mtime/size bust cache when football.db changes."""
    table = UNITS[unit]["table"]
    with sqlite3.connect(DB_FILE) as conn:
        try:
            df = pd.read_sql(f"SELECT * FROM {table}", conn)
        except Exception:
            return pd.DataFrame()
    if "formation_play" not in df.columns and "formation" in df.columns:
        df["formation_play"] = (
            df["formation"].fillna("Unknown").astype(str)
            + "  |  "
            + df["play_call"].fillna("Unknown").astype(str)
        )
    if "def_call" not in df.columns:
        df["def_call"] = (
            df["def_front"].fillna("Unknown").astype(str)
            + "  |  "
            + df["coverage"].fillna("Unknown").astype(str)
        )
    if "points_scored" not in df.columns:
        df["points_scored"] = df["is_touchdown"].fillna(0).astype(int) * 6
    if "is_success" not in df.columns:
        from step3_epa import add_success_flags

        invert = bool(UNITS[unit].get("invert_xp"))
        df = add_success_flags(df, invert=invert)
    if "season" in df.columns:
        prior = ~_is_current_season_mask(df["season"])
        if "form_tagged" in df.columns:
            df.loc[prior, "form_tagged"] = 0
        if "tags_ok" in df.columns:
            df.loc[prior, "tags_ok"] = 0
    return df


def load_plays(unit: str) -> pd.DataFrame:
    if not DB_FILE.exists():
        return pd.DataFrame()
    try:
        st_info = DB_FILE.stat()
        return _load_plays_cached(unit, st_info.st_mtime, st_info.st_size).copy()
    except Exception:
        return pd.DataFrame()


def avg_epa_table(
    df: pd.DataFrame,
    group_col: str,
    min_plays: int,
    exclude_unknown: bool = True,
    require_tags: bool | None = None,
) -> pd.DataFrame:
    valid = df[df[group_col].notna() & (df[group_col] != "")]
    if exclude_unknown:
        valid = valid[~valid[group_col].astype(str).str.contains("Unknown", na=False)]
    # Prior-year Hudl: formations untrusted; tagged play calls OK; EPA uses all snaps elsewhere
    if require_tags is None:
        require_tags = group_col in {"formation", "play_call", "formation_play", "def_call"}
    if require_tags:
        # Formations / combos: current season only
        if group_col in {"formation", "formation_play"} and "season" in valid.columns:
            valid = valid[_is_current_season_mask(valid["season"])]
        if group_col == "formation" and "form_tagged" in valid.columns:
            valid = valid[valid["form_tagged"].fillna(0).astype(int) == 1]
        elif group_col == "play_call" and "play_tagged" in valid.columns:
            valid = valid[valid["play_tagged"].fillna(0).astype(int) == 1]
        elif group_col in {"formation_play", "def_call"} and "tags_ok" in valid.columns:
            valid = valid[valid["tags_ok"].fillna(0).astype(int) == 1]
        elif "tags_ok" in valid.columns and group_col != "play_call":
            valid = valid[valid["tags_ok"].fillna(0).astype(int) == 1]
    if valid.empty:
        return pd.DataFrame()

    aggs: dict = {
        "plays": ("epa", "count"),
        "avg_epa": ("epa", "mean"),
        "total_epa": ("epa", "sum"),
    }
    if "is_success" in valid.columns:
        aggs["successes"] = ("is_success", "sum")
        aggs["success_n"] = ("is_success", "count")

    table = (
        valid.groupby(group_col)
        .agg(**aggs)
        .query("plays >= @min_plays")
        .sort_values("avg_epa", ascending=False)
        .reset_index()
    )
    table["avg_epa"] = table["avg_epa"].round(3)
    table["total_epa"] = table["total_epa"].round(1)
    if "success_n" in table.columns:
        table["success_rate"] = (
            (table["successes"] / table["success_n"].replace(0, np.nan))
            .fillna(0.0)
            .round(3)
        )
    else:
        table["success_rate"] = np.nan
    return table


def filter_situation(
    df: pd.DataFrame,
    down: int | None,
    distance_bucket: str | None,
    field_zone: str | None,
) -> pd.DataFrame:
    out = df.copy()
    if down is not None:
        out = out[out["down"] == down]
    if distance_bucket and distance_bucket != "Any":
        out = out[out["distance_bucket"] == distance_bucket.lower()]
    if field_zone and field_zone != "Any":
        out = out[out["field_zone"] == field_zone.lower()]
    return out


DISTANCE_LABELS = {"short": "Short (1-3)", "medium": "Medium (4-6)", "long": "Long (7+)"}
ZONE_LABELS = {
    "backed_up": "Backed up (Own 1-20)",
    "own_territory": "Own territory (21-40)",
    "midfield": "Midfield (41-50)",
    "opp_territory": "Opp territory (49-21)",
    "red_zone": "Red zone (20-GL)",
}
DOWN_LABELS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}

# Representative ball spot (yards from own goal line) when only a zone is known
ZONE_DEFAULT_BALL_YARD = {
    "backed_up": 10,
    "own_territory": 30,
    "midfield": 45,
    "opp_territory": 65,  # Opp 35
    "red_zone": 90,  # Opp 10
}


def ball_yard_to_zone(ball_yard: int | float | None) -> str:
    """Map yards from own goal (1–99) → field zone bucket."""
    try:
        y = int(ball_yard)
    except (TypeError, ValueError):
        return "midfield"
    y = max(1, min(99, y))
    if y <= 20:
        return "backed_up"
    if y <= 40:
        return "own_territory"
    if y <= 50:
        return "midfield"
    if y <= 79:  # Opp 49 … Opp 21
        return "opp_territory"
    return "red_zone"


def zone_default_ball_yard(field_zone: str | None) -> int:
    return int(ZONE_DEFAULT_BALL_YARD.get(str(field_zone or "midfield"), 45))


def format_ball_spot(ball_yard: int | float | None) -> str:
    """Own 35 / Opp 25 style label."""
    try:
        y = int(ball_yard)
    except (TypeError, ValueError):
        return "—"
    y = max(1, min(99, y))
    if y <= 50:
        return f"Own {y}"
    return f"Opp {100 - y}"


def side_yard_to_ball_yard(side: str, yard: int) -> int:
    """own/opp yard line → yards from own goal (1–99)."""
    yd = max(1, min(50, int(yard)))
    if str(side or "").lower().startswith("own"):
        return yd
    return 100 - yd


def yards_from_ball_span(
    start_ball: int | float | None,
    end_ball: int | float | None,
) -> int | None:
    """Gain = end − start in own-goal coords (Own 25 → Opp 25 = +50)."""
    try:
        if start_ball is None or end_ball is None:
            return None
        return int(end_ball) - int(start_ball)
    except (TypeError, ValueError):
        return None


def advance_ball_yard(
    ball_yard: int | float | None,
    yards_gained: int | float,
    field_zone: str | None = None,
) -> int:
    """Move the ball; clamp on the field (1–99)."""
    try:
        start = int(ball_yard) if ball_yard is not None else zone_default_ball_yard(field_zone)
    except (TypeError, ValueError):
        start = zone_default_ball_yard(field_zone)
    try:
        yds = int(yards_gained)
    except (TypeError, ValueError):
        yds = 0
    return int(max(1, min(99, start + yds)))


def _gamecast_recent_plays(
    live_logs: pd.DataFrame | None,
    opponent: str,
    *,
    limit: int = 8,
    drive_id: int | None = None,
    half: int | None = None,
) -> list[dict]:
    """Offense snaps with start/end spot + estimated EPA for GameCast / drive map."""
    from mesh_engine import (
        _estimate_live_play_epa,
        _load_ep_table_from_season,
        filter_live_logs,
    )

    if live_logs is None or getattr(live_logs, "empty", True):
        return []
    logs = filter_live_logs(live_logs, opponent=opponent, half=half)
    if logs.empty:
        return []
    if "unit" in logs.columns:
        logs = logs[logs["unit"].astype(str).str.lower() == "offense"]
    if logs.empty:
        return []
    if drive_id is not None and "drive_id" in logs.columns:
        did = int(drive_id)
        logs = logs[pd.to_numeric(logs["drive_id"], errors="coerce") == did]
        if logs.empty:
            return []
    ep_table = _load_ep_table_from_season()
    if drive_id is None and limit:
        logs = logs.tail(int(limit))
    rows: list[dict] = []
    for _, r in logs.iterrows():
        try:
            start = int(r.get("ball_yard"))
        except (TypeError, ValueError):
            start = zone_default_ball_yard(r.get("field_zone"))
        start = max(1, min(99, start))
        try:
            yds = int(r.get("yards_gained") or 0)
        except (TypeError, ValueError):
            yds = 0
        end = advance_ball_yard(start, yds)
        epa = float(_estimate_live_play_epa(r, ep_table))
        call = str(r.get("play_call") or r.get("call") or "—").strip() or "—"
        result = str(r.get("result") or "").strip()
        play_n = r.get("play_n")
        try:
            pn = int(play_n) if play_n is not None and str(play_n).strip() != "" else None
        except (TypeError, ValueError):
            pn = None
        label = f"{call} · {yds:+d} · EPA {epa:+.2f}"
        if pn is not None:
            label = f"#{pn} {label}"
        rows.append(
            {
                "start": start,
                "end": end,
                "yards": yds,
                "epa": round(epa, 2),
                "call": call,
                "result": result,
                "play_n": pn,
                "label": label,
            }
        )
    return rows


def _render_halftime_drive_map(
    opponent: str,
    live_logs: pd.DataFrame | None,
    *,
    key_prefix: str = "ht",
) -> None:
    """Read-only GameCast: pick a 1st-half drive and review field arrows."""
    from mesh_engine import filter_live_logs

    st.caption("Field map of each drive — review at halftime, not during live snaps.")
    if live_logs is None or getattr(live_logs, "empty", True):
        st.info("No live snaps yet.")
        return

    half1 = filter_live_logs(live_logs, opponent=opponent, half=1)
    scope = half1 if not half1.empty else filter_live_logs(live_logs, opponent=opponent)
    if scope.empty:
        st.info("No snaps for this opponent yet.")
        return

    drive_ids = known_drive_ids(scope)
    if not drive_ids and "drive_id" in scope.columns:
        for v in scope["drive_id"].dropna().unique():
            try:
                drive_ids.append(int(v))
            except (TypeError, ValueError):
                pass
        drive_ids = sorted(set(drive_ids))
    if not drive_ids:
        st.info("No drive #s on the log yet — Start drive on Live Track next game.")
        return

    pick = st.selectbox(
        "Drive #",
        drive_ids,
        index=len(drive_ids) - 1,
        key=f"{key_prefix}_gc_drive",
        format_func=lambda d: f"Drive #{d}",
    )
    plays = _gamecast_recent_plays(
        scope,
        opponent,
        drive_id=int(pick),
        half=None,
        limit=0,
    )
    if not plays:
        st.caption(f"No offense snaps on drive #{pick}.")
        return

    ball = int(plays[-1].get("end") or plays[-1].get("start") or 45)
    fig = _build_gamecast_figure(ball, plays, players=None, selected_player="")
    st.plotly_chart(
        fig,
        width="stretch",
        key=f"{key_prefix}_gc_chart_{pick}",
        theme=None,
        config={
            "displayModeBar": False,
            "scrollZoom": False,
            "staticPlot": True,
        },
    )
    rows = [
        {
            "#": p.get("play_n") or i + 1,
            "Call": p.get("call") or "—",
            "Result": p.get("result") or "—",
            "Yds": p.get("yards"),
            "EPA": p.get("epa"),
            "From": format_ball_spot(int(p.get("start") or 45)),
            "To": format_ball_spot(int(p.get("end") or 45)),
        }
        for i, p in enumerate(plays)
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


FORMATION_LAYOUTS_FILE = PROJECT_DIR / "data" / "formation_layouts.json"
FIELD_WIDTH_YDS = 53.3
FIELD_CENTER_Y = FIELD_WIDTH_YDS / 2.0


def _default_formation_layout_slots() -> dict[str, dict[str, float]]:
    return {
        "LT": {"dx": 0, "dy": -6},
        "LG": {"dx": 0, "dy": -3},
        "C": {"dx": 0, "dy": 0},
        "RG": {"dx": 0, "dy": 3},
        "RT": {"dx": 0, "dy": 6},
        "QB": {"dx": -5, "dy": 0},
        "RB": {"dx": -7, "dy": 3},
        "TE": {"dx": 0, "dy": 10},
        "WR1": {"dx": 0, "dy": -20},
        "WR2": {"dx": 1, "dy": -13},
        "WR3": {"dx": 0, "dy": 20},
        "WR4": {"dx": 2, "dy": -16},
        "WR5": {"dx": 2, "dy": 16},
        "RB2": {"dx": -7, "dy": -3},
        "TE2": {"dx": 0, "dy": -10},
    }


def load_formation_layouts() -> dict:
    """Load editable formation diagrams for GameCast (data/formation_layouts.json)."""
    empty = {
        "default": "Base",
        "layouts": {
            "Base": {"label": "Base / Shotgun", "slots": _default_formation_layout_slots()}
        },
        "aliases": {},
    }
    if not FORMATION_LAYOUTS_FILE.exists():
        return empty
    try:
        import json

        raw = json.loads(FORMATION_LAYOUTS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return empty
        layouts = raw.get("layouts") or {}
        if not isinstance(layouts, dict) or not layouts:
            return empty
        return {
            "default": str(raw.get("default") or "Base"),
            "layouts": layouts,
            "aliases": raw.get("aliases") if isinstance(raw.get("aliases"), dict) else {},
        }
    except Exception:
        return empty


def resolve_formation_layout_name(formation: str = "", variant: str = "") -> str:
    """Map a called formation (Slot Dip / Fox RT…) → layout key."""
    data = load_formation_layouts()
    layouts = data.get("layouts") or {}

    # Prefer scheme book (East/West compass, Dip/Trig/Fox, etc.)
    try:
        from formation_logic import formation_layout_key

        keyed = formation_layout_key(formation, variant)
        if keyed in layouts:
            return keyed
    except Exception:
        pass

    aliases = {str(k).lower(): str(v) for k, v in (data.get("aliases") or {}).items()}
    form = _ql_norm(formation) if formation else ""
    if form.lower() in {k.lower() for k in layouts}:
        for k in layouts:
            if k.lower() == form.lower():
                return k
    if form.lower() in aliases:
        hit = aliases[form.lower()]
        if hit in layouts:
            return hit
    # Prefix match: "Slot Dip Bash" → alias "slot dip"
    low = form.lower()
    for alias, hit in sorted(aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
        if low.startswith(alias) and hit in layouts:
            return hit
    default = str(data.get("default") or "Base")
    return default if default in layouts else next(iter(layouts), "Base")


def _is_ol_slot(slot_id: str) -> bool:
    sid = str(slot_id or "").strip().upper()
    if sid in OL_SLOT_IDS or sid.startswith("OL"):
        return True
    spec = _slot_by_id(slot_id)
    if not spec:
        return False
    return str(spec.get("log_pos") or "").upper() in OL_LOG_POSITIONS


def _is_ol_log_pos(pos: str) -> bool:
    return str(pos or "").strip().upper() in OL_LOG_POSITIONS


def _formation_players_on_field(
    ball_yard: int,
    formation: str = "",
    variant: str = "",
) -> list[dict]:
    """
    Place on-field lineup using a formation layout relative to the LOS.

    Each row: slot, name, x (yard), y (lateral), label.
    OL slots are omitted (still saved / graded off GameCast).
    """
    try:
        slots = get_formation_slots()
    except Exception:
        slots = {}
    if not slots:
        return []
    data = load_formation_layouts()
    layout_name = resolve_formation_layout_name(formation, variant)
    layout = (data.get("layouts") or {}).get(layout_name) or {}
    coords = layout.get("slots") or _default_formation_layout_slots()
    los = max(1, min(99, int(ball_yard)))
    out: list[dict] = []
    for slot_id, name in slots.items():
        name = str(name or "").strip()
        if not name:
            continue
        # Defense slots skip for now (offense GameCast)
        if str(slot_id).upper().startswith(("DL", "LB", "DB")):
            continue
        # Hide OL on GameCast — clutter; grades still come from logged lineup
        if _is_ol_slot(slot_id):
            continue
        pos = coords.get(slot_id) or coords.get(str(slot_id).upper())
        if not pos:
            continue
        try:
            dx = float(pos.get("dx", 0))
            dy = float(pos.get("dy", 0))
        except (TypeError, ValueError):
            continue
        x = max(1.0, min(99.0, los + dx))
        y = max(1.0, min(FIELD_WIDTH_YDS - 1.0, FIELD_CENTER_Y + dy))
        short = name.split()[-1] if name else slot_id
        out.append(
            {
                "slot": str(slot_id),
                "name": name,
                "x": x,
                "y": y,
                "label": f"{slot_id} {short}",
                "layout": layout_name,
            }
        )
    return out


def _touch_role_from_slot(slot_id: str) -> str:
    s = str(slot_id or "").upper()
    if s.startswith("RB") or s in {"FB"}:
        return "carry"
    if s.startswith(("WR", "TE")):
        return "target"
    if s == "QB":
        return "carry"
    return ""


def _build_gamecast_figure(
    ball_yard: int,
    plays: list[dict] | None = None,
    players: list[dict] | None = None,
    selected_player: str = "",
) -> go.Figure:
    """Top-down football field: turf, hashes, formation, ball, EPA arrows."""
    yard = max(1, min(99, int(ball_yard)))
    fig = go.Figure()
    w = FIELD_WIDTH_YDS
    mid = FIELD_CENTER_Y

    # Alternating 5-yard turf stripes
    for i, x0 in enumerate(range(0, 100, 5)):
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x0 + 5,
            y0=0,
            y1=w,
            fillcolor="#1B4332" if i % 2 == 0 else "#2D6A4F",
            line=dict(width=0),
            layer="below",
        )
    # End zones
    for x0, x1 in ((-10, 0), (100, 110)):
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x1,
            y0=0,
            y1=w,
            fillcolor="#081C15",
            line=dict(width=0),
            layer="below",
        )
    # Sidelines + goal lines
    fig.add_shape(
        type="rect",
        x0=0,
        x1=100,
        y0=0,
        y1=w,
        fillcolor="rgba(0,0,0,0)",
        line=dict(color="rgba(255,255,255,0.85)", width=2),
        layer="below",
    )
    for x in (0, 100):
        fig.add_shape(
            type="line",
            x0=x,
            x1=x,
            y0=0,
            y1=w,
            line=dict(color="#FFFFFF", width=3),
        )
    # Midfield
    fig.add_shape(
        type="line",
        x0=50,
        x1=50,
        y0=0,
        y1=w,
        line=dict(color="rgba(255,255,255,0.9)", width=2),
    )
    # Yard lines every 5 / numbers every 10
    for x in range(5, 100, 5):
        heavy = x % 10 == 0
        fig.add_shape(
            type="line",
            x0=x,
            x1=x,
            y0=0,
            y1=w,
            line=dict(
                color="rgba(255,255,255,0.45)" if heavy else "rgba(255,255,255,0.2)",
                width=1.5 if heavy else 1,
            ),
        )
        if heavy and x not in (0, 100):
            num = str(x if x <= 50 else 100 - x)
            for yy, anchor in ((4.5, "bottom"), (w - 4.5, "top")):
                fig.add_annotation(
                    x=x,
                    y=yy,
                    text=num,
                    showarrow=False,
                    font=dict(color="rgba(255,255,255,0.75)", size=12, family="Arial Black"),
                    yanchor=anchor,
                )
    # Hash marks (approx HS / NCAA)
    for hash_y in (mid - 6.5, mid + 6.5):
        for x in range(1, 100):
            fig.add_shape(
                type="line",
                x0=x,
                x1=x,
                y0=hash_y - 0.45,
                y1=hash_y + 0.45,
                line=dict(color="rgba(255,255,255,0.35)", width=1),
            )
    # End-zone labels
    fig.add_annotation(
        x=-5,
        y=mid,
        text="OWN",
        showarrow=False,
        textangle=-90,
        font=dict(color="#74C69D", size=16, family="Arial Black"),
    )
    fig.add_annotation(
        x=105,
        y=mid,
        text="OPP",
        showarrow=False,
        textangle=90,
        font=dict(color="#74C69D", size=16, family="Arial Black"),
    )
    # LOS guide
    fig.add_shape(
        type="line",
        x0=yard,
        x1=yard,
        y0=0,
        y1=w,
        line=dict(color="#F4A261", width=2, dash="dot"),
    )

    # Recent play EPA paths — thick arrows + high-contrast badges
    play_list = list(plays or [])[-4:]
    for i, p in enumerate(play_list):
        x0 = float(p.get("start") or yard)
        x1 = float(p.get("end") or x0)
        if abs(x1 - x0) < 0.4:
            # No-gain / incomplete — still show a visible tick at the spot
            x1 = x0 + 0.8
        epa = float(p.get("epa") or 0)
        is_latest = i == len(play_list) - 1
        pos = epa >= 0
        color = "#B7F7C8" if pos else "#FF8A65"
        badge_bg = "rgba(8,28,21,0.92)" if pos else "rgba(60,16,8,0.92)"
        # Fan paths slightly so overlapping snaps stay readable
        y_lane = mid + (-1 if i % 2 == 0 else 1) * (3.5 + (len(play_list) - 1 - i) * 1.2)
        width = 7 if is_latest else 4
        opacity = 1.0 if is_latest else 0.75
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y_lane, y_lane],
                mode="lines",
                line=dict(color=color, width=width),
                hovertemplate=str(p.get("label") or "") + "<extra></extra>",
                showlegend=False,
                opacity=opacity,
            )
        )
        # Start / end dots for contrast on green turf
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y_lane, y_lane],
                mode="markers",
                marker=dict(
                    size=[10, 14] if is_latest else [8, 11],
                    color=["#FFFFFF", color],
                    line=dict(color="#081C15", width=1.5),
                ),
                hoverinfo="skip",
                showlegend=False,
                opacity=opacity,
            )
        )
        call = str(p.get("call") or "").strip()
        call_short = (call[:10] + "…") if len(call) > 11 else call
        badge = f"<b>{epa:+.2f}</b>"
        if is_latest and call_short:
            badge = f"<b>{call_short}</b>  {epa:+.2f}"
        fig.add_annotation(
            x=(x0 + x1) / 2,
            y=y_lane + (4.2 if is_latest else 3.2),
            text=badge,
            showarrow=False,
            bgcolor=badge_bg,
            bordercolor=color,
            borderwidth=2 if is_latest else 1,
            borderpad=4 if is_latest else 3,
            font=dict(
                color=color,
                size=16 if is_latest else 13,
                family="Arial Black",
            ),
        )

    # Clickable yard targets on the LOS
    click_x = list(range(5, 100, 5))
    fig.add_trace(
        go.Scatter(
            x=click_x,
            y=[mid] * len(click_x),
            mode="markers",
            marker=dict(size=14, color="rgba(255,255,255,0.06)", line=dict(width=0)),
            customdata=[["yard", x] for x in click_x],
            hovertemplate="%{text}<extra></extra>",
            text=[format_ball_spot(x) for x in click_x],
            name="spot",
            showlegend=False,
        )
    )

    # Formation players (click → ball to)
    if players:
        sel = str(selected_player or "").strip().lower()
        xs, ys, texts, cds, colors, sizes = [], [], [], [], [], []
        for p in players:
            xs.append(p["x"])
            ys.append(p["y"])
            texts.append(p["label"])
            cds.append(["player", p["slot"], p["name"]])
            is_sel = p["name"].lower() == sel
            colors.append("#F4A261" if is_sel else "#D8F3DC")
            sizes.append(18 if is_sel else 14)
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers+text",
                marker=dict(
                    size=sizes,
                    color=colors,
                    line=dict(color="#081C15", width=1.5),
                    symbol="circle",
                ),
                text=texts,
                textposition="top center",
                textfont=dict(color="#FFFFFF", size=9),
                customdata=cds,
                hovertemplate="<b>%{customdata[2]}</b> · %{customdata[1]}<br>Tap to set ball to<extra></extra>",
                name="players",
                showlegend=False,
            )
        )

    # Football
    fig.add_trace(
        go.Scatter(
            x=[yard],
            y=[mid],
            mode="markers",
            marker=dict(
                size=16,
                color="#C45C26",
                line=dict(color="#FFFFFF", width=2),
                symbol="diamond-wide",
            ),
            customdata=[["yard", yard]],
            hovertemplate=f"Ball · {format_ball_spot(yard)}<extra></extra>",
            name="ball",
            showlegend=False,
        )
    )

    fig.update_layout(
        height=280,
        margin=dict(l=4, r=4, t=4, b=4),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(range=[-11, 111], visible=False, fixedrange=True),
        yaxis=dict(range=[-1, w + 1], visible=False, fixedrange=True),
        dragmode=False,
        clickmode="event+select",
    )
    return fig


def _parse_gamecast_customdata(raw) -> dict | None:
    """Normalize Plotly customdata into {kind: yard|player, ...}."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and raw:
        kind = str(raw[0] or "").lower()
        if kind == "yard":
            try:
                return {"kind": "yard", "yard": max(1, min(99, int(raw[1])))}
            except (TypeError, ValueError, IndexError):
                return None
        if kind == "player":
            try:
                return {
                    "kind": "player",
                    "slot": str(raw[1] or ""),
                    "name": str(raw[2] or "").strip(),
                }
            except IndexError:
                return None
    # Legacy: bare yard int
    try:
        return {"kind": "yard", "yard": max(1, min(99, int(raw)))}
    except (TypeError, ValueError):
        return None


def _apply_gamecast_selection(event) -> dict | None:
    """Extract yard or player click from Plotly selection event."""
    if event is None:
        return None
    try:
        points = event.selection.points  # type: ignore[attr-defined]
    except Exception:
        sel = event.get("selection") if isinstance(event, dict) else None
        points = (sel or {}).get("points") or []
    if not points:
        return None
    pt = points[0]
    if isinstance(pt, dict):
        cd = pt.get("customdata")
        x = pt.get("x")
    else:
        cd = getattr(pt, "customdata", None)
        x = getattr(pt, "x", None)
    parsed = _parse_gamecast_customdata(cd)
    if parsed:
        return parsed
    if x is not None:
        try:
            return {"kind": "yard", "yard": max(1, min(99, int(round(float(x)))))}
        except (TypeError, ValueError):
            return None
    return None


def _render_live_gamecast(
    *,
    opponent: str,
    live_logs: pd.DataFrame | None,
    ball_yard: int,
) -> int:
    """
    Football GameCast: turf field, formation overlay, ball spot, EPA arrows.

    Tap a yard hash to set spot · tap a player to set ball-to / touch role.
    Drag the slider as a backup. Formation diagrams live in data/formation_layouts.json.
    """
    yard = max(1, min(99, int(ball_yard)))
    formation = ""
    variant = ""
    try:
        formation = _ql_resolve_piece("ql_form") or str(st.session_state.get("ql_form") or "")
        variant = _ql_resolve_piece("ql_variant") or str(st.session_state.get("ql_variant") or "")
    except Exception:
        formation = str(st.session_state.get("ql_form") or "")
        variant = str(st.session_state.get("ql_variant") or "")

    def _handle_click(hit: dict | None) -> bool:
        if not hit:
            return False
        if hit.get("kind") == "yard":
            y = int(hit["yard"])
            if y != int(st.session_state.get("lt_ball_yard") or 0):
                st.session_state.lt_ball_yard = y
                st.session_state.lt_zone = ball_yard_to_zone(y)
                return True
            return False
        if hit.get("kind") == "player" and hit.get("name"):
            st.session_state.lt_gc_ball_player = str(hit["name"])
            st.session_state.lt_gc_touch_slot = str(hit.get("slot") or "")
            st.session_state.lt_gc_touch_role = _touch_role_from_slot(
                str(hit.get("slot") or "")
            )
            return True
        return False

    prior = st.session_state.get("lt_gamecast")
    prior_hit = _apply_gamecast_selection(prior)
    if _handle_click(prior_hit) and (prior_hit or {}).get("kind") == "yard":
        yard = int(st.session_state.lt_ball_yard)

    yard = int(st.session_state.get("lt_ball_yard") or yard)
    plays = _gamecast_recent_plays(live_logs, opponent, limit=6)
    players = _formation_players_on_field(yard, formation, variant)
    selected = str(st.session_state.get("lt_gc_ball_player") or "")
    layout_name = resolve_formation_layout_name(formation, variant)
    try:
        from formation_logic import formation_breakdown

        form_note = formation_breakdown(formation, variant)
    except Exception:
        form_note = {"note": formation, "known": False}
    fig = _build_gamecast_figure(
        yard, plays, players=players, selected_player=selected
    )
    event = st.plotly_chart(
        fig,
        width="stretch",
        key="lt_gamecast",
        on_select="rerun",
        selection_mode="points",
        theme=None,
        config={
            "displayModeBar": False,
            "scrollZoom": False,
            "staticPlot": False,
        },
    )
    if _handle_click(_apply_gamecast_selection(event)):
        st.rerun()

    s1, s2 = st.columns([4, 1.2])
    with s1:
        ball = int(st.session_state.get("lt_ball_yard") or yard)
        slider_val = st.session_state.get("lt_gc_slider")
        last = st.session_state.get("lt_gc_last_written")
        if slider_val is None:
            st.session_state.lt_gc_slider = ball
        elif int(slider_val) != ball and last != ball:
            st.session_state.lt_gc_slider = ball
        new_yard = int(
            st.slider(
                "Ball spot (drag)",
                min_value=1,
                max_value=99,
                key="lt_gc_slider",
                help="Drag to move the ball · or tap a yard hash on the field.",
            )
        )
    with s2:
        st.markdown(
            f'<div class="gc-spot">{format_ball_spot(new_yard)}</div>',
            unsafe_allow_html=True,
        )
    st.session_state.lt_ball_yard = new_yard
    st.session_state.lt_gc_last_written = new_yard
    st.session_state.lt_zone = ball_yard_to_zone(new_yard)

    bp = str(st.session_state.get("lt_gc_ball_player") or "")
    role = str(st.session_state.get("lt_gc_touch_role") or "")
    slot = str(st.session_state.get("lt_gc_touch_slot") or "")
    if bp:
        role_bit = f" · {role}" if role else ""
        slot_bit = f" ({slot})" if slot else ""
        st.markdown(
            f'<div class="gc-ballto">Ball to <b>{bp}</b>{slot_bit}{role_bit} '
            f'· tap another player to change</div>',
            unsafe_allow_html=True,
        )
    else:
        note = str(form_note.get("note") or formation or "")
        st.caption(
            (f"**{note}** · " if note else "")
            + f"layout `{layout_name}`"
            + " — tap a player for ball-to"
        )

    if plays:
        chips = []
        for p in reversed(plays[-5:]):
            epa = float(p.get("epa") or 0)
            cls = "gc-play up" if epa >= 0 else "gc-play down"
            chips.append(
                f'<span class="{cls}">{p.get("call") or "—"} '
                f'{int(p.get("yards") or 0):+d} · {epa:+.1f}</span>'
            )
        st.markdown(
            '<div class="gc-plays">' + "".join(chips) + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("Plays with EPA appear here after you log.")

    return int(new_yard)


def situation_label(
    down: int,
    distance_bucket: str,
    field_zone: str,
    ball_yard: int | float | None = None,
) -> str:
    zone = field_zone or "midfield"
    if ball_yard is not None:
        spot = format_ball_spot(ball_yard)
        zone_bit = f"{spot} · {ZONE_LABELS.get(zone, zone)}"
    else:
        zone_bit = ZONE_LABELS.get(zone, zone)
    return (
        f"{DOWN_LABELS[int(down)]} & {DISTANCE_LABELS[distance_bucket]} "
        f"| {zone_bit}"
    )


def run_pass_lean(df: pd.DataFrame) -> str:
    typed = df[df["play_type"].isin(["Run", "Pass"])]
    if typed.empty:
        return "—"
    summary = typed.groupby("play_type")["epa"].mean()
    if len(summary) < 2:
        return str(summary.index[0])
    if summary["Pass"] > summary["Run"] + 0.05:
        return "Pass"
    if summary["Run"] > summary["Pass"] + 0.05:
        return "Run"
    return "Balanced"


def build_call_sheet(
    df: pd.DataFrame,
    group_col: str,
    min_situation_plays: int,
    min_call_plays: int,
    top_n: int,
    package_col: str = "formation",
    situations: list[tuple[int, str, str]] | None = None,
) -> pd.DataFrame:
    if situations is None:
        situations = [
            (down, dist, zone)
            for down in (1, 2, 3, 4)
            for dist in ("short", "medium", "long")
            for zone in ZONE_LABELS
        ]

    rows: list[dict] = []
    for down, dist, zone in situations:
        subset = filter_situation(df, down, dist, zone)
        if len(subset) < min_situation_plays:
            continue

        lean = run_pass_lean(subset)
        top_package = avg_epa_table(subset, package_col, min_call_plays, exclude_unknown=True)
        best_package = top_package.iloc[0][package_col] if not top_package.empty else "—"

        ranked = avg_epa_table(subset, group_col, min_call_plays, exclude_unknown=True)
        if ranked.empty:
            continue

        for rank, item in enumerate(ranked.head(top_n).itertuples(index=False), start=1):
            call_value = getattr(item, group_col)
            rows.append(
                {
                    "situation": situation_label(down, dist, zone),
                    "down": int(down),
                    "distance": dist,
                    "field_zone": zone,
                    "rank": rank,
                    "recommendation": call_value,
                    "avg_epa": item.avg_epa,
                    "plays": int(item.plays),
                    "run_pass_lean": lean,
                    "top_package": best_package,
                    "situation_plays": len(subset),
                }
            )

    if not rows:
        return pd.DataFrame()

    sheet = pd.DataFrame(rows)
    return sheet.sort_values(["down", "distance", "field_zone", "rank"]).reset_index(drop=True)


KEY_SITUATIONS = [
    (1, "long", "own_territory"),
    (1, "long", "midfield"),
    (1, "long", "opp_territory"),
    (2, "short", "midfield"),
    (2, "medium", "midfield"),
    (2, "long", "midfield"),
    (3, "short", "midfield"),
    (3, "medium", "midfield"),
    (3, "long", "midfield"),
    (3, "short", "red_zone"),
    (3, "medium", "red_zone"),
    (2, "short", "red_zone"),
    (1, "long", "red_zone"),
    (4, "short", "midfield"),
    (4, "medium", "opp_territory"),
    (4, "short", "red_zone"),
]


def format_game_label(opponent: str, game_notes: str = "", game_id: int | None = None) -> str:
    label = f"vs {opponent}"
    notes = str(game_notes or "").strip()
    # Live Track games all share the same note — don't clutter the x-axis
    if notes and notes.lower() not in {"live track", "live", "nan", "none"}:
        label = f"{label} ({notes})"
    elif game_id is not None:
        label = f"{label} (G{int(game_id)})"
    return label


def game_review_table(df: pd.DataFrame, invert_xp: bool = False) -> pd.DataFrame:
    if "game_id" not in df.columns:
        return pd.DataFrame()

    # game_id alone can collide across sources; keep opponent in the key
    group_cols: list[str] = ["game_id"]
    if "opponent" in df.columns:
        group_cols.append("opponent")

    agg: dict = {
        "plays": ("epa", "count"),
        "total_epa": ("epa", "sum"),
        "actual_points": ("points_scored", "sum"),
        "touchdowns": ("is_touchdown", "sum"),
    }
    if "game_notes" in df.columns:
        agg["game_notes"] = ("game_notes", "first")
    if "opponent" in df.columns and "opponent" not in group_cols:
        agg["opponent"] = ("opponent", "first")

    games = df.groupby(group_cols, dropna=False).agg(**agg).reset_index()
    if "opponent" not in games.columns:
        games["opponent"] = "Unknown"
    if "game_notes" not in games.columns:
        games["game_notes"] = ""

    games["game_label"] = games.apply(
        lambda row: format_game_label(
            str(row["opponent"]),
            str(row["game_notes"]) if pd.notna(row["game_notes"]) else "",
            game_id=int(row["game_id"]) if pd.notna(row.get("game_id")) else None,
        ),
        axis=1,
    )

    avg_epa = games["total_epa"].mean()
    avg_points = games["actual_points"].mean()

    if invert_xp:
        games["xpoints"] = (avg_points - (games["total_epa"] - avg_epa)).round(1)
    else:
        games["xpoints"] = (avg_points + (games["total_epa"] - avg_epa)).round(1)
    games["luck"] = (games["actual_points"] - games["xpoints"]).round(1)
    games["total_epa"] = games["total_epa"].round(2)

    return games.sort_values(["game_id", "opponent"] if "opponent" in games.columns else ["game_id"])


def combo_heatmap(
    df: pd.DataFrame,
    min_plays: int,
    top_rows: int,
    top_cols: int,
    row_col: str = "formation",
    col_col: str = "play_call",
    title: str = "Formation x Play Call — Avg EPA (heatmap)",
    x_title: str = "Play call",
    y_title: str = "Formation",
    is_defense: bool = False,
):
    valid = df[
        df[row_col].notna()
        & df[col_col].notna()
        & (df[row_col].astype(str) != "")
        & (df[col_col].astype(str) != "")
        & ~df[row_col].astype(str).str.contains("Unknown", na=False)
        & ~df[col_col].astype(str).str.contains("Unknown", na=False)
    ].copy()
    # Formation axis is current-season only (prior-year formations are flawed)
    if row_col in {"formation", "formation_play"}:
        if "season" in valid.columns:
            valid = valid[_is_current_season_mask(valid["season"])]
        if "form_tagged" in valid.columns and row_col == "formation":
            valid = valid[valid["form_tagged"].fillna(0).astype(int) == 1]
        if "tags_ok" in valid.columns and row_col == "formation_play":
            valid = valid[valid["tags_ok"].fillna(0).astype(int) == 1]
    if col_col == "play_call" and "play_tagged" in valid.columns:
        valid = valid[valid["play_tagged"].fillna(0).astype(int) == 1]
    if valid.empty:
        return None, pd.DataFrame()

    top_row_vals = valid[row_col].value_counts().head(top_rows).index
    top_col_vals = valid[col_col].value_counts().head(top_cols).index
    subset = valid[valid[row_col].isin(top_row_vals) & valid[col_col].isin(top_col_vals)]

    pivot_epa = subset.pivot_table(index=row_col, columns=col_col, values="epa", aggfunc="mean")
    pivot_n = subset.pivot_table(index=row_col, columns=col_col, values="epa", aggfunc="count")

    # Mask cells below min plays
    masked = pivot_epa.copy()
    masked[pivot_n < min_plays] = np.nan

    detail_rows = []
    for form in pivot_epa.index:
        for call in pivot_epa.columns:
            n = int(pivot_n.loc[form, call]) if pd.notna(pivot_n.loc[form, call]) else 0
            if n >= min_plays:
                detail_rows.append(
                    {
                        "row": form,
                        "col": call,
                        "combo": f"{form} | {call}",
                        "plays": n,
                        "avg_epa": round(float(pivot_epa.loc[form, call]), 3),
                    }
                )
    detail = pd.DataFrame(detail_rows).sort_values("avg_epa", ascending=False)

    text = masked.apply(
        lambda row: [f"{v:.2f}" if pd.notna(v) else "" for v in row],
        axis=1,
        result_type="expand",
    )
    text.columns = masked.columns
    text.index = masked.index

    fig = go.Figure(
        data=go.Heatmap(
            z=masked.values,
            x=masked.columns,
            y=masked.index,
            text=text.values,
            texttemplate="%{text}",
            textfont={"color": "#ffffff", "size": 12},
            colorscale=GREEN_SCALE,
            zmid=0,
            colorbar={
                "title": "Def EPA (↑ better)" if is_defense else "Avg EPA (↑ better)",
                "tickfont": {"color": "#f9fafb"},
            },
            hovertemplate=f"{y_title}: %{{y}}<br>{x_title}: %{{x}}<br>Avg EPA: %{{z:.3f}}<extra></extra>",
        )
    )
    apply_chart_style(fig, title=title, height=max(420, 40 * len(masked.index)))
    fig.update_layout(xaxis_title=x_title, yaxis_title=y_title)
    return fig, detail


def plays_for_season(df: pd.DataFrame, season_id: str | None) -> pd.DataFrame:
    """Filter plays to a season id (None / current → active season aliases)."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    if "season" not in df.columns:
        return df
    tc = _season_api()
    sid = str(season_id or tc.current_season_id()).strip()
    s = df["season"].fillna("").astype(str).str.strip().str.lower()
    # Concrete id match (e.g. "26-27") — do not rely on a cached "current" mask
    if sid.lower() not in {"current", ""} and not tc.is_current_season_value(sid):
        return df[s == sid.lower()].copy()
    # Active / current: include all aliases (26-27, current, blank, …)
    aliases = {a for a in tc.current_season_aliases() if a is not None}
    aliases.add(str(tc.current_season_id()).strip().lower())
    aliases.add("current")
    aliases.add("")
    return df[s.isin(aliases)].copy()


def list_play_seasons(df: pd.DataFrame) -> list[str]:
    """Season labels present in play data, current first."""
    tc = _season_api()
    cur = tc.current_season_id()
    found: list[str] = []
    if df is not None and not df.empty and "season" in df.columns:
        for raw in df["season"].fillna("current").astype(str).str.strip().unique():
            val = str(raw).strip() or "current"
            if tc.is_current_season_value(val):
                label = cur
            else:
                label = val
            if label and label not in found:
                found.append(label)
    if cur and cur not in found:
        found.insert(0, cur)
    # stable: current first, then others sorted
    rest = sorted(x for x in found if x != cur)
    return ([cur] if cur in found or cur else []) + rest


def game_review_page(df: pd.DataFrame, unit_cfg: dict) -> None:
    invert = unit_cfg["invert_xp"]
    if invert:
        intro = """
        **Defensive xP:** estimates how many **TD points (6 each)** you *should* have allowed
        based on opponent play quality vs your defense.

        - **Total EPA** = defensive process (higher = better stops)
        - **Actual pts** = TDs allowed on tagged defensive snaps
        - **xPoints** = expected points allowed from that EPA profile
        - **Luck** = Actual − xPoints (negative = held them below expectation — good)
        """
    else:
        intro = """
        **Like xG in soccer:** xPoints estimates how many **TD points (6 each)** your offense
        *should* have produced based on **play quality (EPA)**.

        - **Total EPA** = process (did you win the play-by-play?)
        - **Actual points** = TDs scored on tagged offensive plays
        - **xPoints** = expected TD-points from that EPA profile
        - **Luck** = Actual − xPoints (positive = finished better than process)
        """
    st.header("Game Review — Expected Points (xP)")
    st.markdown(intro)
    if invert:
        show_defense_legend()

    tc = _season_api()
    season_opts = list_play_seasons(df)
    # Include schedule-only seasons so you can switch even before Hudl lands
    try:
        from schedule import list_schedule_season_ids

        for sid in list_schedule_season_ids():
            if sid not in season_opts:
                season_opts.append(sid)
    except Exception:
        pass
    if not season_opts:
        season_opts = [tc.current_season_id()]

    cur = tc.current_season_id()
    default_ix = season_opts.index(cur) if cur in season_opts else 0
    c_season, c_hint = st.columns([1.2, 2.8])
    picked = c_season.selectbox(
        "Season",
        season_opts,
        index=default_ix,
        key="gr_season_pick",
        help="Swap years to review prior seasons without changing the active booth season.",
    )
    is_active = tc.is_current_season_value(picked) or picked == cur
    if is_active:
        c_hint.caption(f"Viewing **active** season ({tc.current_season_label()}). Edit schedule under Database → Schedule.")
    else:
        c_hint.caption(
            f"Viewing archived season **{picked}**. Active booth season stays **{tc.current_season_label()}**."
        )

    review_df = plays_for_season(df, picked)
    # Pull in any live_games CSVs that never merged (e.g. promote skipped / cache stale)
    try:
        from live_games import remerge_all_live_games

        sync = remerge_all_live_games(skip_hudl_conflicts=True)
        if int(sync.get("merged") or 0) > 0:
            try:
                st.cache_data.clear()
            except Exception:
                pass
            df = load_plays("Offense" if not invert else "Defense")
            review_df = plays_for_season(df, picked)
            st.caption(
                f"Synced **{sync.get('plays', 0)}** live snaps into Game Review "
                f"({sync.get('merged')} game file(s))."
            )
    except Exception:
        pass

    other_n = 0
    if "season" in df.columns:
        other_n = int(len(df) - len(review_df))
    st.caption(
        f"Showing **{picked}** games"
        + (f" · {other_n:,} snaps in other seasons stay available via the picker." if other_n else ".")
    )

    games = game_review_table(review_df, invert_xp=invert)
    if games.empty:
        st.warning(
            "No games for this season yet. Drop Hudl into `data/hudl_exports/`, "
            "set the schedule under **Database → Schedule**, then run `python refresh_all.py`. "
            "Finished Live Track games also land here when you **Start new game**."
        )
        return

    live_n = 0
    if "game_notes" in review_df.columns:
        live_n = int(
            (review_df["game_notes"].astype(str).str.strip().str.lower() == "live track").sum()
        )
    if live_n:
        st.caption(f"Includes **{live_n:,}** Live Track snaps this season.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Games", len(games))
    c2.metric("Avg EPA / game", f"{games['total_epa'].mean():.2f}")
    c3.metric(unit_cfg["points_metric"], f"{games['actual_points'].mean():.1f}")
    c4.metric("Avg xPoints", f"{games['xpoints'].mean():.1f}")

    chart_df = games.copy()

    # Build axes first, then traces — applying a Plotly template *after* traces
    # can wipe custom line colors (xP was rendering near-white).
    points_fig = go.Figure()
    apply_chart_style(
        points_fig,
        title=(
            "Points Allowed vs Expected — by Game"
            if invert
            else "Actual Points vs Expected Points — by Game"
        ),
        height=440,
    )
    points_fig.add_trace(
        smooth_line_chart(
            chart_df,
            "game_label",
            "actual_points",
            unit_cfg["actual_line"],
            "#1B4332",
            width=4.5,
            show_labels=True,
            curved=True,
        )
    )
    points_fig.add_trace(
        smooth_line_chart(
            chart_df,
            "game_label",
            "xpoints",
            "Expected points (xP)",
            "#C9A227",
            dash="solid",
            width=4.5,
            show_labels=True,
            curved=True,
        )
    )
    # Hard-lock by index — Streamlit theme can remap named colors
    if len(points_fig.data) >= 1:
        points_fig.data[0].line.color = "#1B4332"
        points_fig.data[0].line.shape = "spline"
        points_fig.data[0].line.smoothing = 0.85
        points_fig.data[0].marker.color = "#1B4332"
        points_fig.data[0].marker.line.color = "#1B4332"
        if getattr(points_fig.data[0], "textfont", None) is not None:
            points_fig.data[0].textfont.color = "#1B4332"
    if len(points_fig.data) >= 2:
        points_fig.data[1].line.color = "#C9A227"
        points_fig.data[1].line.shape = "spline"
        points_fig.data[1].line.smoothing = 0.85
        points_fig.data[1].line.width = 4.5
        points_fig.data[1].marker.color = "#C9A227"
        points_fig.data[1].marker.line.color = "#A16207"
        if getattr(points_fig.data[1], "textfont", None) is not None:
            points_fig.data[1].textfont.color = "#A16207"
    points_fig.update_layout(
        xaxis_title="Game",
        yaxis_title="Points",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hovermode="x unified",
        colorway=["#1B4332", "#C9A227"],
    )
    # theme=None stops Streamlit from remapping Plotly colors to the app theme
    st.plotly_chart(points_fig, use_container_width=True, theme=None)

    c1, c2 = st.columns(2)
    with c1:
        epa_fig = go.Figure()
        apply_chart_style(epa_fig, title="Total EPA by Game (↑ better)", height=380)
        epa_fig.add_trace(
            smooth_line_chart(
                chart_df,
                "game_label",
                "total_epa",
                "Total EPA (process)",
                "#14532D",
                width=4,
                show_labels=True,
            )
        )
        epa_fig.update_traces(line_color="#14532D", marker_color="#14532D")
        epa_fig.update_layout(xaxis_title="Game", yaxis_title="Def EPA" if invert else "EPA")
        st.plotly_chart(epa_fig, use_container_width=True, theme=None)
    with c2:
        luck_fig = px.bar(
            chart_df,
            x="game_label",
            y="luck",
            title="Finishing Luck (↓ better on defense)" if invert else "Finishing Luck by Game",
            color="luck",
            color_continuous_scale=luck_color_scale(unit_cfg),
            template="simple_white",
        )
        apply_chart_style(luck_fig, height=380)
        luck_fig.add_hline(y=0, line_dash="dash", line_color="#64748B")
        luck_fig.update_layout(xaxis_title="Game", yaxis_title="Luck")
        st.plotly_chart(luck_fig, use_container_width=True, theme=None)

    st.subheader("Game-by-game table")
    show = games[
        [
            "game_label",
            "opponent",
            "plays",
            "total_epa",
            "actual_points",
            "xpoints",
            "luck",
            "touchdowns",
        ]
    ].rename(
        columns={
            "game_label": "Game",
            "opponent": "Opponent",
            "total_epa": "Total EPA",
            "actual_points": "Pts allowed" if invert else "Actual pts",
            "xpoints": "xPoints",
            "luck": "Luck",
            "touchdowns": unit_cfg["td_label"],
        }
    )
    st.dataframe(show, use_container_width=True, hide_index=True)

    best_process = games.loc[games["total_epa"].idxmax()]
    if invert:
        lucky = games.loc[games["luck"].idxmin()]
        unlucky = games.loc[games["luck"].idxmax()]
        st.info(
            f"**Best defensive process:** {best_process['game_label']} ({best_process['total_epa']:+.2f} EPA) · "
            f"**Best stops (luck):** {lucky['game_label']} ({lucky['luck']:+.1f}) · "
            f"**Most points left on field:** {unlucky['game_label']} ({unlucky['luck']:+.1f})"
        )
    else:
        lucky = games.loc[games["luck"].idxmax()]
        unlucky = games.loc[games["luck"].idxmin()]
        st.info(
            f"**Best process:** {best_process['game_label']} ({best_process['total_epa']:+.2f} EPA) · "
            f"**Best finishing luck:** {lucky['game_label']} ({lucky['luck']:+.1f}) · "
            f"**Worst finishing luck:** {unlucky['game_label']} ({unlucky['luck']:+.1f})"
        )


def combo_page(df: pd.DataFrame, unit_cfg: dict) -> None:
    st.header(unit_cfg["combo_page_title"])
    if unit_cfg["invert_xp"]:
        show_defense_legend()
    st.caption(
        "EPA by your best pairings in each situation."
        if not unit_cfg["invert_xp"]
        else "Which front/coverage pairs limit opponent EPA best."
    )

    f1, f2, f3, f4 = st.columns(4)
    down_filter = f1.selectbox("Down", ["Any", 1, 2, 3, 4], key="combo_down")
    dist_filter = f2.selectbox("Distance", ["Any", "Short", "Medium", "Long"], key="combo_dist")
    zone_filter = f3.selectbox(
        "Field zone",
        ["Any", "backed_up", "own_territory", "midfield", "opp_territory", "red_zone"],
        key="combo_zone",
    )
    min_plays = f4.slider("Min plays per cell", 2, 12, 4, key="combo_min")

    filtered = filter_situation(
        df,
        None if down_filter == "Any" else int(down_filter),
        None if dist_filter == "Any" else dist_filter,
        None if zone_filter == "Any" else zone_filter,
    )

    h1, h2 = st.columns(2)
    top_rows = h1.slider(f"Top {unit_cfg['heatmap_y'].lower()}s in heatmap", 5, 12, 8)
    top_cols = h2.slider(f"Top {unit_cfg['heatmap_x'].lower()}s in heatmap", 5, 15, 10)

    fig, detail = combo_heatmap(
        filtered,
        min_plays,
        top_rows,
        top_cols,
        row_col=unit_cfg["heatmap_rows"],
        col_col=unit_cfg["heatmap_cols"],
        title=unit_cfg["heatmap_title"],
        x_title=unit_cfg["heatmap_x"],
        y_title=unit_cfg["heatmap_y"],
        is_defense=unit_cfg["invert_xp"],
    )
    if fig is None:
        st.warning("Not enough tagged data for this heatmap.")
        return

    st.plotly_chart(fig, use_container_width=True)

    combo_table = avg_epa_table(filtered, unit_cfg["combo_col"], min_plays)
    st.subheader("Best combos (ranked list)")
    if combo_table.empty:
        st.write("Lower the min plays filter to see more combos.")
    else:
        bar = px.bar(
            combo_table.head(15),
            x="avg_epa",
            y=unit_cfg["combo_col"],
            orientation="h",
            color="avg_epa",
            color_continuous_scale=epa_color_scale(unit_cfg),
            template=CHART_TEMPLATE,
            title=f"Top combos by avg EPA (↑ better)",
            labels={"avg_epa": "Avg EPA", unit_cfg["combo_col"]: "Combo"},
            hover_data=["plays", "total_epa"],
        )
        bar.update_layout(yaxis={"categoryorder": "total ascending"}, height=520)
        apply_chart_style(bar, height=520)
        st.plotly_chart(bar, use_container_width=True)
        st.dataframe(combo_table, use_container_width=True, hide_index=True)


def scout_room(df: pd.DataFrame, unit_cfg: dict) -> None:
    st.header("Scout Room")
    if unit_cfg["invert_xp"]:
        show_defense_legend()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Plays", f"{len(df):,}")
    col2.metric("Avg EPA / play", f"{df['epa'].mean():.3f}")
    col3.metric("Pass EPA", f"{df.loc[df['play_type'] == 'Pass', 'epa'].mean():.3f}")
    col4.metric("Run EPA", f"{df.loc[df['play_type'] == 'Run', 'epa'].mean():.3f}")

    f1, f2, f3, f4 = st.columns(4)
    down_filter = f1.selectbox("Down", ["Any", 1, 2, 3, 4])
    dist_filter = f2.selectbox("Distance", ["Any", "Short", "Medium", "Long"])
    zone_filter = f3.selectbox(
        "Field zone",
        ["Any", "backed_up", "own_territory", "midfield", "opp_territory", "red_zone"],
    )
    min_plays = f4.slider("Min plays", 5, 30, 8)

    filtered = filter_situation(
        df,
        None if down_filter == "Any" else int(down_filter),
        None if dist_filter == "Any" else dist_filter,
        None if zone_filter == "Any" else zone_filter,
    )
    st.caption(f"{len(filtered):,} plays match filters")

    tab1, tab2, tab3 = st.tabs(["Combos", unit_cfg["primary_label"], "Situations"])

    with tab1:
        fig, detail = combo_heatmap(
            filtered,
            max(3, min_plays - 3),
            8,
            10,
            row_col=unit_cfg["heatmap_rows"],
            col_col=unit_cfg["heatmap_cols"],
            title=unit_cfg["heatmap_title"],
            x_title=unit_cfg["heatmap_x"],
            y_title=unit_cfg["heatmap_y"],
            is_defense=unit_cfg["invert_xp"],
        )
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        combo_table = avg_epa_table(filtered, unit_cfg["combo_col"], min_plays)
        if not combo_table.empty:
            st.dataframe(combo_table.head(20), use_container_width=True, hide_index=True)

    with tab2:
        form_table = avg_epa_table(filtered, unit_cfg["primary_group"], min_plays)
        if form_table.empty:
            st.info(f"No {unit_cfg['primary_label'].lower()} meet min plays.")
        else:
            fig = px.bar(
                form_table.head(12),
                x="avg_epa",
                y=unit_cfg["primary_group"],
                orientation="h",
                color="avg_epa",
                color_continuous_scale=epa_color_scale(unit_cfg),
                template=CHART_TEMPLATE,
                title=f"Avg EPA by {unit_cfg['primary_label'].rstrip('s').lower()} (↑ better)",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=450)
            apply_chart_style(fig, height=450)
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        c1, c2 = st.columns(2)
        down_epa = df.groupby("down")["epa"].mean().reset_index()
        down_epa["down"] = down_epa["down"].astype(int).astype(str)
        c1.plotly_chart(
            apply_chart_style(
                px.bar(
                    down_epa,
                    x="down",
                    y="epa",
                    title="EPA by down",
                    template=CHART_TEMPLATE,
                    color="epa",
                    color_continuous_scale=epa_color_scale(unit_cfg),
                ),
                height=360,
            ),
            use_container_width=True,
        )
        zone_epa = df.groupby("field_zone")["epa"].mean().reset_index()
        c2.plotly_chart(
            apply_chart_style(
                px.bar(
                    zone_epa,
                    x="field_zone",
                    y="epa",
                    title="EPA by field zone (↑ better)",
                    template=CHART_TEMPLATE,
                    color="epa",
                    color_continuous_scale=epa_color_scale(unit_cfg),
                ),
                height=360,
            ),
            use_container_width=True,
        )


def _render_call_sheet_table(sheet: pd.DataFrame, lean_label: str = "Run/Pass") -> None:
    display = sheet[
        ["situation", "rank", "recommendation", "avg_epa", "plays", "run_pass_lean"]
    ].rename(
        columns={
            "situation": "Situation",
            "rank": "#",
            "recommendation": "Call",
            "avg_epa": "Avg EPA",
            "plays": "n",
            "run_pass_lean": lean_label,
        }
    )
    st.dataframe(display, use_container_width=True, hide_index=True)


def _render_call_sheet_cards(sheet: pd.DataFrame, package_label: str = "Best formation") -> None:
    for situation, group in sheet.groupby("situation", sort=False):
        lean = group.iloc[0]["run_pass_lean"]
        package = group.iloc[0]["top_package"]
        n_plays = group.iloc[0]["situation_plays"]
        with st.expander(f"{situation}  ·  {n_plays} plays  ·  lean {lean}", expanded=False):
            cols = st.columns([1, 4, 1, 1])
            cols[0].markdown("**#**")
            cols[1].markdown("**Call**")
            cols[2].markdown("**EPA**")
            cols[3].markdown("**n**")
            for row in group.itertuples(index=False):
                c0, c1, c2, c3 = st.columns([1, 4, 1, 1])
                c0.write(row.rank)
                c1.write(row.recommendation)
                c2.write(f"{row.avg_epa:+.3f}")
                c3.write(row.plays)
            st.caption(f"{package_label} in this spot: **{package}**")


def play_call_sheet_page(df: pd.DataFrame, unit_cfg: dict) -> None:
    st.header(unit_cfg["call_sheet_title"])
    if unit_cfg["invert_xp"]:
        show_defense_legend()
    st.markdown(
        """
        EPA-ranked calls for common situations — built from **your** season data.
        Use for game-week planning or a booth call sheet.
        """
    )

    c1, c2, c3, c4 = st.columns(4)
    option_labels = list(unit_cfg["sheet_options"].keys())
    sheet_type = c1.selectbox("Recommend", option_labels)
    top_n = c2.selectbox("Calls per situation", [3, 4, 5, 6], index=2)
    min_sit = c3.slider("Min plays in situation", 5, 25, 8 if not unit_cfg["invert_xp"] else 5)
    min_call = c4.slider("Min plays per call", 2, 10, 3 if not unit_cfg["invert_xp"] else 2)

    group_col = unit_cfg["sheet_options"][sheet_type]

    tab_quick, tab_full, tab_zone = st.tabs(["Key situations", "Full sheet", "By field zone"])

    with tab_quick:
        quick = build_call_sheet(
            df,
            group_col,
            min_sit,
            min_call,
            top_n,
            package_col=unit_cfg["package_col"],
            situations=KEY_SITUATIONS,
        )
        if quick.empty:
            st.warning("Not enough data for key situations. Lower the min-play sliders.")
        else:
            st.caption(f"{quick['situation'].nunique()} key situations · top {top_n} calls each")
            _render_call_sheet_cards(quick, unit_cfg["package_label"])
            st.download_button(
                "Download key situations (CSV)",
                quick.to_csv(index=False),
                file_name="call_sheet_key_situations.csv",
                mime="text/csv",
            )

    with tab_full:
        full = build_call_sheet(
            df, group_col, min_sit, min_call, top_n, package_col=unit_cfg["package_col"]
        )
        if full.empty:
            st.warning("No situations meet your filters.")
        else:
            st.caption(f"{full['situation'].nunique()} situations covered")
            display = full[
                [
                    "situation",
                    "rank",
                    "recommendation",
                    "avg_epa",
                    "plays",
                    "run_pass_lean",
                    "top_package",
                ]
            ].rename(
                columns={
                    "situation": "Situation",
                    "rank": "#",
                    "recommendation": "Call",
                    "avg_epa": "Avg EPA",
                    "plays": "n",
                    "run_pass_lean": unit_cfg["lean_label"],
                    "top_package": unit_cfg["package_label"],
                }
            )
            st.dataframe(display, use_container_width=True, hide_index=True)
            st.download_button(
                "Download full call sheet (CSV)",
                display.to_csv(index=False),
                file_name="play_call_sheet.csv",
                mime="text/csv",
            )

    with tab_zone:
        full = build_call_sheet(
            df, group_col, min_sit, min_call, top_n, package_col=unit_cfg["package_col"]
        )
        if full.empty:
            st.warning("No situations meet your filters.")
        else:
            for zone_key, zone_name in ZONE_LABELS.items():
                zone_rows = full[full["field_zone"] == zone_key]
                if zone_rows.empty:
                    continue
                st.subheader(zone_name)
                _render_call_sheet_table(zone_rows, unit_cfg["lean_label"])


def sideline(df: pd.DataFrame, unit_cfg: dict) -> None:
    st.header("Sideline")
    if unit_cfg["invert_xp"]:
        show_defense_legend()
    st.write("Situation in → ranked calls from your season EPA data.")

    c1, c2, c3 = st.columns(3)
    down = c1.selectbox("Down", [1, 2, 3, 4], key="sl_down")
    dist_bucket = c2.selectbox("Distance", ["short", "medium", "long"], key="sl_dist")
    field_zone = c3.selectbox(
        "Field zone",
        ["backed_up", "own_territory", "midfield", "opp_territory", "red_zone"],
        index=2,
        key="sl_zone",
    )
    min_plays = st.slider("Min plays", 3, 15, 5, key="sl_min")

    matched = filter_situation(df, down, dist_bucket, field_zone)
    st.info(f"**{len(matched)}** historical plays in this bucket")

    if matched.empty:
        st.warning("No plays in this bucket.")
        return

    combo_table = avg_epa_table(matched, unit_cfg["combo_col"], min_plays)
    call_table = avg_epa_table(matched, unit_cfg["secondary_group"], min_plays)

    left, right = st.columns(2)
    with left:
        st.subheader(unit_cfg["sideline_left"])
        st.dataframe(combo_table.head(8), use_container_width=True, hide_index=True)
    with right:
        st.subheader(unit_cfg["sideline_right"])
        st.dataframe(call_table.head(8), use_container_width=True, hide_index=True)


def _choice_buttons(label: str, options: list, key_prefix: str, default, labels: dict | None = None) -> object:
    st.markdown(f"**{label}**")
    cols = st.columns(len(options))
    current = st.session_state.get(key_prefix, default)
    for i, option in enumerate(options):
        selected = current == option
        display = labels.get(option, str(option)) if labels else str(option)
        if cols[i].button(
            display,
            key=f"{key_prefix}_{option}",
            type="primary" if selected else "secondary",
            use_container_width=True,
        ):
            st.session_state[key_prefix] = option
            current = option
    return st.session_state.get(key_prefix, default)


def _fmt_most(item: dict | None, empty: str = "—") -> str:
    if not item:
        return empty
    return f"{item['name']} ({item['plays']})"


def _live_spot(label: str, value: str, meta: str = "", accent: bool = False) -> None:
    from html import escape

    accent_cls = " live-spot-accent" if accent else ""
    meta_html = f'<div class="live-spot-meta">{meta}</div>' if meta else ""
    st.markdown(
        f"""
        <div class="live-spot{accent_cls}">
          <div class="live-spot-label">{escape(str(label))}</div>
          <div class="live-spot-value">{escape(str(value))}</div>
          {meta_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _best_epa_row(table: pd.DataFrame, call_col: str) -> tuple[str, float, int] | None:
    if table.empty or call_col not in table.columns:
        return None
    row = table.iloc[0]
    return str(row[call_col]), float(row["avg_epa"]), int(row["plays"])


def _render_live_recs(table: pd.DataFrame, title: str, empty_msg: str, call_col: str | None = None) -> None:
    st.markdown(f"### {title}")
    if table.empty:
        st.warning(empty_msg)
        return
    name_col = call_col or table.columns[0]
    for i, row in enumerate(table.head(3).itertuples(index=False), start=1):
        call_name = getattr(row, name_col)
        score = getattr(row, "mesh_score", row.avg_epa)
        season = getattr(row, "season_epa", row.avg_epa)
        live = getattr(row, "live_adj", 0.0)
        sr = getattr(row, "success_rate", None)
        epa_class = "live-good" if score >= 0 else "live-bad"
        extra = ""
        if abs(live) > 0.01:
            extra = f" · tonight {live:+.2f}"
        sr_txt = f" · succ {float(sr):.0%}" if sr is not None and not (isinstance(sr, float) and np.isnan(sr)) else ""
        st.markdown(
            f"""
            <div class="live-card">
              <div class="live-rank">#{i}</div>
              <div class="live-call">{call_name}</div>
              <div class="live-meta">
                Mesh <span class="{epa_class}">{score:+.3f}</span>
                · season EPA {season:+.3f}{sr_txt}
                · n={int(row.plays)}{extra}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


LIVE_LOG_COLUMNS = [
    "timestamp",
    "opponent",
    "half",
    "unit",
    "down",
    "distance",
    "distance_yards",
    "field_zone",
    "ball_yard",
    "situation",
    "formation",
    "formation_variant",
    "play_call",
    "play_type",
    "run_tag",
    "pass_tag",
    "motion",
    "def_front",
    "coverage",
    "blitz",
    "call",
    "result",
    "yards_gained",
    "end_ball_yard",
    "players_on",
    "lineup",
    "ball_player",
    "touch_role",
    "pass_player",
    "note",
    "film_pending",
    "drive_id",
    "play_n",
]

DRIVE_STATE_FILE = PROJECT_DIR / "data" / "drive_state.json"
LIVE_FAVORITES_FILE = PROJECT_DIR / "data" / "live_favorites.json"
PLAY_TYPES = ["run", "pass", "rpo", "special"]
PLAY_TYPE_LABELS = {"run": "Run", "pass": "Pass", "rpo": "RPO", "special": "Special"}
HT_MIN_SAMPLE = 3  # hide thin tendency cells in halftime boards

ROSTER_FILE = PROJECT_DIR / "data" / "roster.json"
STARTERS_FILE = PROJECT_DIR / "data" / "starters.json"
LINEUP_STATE_FILE = PROJECT_DIR / "data" / "lineup_state.json"
ROSTER_POSITIONS = [
    "QB", "RB", "WR", "TE",
    "LT", "LG", "C", "RG", "RT", "OL",
    "DL", "LB", "DB", "ST", "Other",
]
# Offense formation: skill row, OL row, then QB/RB under the line
FORMATION_OFFENSE_SKILL = [
    {"id": "WR1", "label": "WR", "log_pos": "WR", "eligible": ["WR"]},
    {"id": "WR2", "label": "WR", "log_pos": "WR", "eligible": ["WR"]},
    {"id": "TE", "label": "TE", "log_pos": "TE", "eligible": ["TE"]},
    {"id": "WR3", "label": "WR", "log_pos": "WR", "eligible": ["WR"]},
]
FORMATION_OFFENSE_OL = [
    {"id": "LT", "label": "LT", "log_pos": "LT", "eligible": ["LT", "OL"]},
    {"id": "LG", "label": "LG", "log_pos": "LG", "eligible": ["LG", "OL"]},
    {"id": "C", "label": "C", "log_pos": "C", "eligible": ["C", "OL"]},
    {"id": "RG", "label": "RG", "log_pos": "RG", "eligible": ["RG", "OL"]},
    {"id": "RT", "label": "RT", "log_pos": "RT", "eligible": ["RT", "OL"]},
]
FORMATION_OFFENSE_LINE = FORMATION_OFFENSE_SKILL + FORMATION_OFFENSE_OL  # for starters / slot lists
FORMATION_OFFENSE_BACK = [
    {"id": "QB", "label": "QB", "log_pos": "QB", "eligible": ["QB"]},
    {"id": "RB", "label": "RB", "log_pos": "RB", "eligible": ["RB"]},
]
# Optional package slots (enabled via personnel dropdowns)
FORMATION_EXTRA_WR = [
    {"id": "WR4", "label": "WR", "log_pos": "WR", "eligible": ["WR"]},
    {"id": "WR5", "label": "WR", "log_pos": "WR", "eligible": ["WR"]},
]
FORMATION_EXTRA_RB = [
    {"id": "RB2", "label": "RB", "log_pos": "RB", "eligible": ["RB"]},
    {"id": "RB3", "label": "RB", "log_pos": "RB", "eligible": ["RB"]},
]
FORMATION_EXTRA_TE = [
    {"id": "TE2", "label": "TE", "log_pos": "TE", "eligible": ["TE"]},
    {"id": "TE3", "label": "TE", "log_pos": "TE", "eligible": ["TE"]},
]
FORMATION_EXTRA_OL = [
    {"id": "OL6", "label": "OL6", "log_pos": "OL", "eligible": ["OL", "LT", "LG", "C", "RG", "RT"]},
]
# OL stays in starters / live log for grading, but not GameCast or the booth lineup sheet
OL_SLOT_IDS = {s["id"] for s in FORMATION_OFFENSE_OL} | {s["id"] for s in FORMATION_EXTRA_OL}
OL_LOG_POSITIONS = {"LT", "LG", "C", "RG", "RT", "OL"}
FORMATION_DEFENSE = [
    [
        {"id": "DL1", "label": "DL", "log_pos": "DL", "eligible": ["DL"]},
        {"id": "DL2", "label": "DL", "log_pos": "DL", "eligible": ["DL"]},
        {"id": "DL3", "label": "DL", "log_pos": "DL", "eligible": ["DL"]},
    ],
    [
        {"id": "LB1", "label": "LB", "log_pos": "LB", "eligible": ["LB"]},
        {"id": "LB2", "label": "LB", "log_pos": "LB", "eligible": ["LB"]},
        {"id": "LB3", "label": "LB", "log_pos": "LB", "eligible": ["LB"]},
    ],
    [
        {"id": "DB1", "label": "DB", "log_pos": "DB", "eligible": ["DB"]},
        {"id": "DB2", "label": "DB", "log_pos": "DB", "eligible": ["DB"]},
        {"id": "DB3", "label": "DB", "log_pos": "DB", "eligible": ["DB"]},
    ],
]
EMPTY_SLOT = "— empty —"


def load_drive_state() -> dict:
    empty = {
        "opponent": None,
        "active_drive_id": None,
        "drive_open": False,
        "next_id": 1,
        "last_ended_drive_id": None,
        "undo_stack": [],
    }
    if not DRIVE_STATE_FILE.exists():
        return dict(empty)
    try:
        import json

        raw = json.loads(DRIVE_STATE_FILE.read_text())
        if not isinstance(raw, dict):
            return dict(empty)
        raw.setdefault("undo_stack", [])
        raw.setdefault("last_ended_drive_id", None)
        return raw
    except Exception:
        return dict(empty)


def save_drive_state(state: dict) -> None:
    import json

    DRIVE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DRIVE_STATE_FILE.write_text(json.dumps(state, indent=2))


def archive_and_clear_live_log(*, opponent: str = "", reason: str = "new_game") -> Path | None:
    """
    Copy current live_log.csv into data/live_log_archive/, then write an empty log.
    Archive filename prefers the finished opponent from the log rows (not the next game).
    Returns archive path (or None if there was nothing to archive).
    """
    from file_lock import file_lock
    from live_games import finished_opponent_from_log

    LIVE_LOG_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path: Path | None = None

    with file_lock(LIVE_LOG_FILE):
        rows = 0
        existing = None
        if LIVE_LOG_FILE.exists() and LIVE_LOG_FILE.stat().st_size > 0:
            try:
                existing = pd.read_csv(LIVE_LOG_FILE)
                rows = len(existing)
            except Exception:
                existing = None
            if rows:
                finished = finished_opponent_from_log(existing) or opponent or "log"
                safe_opp = "".join(
                    ch if ch.isalnum() or ch in "-_ " else "_" for ch in str(finished)
                ).strip() or "log"
                archive_path = LIVE_LOG_ARCHIVE_DIR / f"{safe_opp}_{stamp}_{reason}.csv"
                if existing is not None:
                    existing.to_csv(archive_path, index=False)
                else:
                    archive_path.write_bytes(LIVE_LOG_FILE.read_bytes())
        empty = pd.DataFrame(columns=LIVE_LOG_COLUMNS)
        tmp = LIVE_LOG_FILE.with_suffix(".csv.tmp")
        empty.to_csv(tmp, index=False)
        tmp.replace(LIVE_LOG_FILE)
    return archive_path


def list_available_scout_files() -> list[dict]:
    """Named scout exports in data/hudl_exports (optional for Live Track)."""
    try:
        from step2_clean import find_named_scout_files

        return [
            {
                "path": path,
                "opponent": opp,
                "role": role,
                "season": season,
                "label": f"{path.name} · {opp} ({'D' if role.endswith('defense') else 'O'})",
            }
            for path, opp, role, season in find_named_scout_files()
        ]
    except Exception:
        return []


def upsert_scout_plays_from_file(
    path: Path,
    *,
    opponent: str,
    role: str = "opponent_defense",
) -> int:
    """
    Clean one scout workbook and merge into scout_plays (replace that opponent+role).
    Scout is optional — Live Track / HT work without it.
    """
    import sqlite3

    from step2_clean import assign_game_ids, clean_scout_file

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    raw = pd.read_excel(path)
    if "PLAY #" not in raw.columns:
        # Try first sheet as-is; assign_game_ids needs PLAY #
        raise ValueError(f"{path.name} needs a PLAY # column (Hudl export).")
    raw = raw.copy()
    raw["game_id"] = assign_game_ids(raw["PLAY #"])
    cleaned = clean_scout_file(
        raw, opponent, role, path.name, season="current"
    )
    if cleaned is None or cleaned.empty:
        return 0

    DB = PROJECT_DIR / "data" / "football.db"
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        try:
            existing = pd.read_sql("SELECT * FROM scout_plays", conn)
        except Exception:
            existing = pd.DataFrame()
        if not existing.empty and "opponent" in existing.columns and "scout_role" in existing.columns:
            keep = existing[
                ~(
                    (existing["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower())
                    & (existing["scout_role"].astype(str) == role)
                )
            ]
            merged = pd.concat([keep, cleaned], ignore_index=True)
        else:
            merged = cleaned
        merged.to_sql("scout_plays", conn, if_exists="replace", index=False)
    return int(len(cleaned))


def start_new_live_game(
    opponent: str,
    *,
    notes: str = "",
    add_to_schedule: bool = True,
    archive_log: bool = True,
    load_starters_lineup: bool = True,
    scout_path: Path | str | None = None,
    scout_role: str = "opponent_defense",
) -> dict:
    """
    Booth 'Start new game': promote finished live log → Game Review, archive/clear
    live log, reset drive + half, set opponent.
    Scout file is optional (scrimmages / tracking tests).
    """
    from file_lock import file_lock
    from live_games import promote_live_log_to_game_review
    from mesh_engine import save_game_state
    from schedule import add_schedule_game, load_schedule, save_schedule

    name = str(opponent or "").strip()
    if not name:
        raise ValueError("Opponent / game name required.")

    result: dict = {
        "opponent": name,
        "archived": None,
        "promoted": None,
        "scout_rows": 0,
        "schedule_added": False,
        "starters_loaded": False,
    }

    # Promote finished game into Game Review before clearing the live log
    finished_log: pd.DataFrame | None = None
    with file_lock(LIVE_LOG_FILE):
        if LIVE_LOG_FILE.exists() and LIVE_LOG_FILE.stat().st_size > 0:
            try:
                finished_log = pd.read_csv(LIVE_LOG_FILE)
            except Exception:
                finished_log = None
    try:
        result["promoted"] = promote_live_log_to_game_review(finished_log)
    except Exception as exc:
        result["promoted"] = {"promoted": False, "reason": str(exc)}
        result["promote_error"] = str(exc)

    if archive_log:
        result["archived"] = str(
            archive_and_clear_live_log(opponent=name, reason="new_game") or ""
        ) or None
    else:
        # Clear without keeping a copy (explicit)
        with file_lock(LIVE_LOG_FILE):
            empty = pd.DataFrame(columns=LIVE_LOG_COLUMNS)
            tmp = LIVE_LOG_FILE.with_suffix(".csv.tmp")
            empty.to_csv(tmp, index=False)
            tmp.replace(LIVE_LOG_FILE)
        result["archived"] = None

    # Bust Streamlit play-table cache so Game Review graphs pick up the promote
    try:
        st.cache_data.clear()
    except Exception:
        pass
    result["cache_cleared"] = True

    # Fresh drive counter for the night
    save_drive_state(
        {
            "opponent": name,
            "active_drive_id": None,
            "drive_open": False,
            "next_id": 1,
            "last_ended_drive_id": None,
            "undo_stack": [],
        }
    )
    save_game_state(
        {
            "opponent": name,
            "phase": "1st",
            "halftime_at": None,
            "report_path": None,
            "report_md": None,
        }
    )

    if add_to_schedule:
        try:
            sched = load_schedule(None)
            already = {
                str(x).strip().lower()
                for x in (sched["opponent"].tolist() if not sched.empty else [])
            }
            if name.lower() not in already:
                note = str(notes or "").strip() or ("Scrimmage / no scout" if not scout_path else "")
                sched = add_schedule_game(sched, name, notes=note)
                save_schedule(sched, None)
                result["schedule_added"] = True
        except Exception as exc:
            result["schedule_error"] = str(exc)

    if scout_path:
        try:
            n = upsert_scout_plays_from_file(
                Path(scout_path), opponent=name, role=scout_role
            )
            result["scout_rows"] = n
        except Exception as exc:
            result["scout_error"] = str(exc)

    if load_starters_lineup:
        try:
            starters = load_starters().get("offense") or {}
            if starters:
                set_formation_slots(dict(starters))
                result["starters_loaded"] = True
        except Exception:
            pass

    return result


def _reset_live_track_session_for_new_game(opponent: str) -> None:
    """Clear booth situation / HT cache so the new game starts clean."""
    # Widget keys (opponent / half) already exist on this run — apply on next rerun
    st.session_state.lt_page_opponent_pending = opponent
    st.session_state.lt_half_pending = 1
    st.session_state.pop("lt_half_auto_done", None)
    for key in (
        "ht_last_report",
        "ht_last_md",
        "lt_situation_pending",
        "ql_confirm_draft",
        "lt_last_warnings",
    ):
        st.session_state.pop(key, None)
    # Fresh down & distance defaults (those widgets are created after this panel)
    st.session_state.lt_down = 1
    st.session_state.lt_dist_y = 10
    st.session_state.lt_ball_yard = 40
    st.session_state.lt_zone = "own_territory"
    st.session_state.lt_result = "Gain"
    st.session_state.lt_gain = 0
    st.session_state.ql_step = 0
    st.session_state.ig_mode = "1st Half"


def _drive_snapshot(state: dict) -> dict:
    return {
        "opponent": state.get("opponent"),
        "active_drive_id": state.get("active_drive_id"),
        "drive_open": bool(state.get("drive_open")),
        "next_id": state.get("next_id"),
        "last_ended_drive_id": state.get("last_ended_drive_id"),
    }


def _push_drive_undo(state: dict, action: str) -> None:
    stack = list(state.get("undo_stack") or [])
    stack.append({"action": action, "snapshot": _drive_snapshot(state)})
    state["undo_stack"] = stack[-10:]  # keep last 10


def start_drive(opponent: str) -> int:
    """Start a new drive. If one is already open, keep it (no accidental skip)."""
    state = load_drive_state()
    if state.get("drive_open") and state.get("active_drive_id") is not None:
        # Already mid-drive — do not bump to the next id
        return int(state["active_drive_id"])

    _push_drive_undo(state, "start")
    did = int(state.get("next_id") or 1)
    state.update(
        {
            "opponent": opponent,
            "active_drive_id": did,
            "drive_open": True,
            "next_id": did + 1,
            "last_ended_drive_id": state.get("last_ended_drive_id"),
        }
    )
    save_drive_state(state)
    try:
        from booth_snaps import reset_booth_snap_for_drive

        half = int(st.session_state.get("lt_half") or 1)
        reset_booth_snap_for_drive(opponent, did, half=half, play_n=1)
    except Exception:
        pass
    return did


def end_drive() -> int | None:
    state = load_drive_state()
    if not state.get("drive_open"):
        return None
    _push_drive_undo(state, "end")
    did = state.get("active_drive_id")
    state["drive_open"] = False
    state["last_ended_drive_id"] = did
    state["active_drive_id"] = None
    save_drive_state(state)
    return int(did) if did is not None else None


def resume_drive(drive_id: int, opponent: str | None = None) -> int:
    """Re-open an existing drive id (undo accidental Start/End)."""
    state = load_drive_state()
    _push_drive_undo(state, "resume")
    did = int(drive_id)
    state["drive_open"] = True
    state["active_drive_id"] = did
    if opponent:
        state["opponent"] = opponent
    # next_id must stay ahead of any known drive
    try:
        state["next_id"] = max(int(state.get("next_id") or 1), did + 1)
    except (TypeError, ValueError):
        state["next_id"] = did + 1
    save_drive_state(state)
    try:
        from booth_snaps import max_play_n_for_drive, reset_booth_snap_for_drive
        from mesh_engine import load_live_log

        logs = load_live_log()
        max_n = max_play_n_for_drive(logs, did)
        half = int(st.session_state.get("lt_half") or 1)
        reset_booth_snap_for_drive(
            opponent or str(state.get("opponent") or ""),
            did,
            half=half,
            play_n=(max_n + 1) if max_n else 1,
        )
    except Exception:
        pass
    return did


def undo_drive_action() -> dict | None:
    """Restore the previous drive bar state (start/end/resume)."""
    state = load_drive_state()
    stack = list(state.get("undo_stack") or [])
    if not stack:
        return None
    entry = stack.pop()
    snap = entry.get("snapshot") or {}
    state.update(
        {
            "opponent": snap.get("opponent"),
            "active_drive_id": snap.get("active_drive_id"),
            "drive_open": bool(snap.get("drive_open")),
            "next_id": snap.get("next_id", state.get("next_id")),
            "last_ended_drive_id": snap.get("last_ended_drive_id"),
            "undo_stack": stack,
        }
    )
    save_drive_state(state)
    return entry


def known_drive_ids(live_logs: pd.DataFrame | None = None) -> list[int]:
    """Drive ids seen in the live log + current state."""
    ids: set[int] = set()
    state = load_drive_state()
    for key in ("active_drive_id", "last_ended_drive_id"):
        try:
            if state.get(key) is not None:
                ids.add(int(state[key]))
        except (TypeError, ValueError):
            pass
    try:
        nid = int(state.get("next_id") or 1)
        for i in range(1, nid):
            ids.add(i)
    except (TypeError, ValueError):
        pass
    if live_logs is not None and not live_logs.empty and "drive_id" in live_logs.columns:
        for v in live_logs["drive_id"].dropna().unique():
            try:
                ids.add(int(float(v)))
            except (TypeError, ValueError):
                continue
    return sorted(ids)


def reassign_drive_plays(from_id: int, to_id: int) -> int:
    """Move live-log rows from one drive_id to another. Returns rows updated."""
    if int(from_id) == int(to_id):
        return 0
    n_box = {"n": 0}

    def _move(df: pd.DataFrame):
        if "drive_id" not in df.columns:
            return None
        mask = pd.to_numeric(df["drive_id"], errors="coerce") == int(from_id)
        n_box["n"] = int(mask.sum())
        if not n_box["n"]:
            return None
        df.loc[mask, "drive_id"] = int(to_id)
        return df

    ok = _mutate_live_log(_move)
    return n_box["n"] if ok else 0


def current_drive_id(opponent: str | None = None) -> int | None:
    state = load_drive_state()
    if not state.get("drive_open"):
        return None
    if opponent and state.get("opponent"):
        if str(state.get("opponent")).strip().lower() != opponent.strip().lower():
            return None
    return state.get("active_drive_id")


def validate_live_play(
    result: str,
    yards_gained: int | float,
    distance_yards: int | float,
) -> tuple[str, int, list[str]]:
    """
    Coerce inconsistent live tags. Returns (result, yards, warnings).
    """
    warnings: list[str] = []
    r = str(result or "Other")
    try:
        y = int(yards_gained)
    except (TypeError, ValueError):
        y = 0
    try:
        to_go = int(distance_yards)
    except (TypeError, ValueError):
        to_go = 10

    if r == "Incomplete":
        if y != 0:
            warnings.append(f"Incomplete → yards set to 0 (was {y}).")
            y = 0
    elif r == "No gain":
        if y > 0:
            warnings.append("Positive yards with No gain → Result set to Gain.")
            r = "Gain"
        elif y < 0:
            warnings.append("Negative yards with No gain → Result set to Sack / TFL.")
            r = "Sack / TFL"
    elif r == "Gain":
        if y == 0:
            warnings.append("Gain with 0 yards → Result set to No gain.")
            r = "No gain"
        # Negative Gain is allowed (completed pass / catch behind the LOS)
    elif r == "TD":
        if y < max(1, to_go):
            # Still allow (wrong to-go happens), but nudge yards up for consistency
            warnings.append(
                f"TD with {y} yds vs {to_go} to-go — check yards if you can."
            )
        if y <= 0:
            y = max(1, to_go)
            warnings.append(f"TD → yards set to {y}.")
    elif r == "Penalty":
        if y == 0:
            warnings.append("Penalty with 0 yards — set ± yards when you can.")
    elif r == "Sack / TFL":
        if y > 0:
            warnings.append("Sack/TFL with positive yards → Result set to Gain.")
            r = "Gain"
        elif y == 0:
            y = -1
            warnings.append("Sack/TFL with 0 → yards set to −1.")
    elif r == "Turnover":
        pass  # yards can be anything
    return r, int(y), warnings


def favorite_tags(
    live_logs: pd.DataFrame | None,
    column: str,
    opponent: str | None = None,
    *,
    pins: list[str] | None = None,
    learned_kind: str | None = None,
    limit: int = 6,
) -> list[str]:
    """Top taps for one-handed Quick Log: pins → tonight frequency → learned."""
    out: list[str] = []
    seen: set[str] = set()

    def _add(val: str) -> None:
        s = str(val or "").strip()
        if not s or s.lower() in seen or s.lower() in {"(none)", "none", "nan"}:
            return
        if "unknown" in s.lower():
            return
        seen.add(s.lower())
        out.append(s)

    for p in pins or []:
        _add(p)
        if len(out) >= limit:
            return out

    if live_logs is not None and not live_logs.empty and column in live_logs.columns:
        logs = live_logs
        if opponent and "opponent" in logs.columns:
            filt = logs[
                logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
            ]
            if not filt.empty:
                logs = filt
        counts = logs[column].dropna().astype(str).str.strip().value_counts()
        for val in counts.index:
            _add(str(val))
            if len(out) >= limit:
                return out

    if learned_kind:
        for val in _load_learned_tags().get(learned_kind, []):
            _add(val)
            if len(out) >= limit:
                return out
    return out


# Formation suffixes that are alignment variants, not base formations
FORMATION_VARIANT_SUFFIXES = ["STACK BASH", "BASH", "STACK", "QUADS", "WIDE"]


def _empty_live_favorites() -> dict:
    return {
        "formations": [],
        "variants": [],  # global variants (any formation)
        "variants_by_formation": {},  # { "Slot Dip": ["Bash", ...] }
        "motions": [],
        "plays": {t: [] for t in PLAY_TYPES},
        "inbox_plays": [],  # imported but not yet sorted into run/pass/rpo/special
    }


def _clean_fav_list(vals) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in vals or []:
        s = str(v or "").strip()
        if not s or s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
    return out


def load_live_favorites() -> dict:
    """Curated booth favorites: formations, variants, motions, typed plays."""
    empty = _empty_live_favorites()
    if not LIVE_FAVORITES_FILE.exists():
        return empty
    try:
        import json

        raw = json.loads(LIVE_FAVORITES_FILE.read_text())
        if not isinstance(raw, dict):
            return empty
    except Exception:
        return empty

    plays_raw = raw.get("plays") if isinstance(raw.get("plays"), dict) else {}
    plays = {t: _clean_fav_list(plays_raw.get(t)) for t in PLAY_TYPES}
    if not any(plays.values()) and isinstance(raw.get("plays_flat"), list):
        plays["run"] = _clean_fav_list(raw.get("plays_flat"))

    vbf_raw = raw.get("variants_by_formation") if isinstance(raw.get("variants_by_formation"), dict) else {}
    vbf = {str(k).strip(): _clean_fav_list(v) for k, v in vbf_raw.items() if str(k).strip()}

    return {
        "formations": _clean_fav_list(raw.get("formations")),
        "variants": _clean_fav_list(raw.get("variants")),
        "variants_by_formation": vbf,
        "motions": _clean_fav_list(raw.get("motions")),
        "plays": plays,
        "inbox_plays": _clean_fav_list(raw.get("inbox_plays")),
    }


def save_live_favorites(favs: dict) -> None:
    import json

    LIVE_FAVORITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIVE_FAVORITES_FILE.write_text(json.dumps(favs if favs else _empty_live_favorites(), indent=2))
    LIVE_FAVORITES_FILE.write_text(json.dumps(load_live_favorites(), indent=2))


from tag_normalize import normalize_play_call  # shared with ingest


def _tag_display(name: str) -> str:
    """SLOT DIP / FOX RT → Slot Dip / Fox RT."""
    keep_upper = {"RT", "LT", "QB", "RB", "TE", "WR", "OL", "SS", "R", "L"}
    parts = []
    for p in str(name or "").strip().split():
        up = p.upper()
        if up in keep_upper or (len(up) <= 2 and up.isalpha()):
            parts.append(up)
        else:
            parts.append(p.title())
    # Play-call aliases after title-case (Axel → Axle)
    return normalize_play_call(" ".join(parts))


def split_formation_variant(raw: str) -> tuple[str, str]:
    """SLOT TRIG BASH → (Slot Trig, Bash)."""
    s = _ql_norm(raw)
    if not s:
        return "", ""
    up = s.upper()
    for var in FORMATION_VARIANT_SUFFIXES:
        token = f" {var}"
        if up.endswith(token):
            base = s[: -len(var)].strip()
            if base:
                return _tag_display(base), _tag_display(var)
    return _tag_display(s), ""


def _map_db_play_type(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if s in {"run", "r"}:
        return "run"
    if s in {"pass", "p"}:
        return "pass"
    if "rpo" in s:
        return "rpo"
    if s in {"special", "st", "punt", "fg", "kick", "ko", "pat"}:
        return "special"
    return "inbox"


def suggest_offense_favorites(
    offense_df: pd.DataFrame | None,
    *,
    min_form_plays: int = 2,
    min_play_plays: int = 2,
    min_motion_plays: int = 1,
) -> dict:
    """
    Build favorites from our season offense tags.

    - Formations with Bash/Stack/etc. are split into base + variant
    - Plays sorted by Hudl PLAY TYPE into run/pass when known
    - Motions from Hudl MOTION column (season export)
    """
    out = _empty_live_favorites()
    if offense_df is None or offense_df.empty:
        return out

    # Formations: current season only (24-25 scheme is untrusted)
    form_src = current_season_plays(offense_df)
    if "form_tagged" in form_src.columns:
        form_src = form_src[form_src["form_tagged"].fillna(0).astype(int) == 1]

    # --- Formations / variants ---
    form_counts: dict[str, int] = {}
    if "formation" in form_src.columns:
        for val, cnt in (
            form_src["formation"].dropna().astype(str).str.strip().value_counts().items()
        ):
            if not val or "unknown" in val.lower():
                continue
            form_counts[val] = int(cnt)

    vbf: dict[str, list[str]] = {}
    global_vars: list[str] = []
    bases: list[str] = []
    for raw, cnt in sorted(form_counts.items(), key=lambda x: -x[1]):
        if cnt < min_form_plays:
            continue
        base, var = split_formation_variant(raw)
        if not base:
            continue
        bases = _add_favorite_name(bases, base)
        if var:
            global_vars = _add_favorite_name(global_vars, var)
            bucket = list(vbf.get(base) or [])
            vbf[base] = _add_favorite_name(bucket, var)
    out["formations"] = bases
    out["variants"] = global_vars
    out["variants_by_formation"] = vbf

    # --- Plays by type (any season if tagged — includes usable 24-25 play calls) ---
    plays = {t: [] for t in PLAY_TYPES}
    inbox: list[str] = []
    if "play_call" in offense_df.columns:
        tmp = offense_df.copy()
        if "play_tagged" in tmp.columns:
            tmp = tmp[tmp["play_tagged"].fillna(0).astype(int) == 1]
        tmp["_play"] = tmp["play_call"].dropna().astype(str).str.strip()
        tmp = tmp[tmp["_play"].ne("") & ~tmp["_play"].str.contains("unknown", case=False, na=False)]
        if "play_type" in tmp.columns:
            tmp["_ptype"] = tmp["play_type"].map(_map_db_play_type)
        else:
            tmp["_ptype"] = "inbox"
        for play, grp in tmp.groupby("_play"):
            n = len(grp)
            mode = grp["_ptype"].value_counts()
            ptype = str(mode.index[0]) if not mode.empty else "inbox"
            name = _tag_display(str(play))
            # Rare installs (n=1) still go to inbox so phrase log can match (e.g. Big Balls)
            if n < min_play_plays:
                inbox = _add_favorite_name(inbox, name)
                continue
            if ptype in PLAY_TYPES:
                plays[ptype] = _add_favorite_name(plays[ptype], name)
            else:
                inbox = _add_favorite_name(inbox, name)
    out["plays"] = plays
    out["inbox_plays"] = inbox

    # --- Motions from our season Hudl export only (skip opponent scout files) ---
    motions: list[str] = []
    try:
        export_dir = PROJECT_DIR / "data" / "hudl_exports"
        season_paths = [
            p
            for p in sorted(export_dir.glob("*.xlsx"))
            if not p.name.startswith("~")
            and "season" in p.name.lower()
        ]
        for path in season_paths:
            try:
                raw = pd.read_excel(path)
            except Exception:
                continue
            cols = {str(c).strip().upper(): c for c in raw.columns}
            if "MOTION" not in cols:
                continue
            frame = raw
            if "ODK" in cols:
                odk = frame[cols["ODK"]].astype(str).str.upper()
                frame = frame[odk.isin(["O", "OFF", "OFFENSE"])]
            counts = frame[cols["MOTION"]].dropna().astype(str).str.strip().value_counts()
            for val, cnt in counts.items():
                if int(cnt) < min_motion_plays:
                    continue
                if not val or val.lower() in {"nan", "none", "n/a"}:
                    continue
                motions = _add_favorite_name(motions, _tag_display(val))
    except Exception:
        pass
    out["motions"] = motions
    return out


def merge_offense_favorites_into(favs: dict, suggested: dict, *, replace: bool = False) -> dict:
    """Merge season suggestions into curated favorites (or replace)."""
    if replace:
        return suggested
    merged = load_live_favorites() if not favs else {
        "formations": list(favs.get("formations") or []),
        "variants": list(favs.get("variants") or []),
        "variants_by_formation": dict(favs.get("variants_by_formation") or {}),
        "motions": list(favs.get("motions") or []),
        "plays": {t: list((favs.get("plays") or {}).get(t) or []) for t in PLAY_TYPES},
        "inbox_plays": list(favs.get("inbox_plays") or []),
    }
    for name in suggested.get("formations") or []:
        merged["formations"] = _add_favorite_name(merged["formations"], name)
    for name in suggested.get("variants") or []:
        merged["variants"] = _add_favorite_name(merged["variants"], name)
    for name in suggested.get("motions") or []:
        merged["motions"] = _add_favorite_name(merged["motions"], name)
    for form, vars_ in (suggested.get("variants_by_formation") or {}).items():
        bucket = list(merged["variants_by_formation"].get(form) or [])
        for v in vars_ or []:
            bucket = _add_favorite_name(bucket, v)
        merged["variants_by_formation"][form] = bucket
    # Plays: only add if not already in any typed bucket
    already = {p.lower() for t in PLAY_TYPES for p in (merged["plays"].get(t) or [])}
    already |= {p.lower() for p in (merged.get("inbox_plays") or [])}
    for t in PLAY_TYPES:
        for name in (suggested.get("plays") or {}).get(t) or []:
            if name.lower() in already:
                continue
            merged["plays"][t] = _add_favorite_name(merged["plays"][t], name)
            already.add(name.lower())
    for name in suggested.get("inbox_plays") or []:
        if name.lower() in already:
            continue
        merged["inbox_plays"] = _add_favorite_name(merged["inbox_plays"], name)
        already.add(name.lower())
    return merged


def variants_for_formation(favs: dict, formation: str) -> list[str]:
    """Variants for a formation: specific list, else global variants."""
    form = str(formation or "").strip()
    vbf = favs.get("variants_by_formation") or {}
    if form:
        for key, vals in vbf.items():
            if str(key).strip().lower() == form.lower() and vals:
                return list(vals)
    return list(favs.get("variants") or [])


def _add_favorite_name(bucket: list[str], name: str) -> list[str]:
    s = str(name or "").strip()
    if not s:
        return bucket
    if s.lower() in {x.lower() for x in bucket}:
        return bucket
    return bucket + [s]


def _remove_favorite_name(bucket: list[str], name: str) -> list[str]:
    low = str(name or "").strip().lower()
    return [x for x in bucket if x.lower() != low]


def compose_formation_label(formation: str, variant: str = "") -> str:
    form = str(formation or "").strip()
    var = str(variant or "").strip()
    if form and var and var.lower() not in {"base", "(none)", "none", "—"}:
        return f"{form} {var}"
    return form


def append_live_log(row: dict) -> None:
    """Append a play. Fast-path: one CSV line when schema matches; else full rewrite."""
    import csv

    from file_lock import file_lock

    LIVE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(LIVE_LOG_FILE):
        if LIVE_LOG_FILE.exists() and LIVE_LOG_FILE.stat().st_size > 0:
            try:
                with LIVE_LOG_FILE.open("r", encoding="utf-8", newline="") as f:
                    header = next(csv.reader(f), None)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not read {LIVE_LOG_FILE.name} — snap NOT logged "
                    f"(protecting existing plays). Retry. ({exc})"
                ) from exc
            # True append when row adds no new columns (common path under tempo)
            if header and not any(k not in header for k in row.keys()):
                values = []
                for col in header:
                    v = row.get(col, "")
                    if v is None:
                        v = ""
                    elif isinstance(v, float) and pd.isna(v):
                        v = ""
                    values.append(v)
                with LIVE_LOG_FILE.open("a", encoding="utf-8", newline="") as f:
                    csv.writer(f).writerow(values)
                return
            try:
                existing = pd.read_csv(LIVE_LOG_FILE)
            except Exception as exc:
                raise RuntimeError(
                    f"Could not read {LIVE_LOG_FILE.name} — snap NOT logged "
                    f"(protecting existing plays). Retry. ({exc})"
                ) from exc
            existing = _ensure_live_log_text_dtypes(existing)
            combined = pd.concat(
                [existing, _ensure_live_log_text_dtypes(pd.DataFrame([row]))],
                ignore_index=True,
            )
        else:
            combined = _ensure_live_log_text_dtypes(pd.DataFrame([row]))
        ordered = [c for c in LIVE_LOG_COLUMNS if c in combined.columns]
        extras = [c for c in combined.columns if c not in ordered]
        _atomic_live_log_to_csv(combined[ordered + extras])


def _atomic_live_log_to_csv(df: pd.DataFrame) -> None:
    """Write live_log via temp+replace (caller must hold file_lock)."""
    tmp = LIVE_LOG_FILE.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(LIVE_LOG_FILE)


def _rewrite_live_log(df: pd.DataFrame) -> None:
    from file_lock import file_lock

    LIVE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(LIVE_LOG_FILE):
        if df is None or df.empty:
            if LIVE_LOG_FILE.exists():
                LIVE_LOG_FILE.unlink()
            return
        df = _ensure_live_log_text_dtypes(df)
        ordered = [c for c in LIVE_LOG_COLUMNS if c in df.columns]
        extras = [c for c in df.columns if c not in ordered]
        _atomic_live_log_to_csv(df[ordered + extras])


def _mutate_live_log(mutator) -> bool:
    """Read-modify-write live_log under one lock. mutator(df) -> df|None."""
    from file_lock import file_lock

    LIVE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(LIVE_LOG_FILE):
        if not LIVE_LOG_FILE.exists() or LIVE_LOG_FILE.stat().st_size == 0:
            return False
        try:
            existing = pd.read_csv(LIVE_LOG_FILE).reset_index(drop=True)
        except Exception:
            return False
        if existing.empty:
            return False
        existing = _ensure_live_log_text_dtypes(existing)
        out = mutator(existing)
        if out is None:
            return False
        if out.empty:
            LIVE_LOG_FILE.unlink(missing_ok=True)
            return True
        out = _ensure_live_log_text_dtypes(out)
        ordered = [c for c in LIVE_LOG_COLUMNS if c in out.columns]
        extras = [c for c in out.columns if c not in ordered]
        _atomic_live_log_to_csv(out[ordered + extras])
        return True


# Text fields — empty CSV cells become float NaN; must stay object so film tags can write.
LIVE_LOG_TEXT_COLUMNS = {
    "timestamp",
    "opponent",
    "unit",
    "distance",
    "field_zone",
    "situation",
    "formation",
    "formation_variant",
    "play_call",
    "play_type",
    "run_tag",
    "pass_tag",
    "motion",
    "def_front",
    "coverage",
    "blitz",
    "call",
    "result",
    "players_on",
    "lineup",
    "ball_player",
    "touch_role",
    "pass_player",
    "note",
    "film_pending",
}


def _ensure_live_log_text_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Keep film/call columns as object so '' / 'Odd' never hit float64 upcast errors."""
    if df is None or df.empty:
        return df
    out = df
    for col in LIVE_LOG_TEXT_COLUMNS:
        if col not in out.columns:
            continue
        if pd.api.types.is_numeric_dtype(out[col]) or pd.api.types.is_bool_dtype(out[col]):
            out[col] = out[col].astype("object")
        # Normalize NaN → blank string for text tags
        out[col] = out[col].where(out[col].notna(), "")
        out[col] = out[col].astype("object")
    return out


def update_live_log_at(index: int, updates: dict) -> bool:
    """Patch fields on one live_log row by 0-based index."""

    def _patch(existing: pd.DataFrame):
        if index < 0 or index >= len(existing):
            return None
        for key, val in (updates or {}).items():
            if key not in existing.columns:
                existing[key] = pd.Series([""] * len(existing), dtype="object")
            elif key in LIVE_LOG_TEXT_COLUMNS or (
                not isinstance(val, (int, float, bool))
                and val is not None
                and pd.api.types.is_numeric_dtype(existing[key])
            ):
                if pd.api.types.is_numeric_dtype(existing[key]):
                    existing[key] = existing[key].astype("object")
                    existing[key] = existing[key].where(existing[key].notna(), "")
            existing.loc[index, key] = "" if val is None and key in LIVE_LOG_TEXT_COLUMNS else val
        return existing

    return _mutate_live_log(_patch)


def play_needs_film(row: pd.Series | dict) -> bool:
    """True when Sky Coach tags still need to be filled after a quick log."""
    fp = str((row.get("film_pending") if hasattr(row, "get") else "") or "").strip().lower()
    if fp in {"1", "true", "yes", "y"}:
        return True
    if fp in {"0", "false", "no", "n"}:
        return False
    return bool(play_missing_film_fields(row))


def play_missing_film_fields(row: pd.Series | dict) -> set[str]:
    """Which film tags are still empty: front / coverage / blitz."""
    missing: set[str] = set()
    if not str(row.get("def_front", "") or "").strip():
        missing.add("front")
    if not str(row.get("coverage", "") or "").strip():
        missing.add("coverage")
    blitz = str(row.get("blitz", "") or "").strip().lower()
    if blitz not in {"yes", "no"}:
        missing.add("blitz")
    return missing


def play_needs_tag_focuses(row: pd.Series | dict, focuses: list[str] | None) -> bool:
    """True if this play still needs any of the tagger's film focuses."""
    from booth_stations import FILM_FOCUSES

    wanted = FILM_FOCUSES.intersection(focuses or [])
    if not wanted:
        return False
    return bool(play_missing_film_fields(row).intersection(wanted))


def count_film_pending(
    live_logs: pd.DataFrame | None,
    opponent: str | None = None,
    focuses: list[str] | None = None,
) -> int:
    if live_logs is None or live_logs.empty:
        return 0
    logs = live_logs
    if opponent and "opponent" in logs.columns:
        logs = logs[
            logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
        ]
    if logs.empty:
        return 0
    if focuses is not None:
        from booth_stations import FILM_FOCUSES, has_film_focus

        if has_film_focus(focuses):
            film_only = [f for f in focuses if f in FILM_FOCUSES]
            # Subset of film fields → queue is "missing my fields"
            if set(film_only) != FILM_FOCUSES:
                return int(
                    sum(play_needs_tag_focuses(row, focuses) for _, row in logs.iterrows())
                )
    return int(sum(play_needs_film(row) for _, row in logs.iterrows()))


def delete_live_log_at(index: int) -> bool:
    """Delete one play by its 0-based row index in live_log.csv. Returns True if removed."""

    def _drop(existing: pd.DataFrame):
        if index < 0 or index >= len(existing):
            return None
        return existing.drop(index=index).reset_index(drop=True)

    return _mutate_live_log(_drop)


def delete_last_live_log(opponent: str | None = None) -> bool:
    """Remove the most recent play (optionally limited to tonight's opponent)."""
    return delete_last_live_log_info(opponent)[0]


def delete_last_live_log_info(
    opponent: str | None = None,
) -> tuple[bool, int | None, int | None]:
    """
    Remove the most recent play for opponent.
    Returns (ok, drive_id, play_n) of the deleted row when known.
    """
    meta: dict = {"drive_id": None, "play_n": None}

    def _drop_last(existing: pd.DataFrame):
        if opponent and "opponent" in existing.columns:
            mask = existing["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
            hits = existing.index[mask]
            if len(hits) == 0:
                return None
            drop_idx = int(hits[-1])
        else:
            drop_idx = int(existing.index[-1])
        row = existing.loc[drop_idx]
        try:
            if row.get("drive_id") is not None and str(row.get("drive_id")).strip() != "":
                meta["drive_id"] = int(float(row.get("drive_id")))
        except (TypeError, ValueError):
            meta["drive_id"] = None
        try:
            if row.get("play_n") is not None and str(row.get("play_n")).strip() != "":
                meta["play_n"] = int(float(row.get("play_n")))
        except (TypeError, ValueError):
            meta["play_n"] = None
        return existing.drop(index=drop_idx).reset_index(drop=True)

    ok = _mutate_live_log(_drop_last)
    return bool(ok), meta.get("drive_id"), meta.get("play_n")


def _live_log_row_label(row: pd.Series, idx: int) -> str:
    ts = str(row.get("timestamp", ""))[-8:] if row.get("timestamp") is not None else ""
    half = row.get("half", "?")
    unit = row.get("unit", "?")
    down = row.get("down", "")
    call = row.get("play_call") or row.get("call") or ""
    result = row.get("result", "")
    yds = row.get("yards_gained", "")
    return f"#{idx} · H{half} {unit} · {down}d · {call} · {result} {yds}yd · {ts}"


def _render_live_log_delete_controls(opponent: str, key_prefix: str = "lt") -> None:
    """Undo last / edit half / delete a mistaken play."""
    if not LIVE_LOG_FILE.exists():
        return
    try:
        full = pd.read_csv(LIVE_LOG_FILE).reset_index(drop=True)
    except Exception:
        return
    if full.empty:
        return

    opp_mask = (
        full["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
        if "opponent" in full.columns
        else pd.Series([True] * len(full))
    )
    opp_idxs = list(full.index[opp_mask])
    if not opp_idxs:
        return

    st.markdown("#### Fix a mistake")
    u1, u2 = st.columns([1, 2])
    if u1.button("Undo last play", use_container_width=True, key=f"{key_prefix}_undo_last"):
        ok, did, pn = delete_last_live_log_info(opponent)
        if ok:
            # Rewind shared pointer so Main/taggers land on the open slot again
            if did is not None and pn is not None:
                try:
                    from booth_snaps import set_booth_snap_play

                    half = int(st.session_state.get("lt_half") or 1)
                    set_booth_snap_play(
                        int(did),
                        max(1, int(pn)),
                        opponent=opponent,
                        half=half,
                    )
                except Exception:
                    pass
            st.success("Deleted last play.")
            st.rerun()
        else:
            st.error("Nothing to undo.")

    recent = list(reversed(opp_idxs[-40:]))
    labels = {_live_log_row_label(full.loc[i], int(i)): int(i) for i in recent}
    pick = u2.selectbox(
        "Pick a play",
        list(labels.keys()),
        key=f"{key_prefix}_fix_pick",
    )
    idx = labels.get(pick)

    # --- Edit half (mis-tagged 2nd half → 1st half for HT report) ---
    h2_idxs = [
        int(i)
        for i in opp_idxs
        if "half" in full.columns
        and str(full.loc[i].get("half") or "").strip() in {"2", "2.0"}
    ]
    with st.expander(
        f"Edit half ({len(h2_idxs)} tagged 2nd half tonight)",
        expanded=bool(h2_idxs),
    ):
        st.caption(
            "Halftime report only uses **1st half** plays. "
            "Fix accidents here, then regenerate under Live Track → Halftime / end 1st half."
        )
        eh1, eh2, eh3 = st.columns([1, 1, 1])
        new_half = eh1.selectbox(
            "Set selected play to",
            [1, 2],
            format_func=lambda h: f"{h}st half" if h == 1 else f"{h}nd half",
            key=f"{key_prefix}_edit_half_val",
        )
        if eh2.button(
            "Save half on selected",
            type="primary",
            use_container_width=True,
            key=f"{key_prefix}_edit_half_btn",
        ):
            if idx is not None and update_live_log_at(int(idx), {"half": int(new_half)}):
                st.success(f"Play #{idx} → half {new_half}.")
                st.rerun()
            else:
                st.error("Could not update that play.")
        if eh3.button(
            f"Move all H2 → H1 ({len(h2_idxs)})",
            use_container_width=True,
            key=f"{key_prefix}_move_all_h2",
            disabled=not h2_idxs,
            help="Retag every 2nd-half play for this opponent as 1st half.",
        ):
            ok_n = 0
            for i in h2_idxs:
                if update_live_log_at(int(i), {"half": 1}):
                    ok_n += 1
            st.success(f"Moved {ok_n} play(s) to 1st half. Regenerate the Halftime report.")
            st.rerun()

        if h2_idxs:
            st.write("Currently tagged 2nd half:")
            show_h2 = full.loc[h2_idxs].copy()
            cols = [
                c
                for c in [
                    "timestamp",
                    "half",
                    "down",
                    "formation",
                    "play_call",
                    "result",
                    "yards_gained",
                ]
                if c in show_h2.columns
            ]
            st.dataframe(
                show_h2[cols] if cols else show_h2,
                hide_index=True,
                use_container_width=True,
            )

    if st.button(
        "Delete selected play",
        type="secondary",
        use_container_width=True,
        key=f"{key_prefix}_del_btn",
    ):
        if idx is not None and delete_live_log_at(int(idx)):
            st.success(f"Deleted play #{idx}.")
            st.rerun()
        else:
            st.error("Could not delete that play.")


def _normalize_roster_player(p: dict) -> dict:
    """Multi-position support; migrate old single `position` → `positions` list."""
    name = str(p.get("name", "")).strip()
    positions = p.get("positions")
    if not positions:
        legacy = p.get("position")
        positions = [legacy] if legacy else ["Other"]
    if isinstance(positions, str):
        positions = [positions]
    cleaned: list[str] = []
    seen: set[str] = set()
    for pos in positions:
        pos_u = str(pos).strip().upper()
        if pos_u not in ROSTER_POSITIONS:
            pos_u = "Other"
        if pos_u not in seen:
            seen.add(pos_u)
            cleaned.append(pos_u)
    if not cleaned:
        cleaned = ["Other"]
    starter = bool(p.get("starter", False))
    return {"name": name, "positions": cleaned, "starter": starter}


@st.cache_data(show_spinner=False)
def _load_roster_cached(mtime: float, size: int, season_id: str) -> list[dict]:
    """Cached roster JSON; busts when file or active season changes."""
    if not ROSTER_FILE.exists():
        return []
    try:
        import json

        data = json.loads(ROSTER_FILE.read_text())
        sid = season_id
        raw: list = []
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            seasons = data.get("seasons")
            if isinstance(seasons, dict) and seasons:
                bucket = seasons.get(sid) or seasons.get("current")
                if bucket is None and len(seasons) == 1:
                    bucket = next(iter(seasons.values()))
                if isinstance(bucket, dict):
                    raw = bucket.get("players", []) or []
                elif isinstance(bucket, list):
                    raw = bucket
                else:
                    raw = data.get("players", []) or []
            else:
                raw = data.get("players", []) or []
        return [_normalize_roster_player(p) for p in raw if str(p.get("name", "")).strip()]
    except Exception:
        return []


def load_roster() -> list[dict]:
    """Current-season roster only (legacy flat files migrate on save)."""
    current_season_id = _season_api().current_season_id
    if not ROSTER_FILE.exists():
        return []
    try:
        st_info = ROSTER_FILE.stat()
        return list(_load_roster_cached(st_info.st_mtime, st_info.st_size, current_season_id()))
    except Exception:
        return []


def _read_roster_payload() -> dict:
    """Raw roster.json as a seasons-aware dict (empty if missing)."""
    import json

    if not ROSTER_FILE.exists():
        return {"players": [], "seasons": {}, "active_season": "", "season": ""}
    try:
        data = json.loads(ROSTER_FILE.read_text())
    except Exception:
        return {"players": [], "seasons": {}, "active_season": "", "season": ""}
    if isinstance(data, list):
        return {
            "players": data,
            "seasons": {"legacy": {"players": data, "label": "Legacy"}},
            "active_season": "legacy",
            "season": "legacy",
        }
    if not isinstance(data, dict):
        return {"players": [], "seasons": {}, "active_season": "", "season": ""}
    seasons = data.get("seasons") if isinstance(data.get("seasons"), dict) else {}
    if not seasons and data.get("players"):
        sid = str(data.get("active_season") or data.get("season") or "legacy").strip() or "legacy"
        seasons = {sid: {"players": data.get("players") or [], "label": sid}}
    return {
        "players": data.get("players") or [],
        "seasons": seasons,
        "active_season": str(data.get("active_season") or data.get("season") or "").strip(),
        "season": str(data.get("season") or data.get("active_season") or "").strip(),
    }


def list_roster_seasons() -> list[dict]:
    """[{id, label, players, active}] oldest → newest-ish by id string."""
    current_season_id = _season_api().current_season_id
    sid = current_season_id()
    payload = _read_roster_payload()
    seasons = payload.get("seasons") or {}
    rows: list[dict] = []
    seen: set[str] = set()
    for key, bucket in seasons.items():
        key_s = str(key).strip()
        if not key_s or key_s in seen:
            continue
        seen.add(key_s)
        if isinstance(bucket, dict):
            players = bucket.get("players") or []
            label = str(bucket.get("label") or key_s)
        elif isinstance(bucket, list):
            players = bucket
            label = key_s
        else:
            players = []
            label = key_s
        rows.append(
            {
                "id": key_s,
                "label": label,
                "players": len(players) if isinstance(players, list) else 0,
                "active": key_s == sid,
            }
        )
    # Ensure active season appears even before first save
    if sid and sid not in seen:
        rows.append(
            {
                "id": sid,
                "label": _season_api().current_season_label(),
                "players": len(load_roster()),
                "active": True,
            }
        )
    rows.sort(key=lambda r: (not r["active"], str(r["id"])))
    return rows


def load_roster_for_season(season_id: str) -> list[dict]:
    """Players archived under a specific season id (not necessarily active)."""
    want = str(season_id or "").strip()
    if not want:
        return []
    current_season_id = _season_api().current_season_id
    if want == current_season_id() or want.lower() == "current":
        return load_roster()
    payload = _read_roster_payload()
    bucket = (payload.get("seasons") or {}).get(want)
    raw: list = []
    if isinstance(bucket, dict):
        raw = bucket.get("players") or []
    elif isinstance(bucket, list):
        raw = bucket
    return [_normalize_roster_player(p) for p in raw if str(p.get("name", "")).strip()]


def save_roster(players: list[dict]) -> None:
    """Save into the current-season bucket; keep prior seasons archived."""
    import json

    _sc = _season_api()
    current_season_id = _sc.current_season_id
    current_season_label = _sc.current_season_label

    ROSTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    sid = current_season_id()
    normalized = [_normalize_roster_player(p) for p in players if str(p.get("name", "")).strip()]

    seasons: dict = {}
    if ROSTER_FILE.exists():
        try:
            prev = json.loads(ROSTER_FILE.read_text())
            if isinstance(prev, dict) and isinstance(prev.get("seasons"), dict):
                seasons = dict(prev["seasons"])
            elif isinstance(prev, dict) and prev.get("players"):
                old_sid = str(prev.get("season") or prev.get("active_season") or "").strip()
                if old_sid and old_sid != sid:
                    seasons[old_sid] = {"players": prev.get("players") or []}
            elif isinstance(prev, list) and prev:
                seasons["legacy"] = {"players": prev}
        except Exception:
            seasons = {}

    seasons[sid] = {"players": normalized, "label": current_season_label()}
    payload = {
        "active_season": sid,
        "season": sid,
        "players": normalized,
        "seasons": seasons,
    }
    ROSTER_FILE.write_text(json.dumps(payload, indent=2))


def create_season_roster(
    *,
    new_season_id: str,
    new_season_label: str,
    carry_names: list[str] | None = None,
    source_season_id: str | None = None,
    clear_unkept_starters: bool = True,
) -> dict:
    """
    Roll to a new season roster.

    - Snapshots the current roster under its season id (unchanged history)
    - Advances team_config season identity
    - Builds the new active roster from selected carry-over names
    - Players not carried stay in the prior-season archive only (no lineup clutter)
    """
    import json

    new_id = str(new_season_id or "").strip()
    new_label = str(new_season_label or new_id).strip() or new_id
    if not new_id:
        raise ValueError("New season id is required (e.g. 26-27).")

    _sc = _season_api()
    old_id = _sc.current_season_id()
    if new_id.lower() == old_id.lower():
        raise ValueError(f"Season {new_id} is already active. Pick a new id.")

    # Freeze current players into the old season bucket before flipping identity
    current_players = load_roster()
    if current_players:
        save_roster(current_players)

    # Snapshot starters for the season we're leaving (before config flip)
    prior_starters: dict[str, str] = {}
    try:
        prior_starters = dict(load_starters().get("offense") or {})
        if STARTERS_FILE.exists():
            raw = json.loads(STARTERS_FILE.read_text())
            seasons = raw.get("seasons") if isinstance(raw, dict) else {}
            if isinstance(seasons, dict) and old_id in seasons:
                bucket = seasons[old_id]
                if isinstance(bucket, dict) and isinstance(bucket.get("offense"), dict):
                    prior_starters = {
                        str(k): str(v).strip()
                        for k, v in bucket["offense"].items()
                        if str(v).strip()
                    }
            elif isinstance(raw, dict) and isinstance(raw.get("offense"), dict) and not prior_starters:
                prior_starters = {
                    str(k): str(v).strip()
                    for k, v in raw["offense"].items()
                    if str(v).strip()
                }
    except Exception:
        prior_starters = {}

    src_id = str(source_season_id or old_id).strip() or old_id
    source_players = load_roster_for_season(src_id)
    if not source_players and src_id != old_id:
        source_players = current_players

    want = {str(n).strip().lower() for n in (carry_names or []) if str(n).strip()}
    carried: list[dict] = []
    for p in source_players:
        name = str(p.get("name") or "").strip()
        if name.lower() in want:
            carried.append(
                {
                    "name": name,
                    "positions": list(p.get("positions") or ["Other"]),
                    "starter": False,
                }
            )

    _season_api().set_current_season(new_id, new_label)
    try:
        _is_current_season_mask.clear()
    except Exception:
        pass

    save_roster(carried)

    if clear_unkept_starters:
        kept = {p["name"].lower() for p in carried}
        filtered = {
            str(k): str(v).strip()
            for k, v in prior_starters.items()
            if str(v).strip().lower() in kept
        }
        save_starters({"offense": filtered})

    return {
        "old_season": old_id,
        "new_season": new_id,
        "new_label": new_label,
        "source_season": src_id,
        "carried": len(carried),
        "left_behind": max(0, len(source_players) - len(carried)),
    }


def roster_players_at(roster: list[dict], position: str) -> list[dict]:
    return [p for p in roster if position in p.get("positions", [])]


def roster_eligible(roster: list[dict], eligible: list[str]) -> list[dict]:
    """Players eligible for a formation slot (any matching roster position)."""
    want = {e.upper() for e in eligible}
    return [p for p in roster if want & set(p.get("positions", []))]


def _offense_package_counts() -> dict[str, int]:
    """Extra skill / OL slots beyond the base 11 (3 WR, 1 TE, 5 OL, 1 QB, 1 RB)."""
    return {
        "wr": int(st.session_state.get("lt_extra_wr", 0) or 0),
        "rb": int(st.session_state.get("lt_extra_rb", 0) or 0),
        "te": int(st.session_state.get("lt_extra_te", 0) or 0),
        "ol": int(st.session_state.get("lt_extra_ol", 0) or 0),
    }


def _offense_extra_slots() -> list[dict]:
    pkg = _offense_package_counts()
    extras: list[dict] = []
    extras.extend(FORMATION_EXTRA_WR[: max(0, min(2, pkg["wr"]))])
    extras.extend(FORMATION_EXTRA_RB[: max(0, min(2, pkg["rb"]))])
    extras.extend(FORMATION_EXTRA_TE[: max(0, min(2, pkg["te"]))])
    extras.extend(FORMATION_EXTRA_OL[: max(0, min(1, pkg["ol"]))])
    return extras


def _all_formation_slots() -> list[dict]:
    slots = list(FORMATION_OFFENSE_LINE) + list(FORMATION_OFFENSE_BACK) + _offense_extra_slots()
    for row in FORMATION_DEFENSE:
        slots.extend(row)
    return slots


def _prune_slots_to_active(slots: dict[str, str]) -> dict[str, str]:
    valid = {s["id"] for s in _all_formation_slots()}
    return {k: v for k, v in slots.items() if k in valid and str(v).strip()}


def _slot_by_id(slot_id: str) -> dict | None:
    for s in _all_formation_slots():
        if s["id"] == slot_id:
            return s
    # Still resolve known extra templates even if currently disabled (for chip labels)
    for group in (FORMATION_EXTRA_WR, FORMATION_EXTRA_RB, FORMATION_EXTRA_TE, FORMATION_EXTRA_OL):
        for s in group:
            if s["id"] == slot_id:
                return s
    for s in list(FORMATION_OFFENSE_LINE) + list(FORMATION_OFFENSE_BACK):
        if s["id"] == slot_id:
            return s
    for row in FORMATION_DEFENSE:
        for s in row:
            if s["id"] == slot_id:
                return s
    return None


def _load_lineup_state_file() -> dict[str, str]:
    if not LINEUP_STATE_FILE.exists():
        return {}
    try:
        import json

        data = json.loads(LINEUP_STATE_FILE.read_text())
        slots = data.get("slots", data) if isinstance(data, dict) else {}
        if not isinstance(slots, dict):
            return {}
        return {str(k): str(v).strip() for k, v in slots.items() if str(v).strip()}
    except Exception:
        return {}


def _save_lineup_state_file(slots: dict[str, str]) -> None:
    import json

    LINEUP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LINEUP_STATE_FILE.write_text(json.dumps({"slots": slots}, indent=2))


def get_formation_slots() -> dict[str, str]:
    """slot_id → player name. Persists across logged plays until you substitute."""
    if "lt_slots" in st.session_state and isinstance(st.session_state.lt_slots, dict):
        return {
            str(k): str(v)
            for k, v in st.session_state.lt_slots.items()
            if str(v).strip()
        }
    # Restore from disk (survives refresh) before legacy migration
    saved = _load_lineup_state_file()
    if saved:
        st.session_state.lt_slots = saved
        return dict(saved)
    # Migrate old lt_on_field {name: pos} into best-effort slots
    legacy = st.session_state.get("lt_on_field", {})
    slots: dict[str, str] = {}
    if isinstance(legacy, dict) and legacy:
        used: set[str] = set()
        for slot in _all_formation_slots():
            for name, pos in legacy.items():
                if name in used:
                    continue
                if str(pos).upper() in {e.upper() for e in slot["eligible"]} or str(pos).upper() == slot["log_pos"]:
                    slots[slot["id"]] = name
                    used.add(name)
                    break
        for name, pos in legacy.items():
            if name in used:
                continue
            pos_u = str(pos).upper()
            for slot in _all_formation_slots():
                if slot["id"] in slots:
                    continue
                if pos_u == "WR" and slot["log_pos"] == "WR":
                    slots[slot["id"]] = name
                    used.add(name)
                    break
                if pos_u == "OL" and slot["log_pos"] in {"LT", "LG", "C", "RG", "RT"}:
                    slots[slot["id"]] = name
                    used.add(name)
                    break
                if pos_u == slot["log_pos"]:
                    slots[slot["id"]] = name
                    used.add(name)
                    break
    st.session_state.lt_slots = slots
    return slots


def set_formation_slots(slots: dict[str, str]) -> None:
    """Update lineup. Does not clear on log — only when you edit / clear / starters."""
    cleaned = {
        str(k): str(v).strip() for k, v in slots.items() if str(v).strip()
    }
    # Drop only slots that are not in the current package (extras turned off)
    cleaned = _prune_slots_to_active(cleaned)
    st.session_state.lt_slots = cleaned
    _save_lineup_state_file(cleaned)
    on_field: dict[str, str] = {}
    for slot_id, name in cleaned.items():
        spec = _slot_by_id(slot_id)
        if spec:
            on_field[name] = spec["log_pos"]
    st.session_state.lt_on_field = on_field


def get_on_field(*, include_ol: bool = True) -> dict[str, str]:
    """
    name → active log position (from formation slots).

    include_ol=False → skill / QB / RB only (active booth lineup & GameCast picks).
    OL still stays in slots + logged snaps for grading when include_ol=True (default).
    """
    slots = get_formation_slots()
    on_field: dict[str, str] = {}
    for slot_id, name in slots.items():
        if not include_ol and _is_ol_slot(slot_id):
            continue
        spec = _slot_by_id(slot_id)
        if spec and name:
            on_field[name] = spec["log_pos"]
    if include_ol:
        st.session_state.lt_on_field = on_field
    return on_field


def set_on_field(on_field: dict[str, str]) -> None:
    """Legacy helper — prefer set_formation_slots. Clears if empty."""
    if not on_field:
        set_formation_slots({})
        return
    st.session_state.lt_on_field = {
        str(k): str(v or "").strip().upper() for k, v in on_field.items() if str(k).strip()
    }


def assign_formation_slot(slots: dict[str, str], slot_id: str, player: str) -> dict[str, str]:
    """Put player in slot_id; remove them from any other slot. Empty clears the slot."""
    out = {k: v for k, v in slots.items() if k != slot_id and v != player}
    if player and player != EMPTY_SLOT:
        out[slot_id] = player
    return out


def _bump_slot_widgets() -> None:
    """Force formation selectboxes to resync after Clear / Starters."""
    st.session_state.lt_slot_gen = int(st.session_state.get("lt_slot_gen", 0)) + 1


def load_starters() -> dict[str, dict[str, str]]:
    """Saved starting lineup for the current season."""
    current_season_id = _season_api().current_season_id

    if not STARTERS_FILE.exists():
        return {"offense": {}}
    try:
        import json

        raw = json.loads(STARTERS_FILE.read_text())
        if not isinstance(raw, dict):
            return {"offense": {}}
        sid = current_season_id()
        offense: dict = {}
        seasons = raw.get("seasons")
        if isinstance(seasons, dict) and seasons:
            bucket = seasons.get(sid) or seasons.get("current")
            if isinstance(bucket, dict):
                offense = bucket.get("offense") if isinstance(bucket.get("offense"), dict) else bucket
            if not isinstance(offense, dict):
                offense = {}
        else:
            offense = raw.get("offense") if isinstance(raw.get("offense"), dict) else {}
        cleaned = {
            str(k): str(v).strip()
            for k, v in (offense or {}).items()
            if str(v).strip()
        }
        return {"offense": cleaned}
    except Exception:
        return {"offense": {}}


def save_starters(data: dict) -> None:
    import json

    _sc = _season_api()
    current_season_id = _sc.current_season_id
    current_season_label = _sc.current_season_label

    offense = data.get("offense") if isinstance(data, dict) else {}
    if not isinstance(offense, dict):
        offense = {}
    cleaned = {
        str(k): str(v).strip()
        for k, v in offense.items()
        if str(v).strip()
    }
    sid = current_season_id()
    seasons: dict = {}
    if STARTERS_FILE.exists():
        try:
            prev = json.loads(STARTERS_FILE.read_text())
            if isinstance(prev, dict) and isinstance(prev.get("seasons"), dict):
                seasons = dict(prev["seasons"])
            elif isinstance(prev, dict) and isinstance(prev.get("offense"), dict):
                old_sid = str(prev.get("season") or prev.get("active_season") or "").strip()
                if old_sid and old_sid != sid:
                    seasons[old_sid] = {"offense": prev.get("offense") or {}}
        except Exception:
            seasons = {}

    seasons[sid] = {"offense": cleaned, "label": current_season_label()}
    STARTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STARTERS_FILE.write_text(
        json.dumps(
            {
                "active_season": sid,
                "season": sid,
                "offense": cleaned,
                "seasons": seasons,
            },
            indent=2,
        )
    )


def _starters_for_side(roster: list[dict], side: str = "Offense") -> dict[str, str]:
    """Prefer saved starters.json; else roster players flagged starter; else first eligible."""
    if side != "Offense":
        side = "Offense"  # offense-only product for now
    saved = load_starters().get("offense") or {}
    if saved:
        return dict(saved)

    slot_list = list(FORMATION_OFFENSE_LINE) + list(FORMATION_OFFENSE_BACK) + _offense_extra_slots()
    used: set[str] = set()
    starters: dict[str, str] = {}
    flagged = [p for p in roster if p.get("starter")]
    pool = flagged + [p for p in roster if not p.get("starter")]
    for slot in slot_list:
        for p in roster_eligible(pool, slot["eligible"]):
            name = p["name"]
            if name in used:
                continue
            starters[slot["id"]] = name
            used.add(name)
            break
    return starters


def match_roster_name(query: str, roster: list[dict]) -> str | None:
    """Match full name, last name, or first name (unique only)."""
    q = str(query or "").strip().lower()
    if not q:
        return None
    names = [str(p.get("name") or "").strip() for p in roster if str(p.get("name") or "").strip()]
    for n in names:
        if n.lower() == q:
            return n
    last_hits = [n for n in names if n.split()[-1].lower() == q]
    if len(last_hits) == 1:
        return last_hits[0]
    first_hits = [n for n in names if n.split()[0].lower() == q]
    if len(first_hits) == 1:
        return first_hits[0]
    # partial unique contains
    contains = [n for n in names if q in n.lower()]
    if len(contains) == 1:
        return contains[0]
    return None


def parse_sub_phrase(
    phrase: str,
    roster: list[dict],
    slots: dict[str, str],
) -> dict:
    """
    Parse a booth sub command.

    Examples:
      'sub Cheatham for Tyse at WR'
      'sub Jonathan for Lennon'
      'Cheatham in for Tyse at receiver'
    """
    import re

    out: dict = {
        "in_name": "",
        "out_name": "",
        "slot_id": "",
        "position": "",
        "error": "",
        "ok": False,
    }
    raw = str(phrase or "").strip()
    if not raw:
        out["error"] = "Empty sub command."
        return out
    work = re.sub(r"[,;:]+", " ", raw)
    work = re.sub(r"\s+", " ", work).strip()
    low = work.lower()

    # Normalize position words
    pos_aliases = {
        "receiver": "WR",
        "receivers": "WR",
        "wideout": "WR",
        "wide": "WR",
        "wr": "WR",
        "tight": "TE",
        "te": "TE",
        "end": "TE",
        "back": "RB",
        "rb": "RB",
        "running": "RB",
        "qb": "QB",
        "quarterback": "QB",
        "lt": "LT",
        "lg": "LG",
        "center": "C",
        "rg": "RG",
        "rt": "RT",
        "ol": "OL",
    }

    m = re.search(
        r"^(?:sub(?:stitute)?|swap)\s+(.+?)\s+for\s+(.+?)(?:\s+at\s+(.+))?$",
        work,
        flags=re.I,
    )
    if not m:
        m = re.search(
            r"^(.+?)\s+in\s+for\s+(.+?)(?:\s+at\s+(.+))?$",
            work,
            flags=re.I,
        )
    if not m:
        out["error"] = 'Try: "sub Cheatham for Tyse at WR"'
        return out

    in_q, out_q = m.group(1).strip(), m.group(2).strip()
    pos_q = (m.group(3) or "").strip()
    in_name = match_roster_name(in_q, roster)
    out_name = match_roster_name(out_q, roster)
    if not in_name:
        out["error"] = f'Could not match incoming player "{in_q}".'
        return out
    if not out_name:
        out["error"] = f'Could not match outgoing player "{out_q}".'
        return out
    if in_name == out_name:
        out["error"] = "In and out are the same player."
        return out

    pos = ""
    if pos_q:
        pos = pos_aliases.get(pos_q.lower(), pos_q.upper())

    # Prefer the slot where the outgoing player currently is
    slot_id = ""
    for sid, name in (slots or {}).items():
        if name == out_name:
            spec = _slot_by_id(sid)
            if not pos or (spec and spec.get("log_pos") == pos) or (
                spec and pos in (spec.get("eligible") or [])
            ):
                slot_id = sid
                break
    if not slot_id and pos:
        # First empty or any slot matching position
        for slot in list(FORMATION_OFFENSE_LINE) + list(FORMATION_OFFENSE_BACK) + _offense_extra_slots():
            if slot.get("log_pos") == pos or pos in (slot.get("eligible") or []):
                if not slots.get(slot["id"]) or slots.get(slot["id"]) == out_name:
                    slot_id = slot["id"]
                    break
        if not slot_id:
            for slot in list(FORMATION_OFFENSE_LINE) + list(FORMATION_OFFENSE_BACK) + _offense_extra_slots():
                if slot.get("log_pos") == pos or pos in (slot.get("eligible") or []):
                    slot_id = slot["id"]
                    break
    if not slot_id:
        # Fallback: wherever out player is standing
        for sid, name in (slots or {}).items():
            if name == out_name:
                slot_id = sid
                break
    if not slot_id:
        out["error"] = f"{out_name} is not on the field — set lineup or name the spot (at WR)."
        return out

    out.update(
        {
            "in_name": in_name,
            "out_name": out_name,
            "slot_id": slot_id,
            "position": pos or ((_slot_by_id(slot_id) or {}).get("log_pos") or ""),
            "ok": True,
        }
    )
    return out


def apply_sub_phrase(phrase: str) -> dict:
    """Parse + apply a sub to the live formation slots."""
    roster = load_roster()
    slots = get_formation_slots()
    parsed = parse_sub_phrase(phrase, roster, slots)
    if not parsed.get("ok"):
        return parsed
    new_slots = assign_formation_slot(
        slots, parsed["slot_id"], parsed["in_name"]
    )
    set_formation_slots(new_slots)
    _bump_slot_widgets()
    parsed["message"] = (
        f"Subbed {parsed['in_name']} in for {parsed['out_name']} "
        f"at {parsed.get('position') or parsed['slot_id']}."
    )
    return parsed


def _render_formation_slot(
    slot: dict,
    roster: list[dict],
    slots: dict[str, str],
    side: str,
) -> None:
    """Active name + depth dropdown. Lineup stays put until the coach changes a spot."""
    slot_id = slot["id"]
    label = slot["label"]
    active = slots.get(slot_id, "")
    eligible = roster_eligible(roster, slot["eligible"])
    eligible_names = [p["name"] for p in eligible]
    options = [EMPTY_SLOT] + eligible_names
    if active and active not in options:
        options.insert(1, active)

    elsewhere = {
        n: (_slot_by_id(sid) or {}).get("log_pos", "?")
        for sid, n in slots.items()
        if sid != slot_id and n
    }

    def _fmt(name: str) -> str:
        if name == EMPTY_SLOT:
            return name
        if name in elsewhere and name != active:
            return f"{name} (at {elsewhere[name]})"
        return name

    st.markdown(
        f'<div class="dc-pos-col"><div class="dc-pos-label">{label}</div>',
        unsafe_allow_html=True,
    )

    gen = int(st.session_state.get("lt_slot_gen", 0))
    key = f"lt_slot_{side}_{slot_id}_g{gen}"
    desired = active if active in options else EMPTY_SLOT
    # Initialize from lineup truth once per widget key — never wipe lt_slots from a stale empty widget
    if key not in st.session_state:
        st.session_state[key] = desired

    def _on_slot_change(sid: str = slot_id, widget_key: str = key) -> None:
        choice = st.session_state.get(widget_key, EMPTY_SLOT)
        chosen = "" if choice == EMPTY_SLOT else str(choice)
        current = dict(st.session_state.get("lt_slots") or {})
        set_formation_slots(assign_formation_slot(current, sid, chosen))

    st.selectbox(
        f"{label} depth",
        options,
        key=key,
        label_visibility="collapsed",
        format_func=_fmt,
        on_change=_on_slot_change,
    )
    st.markdown("</div>", unsafe_allow_html=True)
def live_play_value(result: str, yards_gained: float = 0.0, unit: str = "Offense") -> float:
    """Rough live +/- for a snap (basketball-style), not full EPA."""
    r = str(result)
    offense_map = {
        "TD": 1.5,
        "Gain": 0.6,
        "No gain": -0.15,
        "Incomplete": -0.35,
        "Sack / TFL": -0.9,
        "Turnover": -1.5,
        "Punt": -0.4,
        "Penalty": -0.2,
        "Other": 0.0,
    }
    defense_map = {
        "TD": -1.5,
        "Gain": -0.6,
        "No gain": 0.4,
        "Incomplete": 0.5,
        "Sack / TFL": 1.0,
        "Turnover": 1.5,
        "Punt": 0.6,
        "Penalty": 0.1,
        "Other": 0.0,
    }
    base = (offense_map if unit.lower() == "offense" else defense_map).get(r, 0.0)
    # Small yard nudge for gains
    try:
        y = float(yards_gained)
    except (TypeError, ValueError):
        y = 0.0
    if unit.lower() == "offense" and r == "Gain":
        base += min(0.4, max(0.0, y) / 25.0)
    if unit.lower() == "defense" and r == "Gain":
        base -= min(0.4, max(0.0, y) / 25.0)
    return round(base, 3)


def ol_play_grade(result: str, yards_gained: float = 0.0) -> float:
    """
    OL unit grade for a snap: reward chunk runs / TD, ding sacks & TFLs.
    Shared across the line on that play (overall grade, not individual technique).
    """
    r = str(result or "").strip()
    try:
        y = float(yards_gained or 0)
    except (TypeError, ValueError):
        y = 0.0
    if r == "TD":
        return 1.5
    if r == "Sack / TFL":
        return -1.25
    if r == "Turnover":
        return -0.75
    if r == "No gain":
        return -0.2
    if r == "Gain":
        if y >= 20:
            return 1.25
        if y >= 10:
            return 0.9
        if y >= 5:
            return 0.45
        if y > 0:
            return 0.15
        return -0.1
    if r == "Incomplete":
        return 0.0  # usually not on the OL
    if r == "Penalty":
        return -0.35
    return 0.0


def ol_grade_table(
    live_logs: pd.DataFrame,
    opponent: str | None = None,
) -> pd.DataFrame:
    """Per-OL overall grade from snaps they were logged on (lineup / players_on)."""
    cols = [
        "player",
        "pos",
        "snaps",
        "grade",
        "avg",
        "big_runs",
        "sacks_tfl",
        "tds",
    ]
    if live_logs is None or live_logs.empty or "players_on" not in live_logs.columns:
        return pd.DataFrame(columns=cols)
    logs = live_logs.copy()
    if opponent and "opponent" in logs.columns:
        filt = logs[
            logs["opponent"].astype(str).str.strip().str.lower()
            == opponent.strip().lower()
        ]
        if not filt.empty:
            logs = filt
    if "unit" in logs.columns:
        logs = logs[logs["unit"].astype(str).str.strip().str.lower() == "offense"]
    tallies: dict[tuple[str, str], dict] = {}
    for _, row in logs.iterrows():
        players = parse_players_on(str(row.get("players_on", "") or ""))
        ol_on = [(n, p) for n, p in players if _is_ol_log_pos(p)]
        if not ol_on:
            continue
        result = str(row.get("result", ""))
        try:
            yds = float(row.get("yards_gained", 0) or 0)
        except (TypeError, ValueError):
            yds = 0.0
        grade = ol_play_grade(result, yds)
        big = result == "Gain" and yds >= 10
        sack = result == "Sack / TFL"
        td = result == "TD"
        for name, pos in ol_on:
            key = (name, pos or "OL")
            t = tallies.setdefault(
                key,
                {
                    "snaps": 0,
                    "grade": 0.0,
                    "big_runs": 0,
                    "sacks_tfl": 0,
                    "tds": 0,
                },
            )
            t["snaps"] += 1
            t["grade"] += grade
            if big:
                t["big_runs"] += 1
            if sack:
                t["sacks_tfl"] += 1
            if td:
                t["tds"] += 1
    if not tallies:
        return pd.DataFrame(columns=cols)
    rows = []
    for (name, pos), vals in tallies.items():
        snaps = int(vals["snaps"])
        total = float(vals["grade"])
        rows.append(
            {
                "player": name,
                "pos": pos,
                "snaps": snaps,
                "grade": round(total, 2),
                "avg": round(total / snaps, 2) if snaps else 0.0,
                "big_runs": int(vals["big_runs"]),
                "sacks_tfl": int(vals["sacks_tfl"]),
                "tds": int(vals["tds"]),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["grade", "snaps"], ascending=[False, False])
        .reset_index(drop=True)
    )


def parse_players_on_token(token: str) -> tuple[str, str]:
    """Parse 'Smith@WR' or legacy 'Smith' → (name, active_pos). Empty pos if unknown."""
    t = token.strip()
    if not t:
        return "", ""
    if "@" in t:
        name, pos = t.rsplit("@", 1)
        return name.strip(), pos.strip().upper()
    return t, ""


def parse_players_on(raw: str) -> list[tuple[str, str]]:
    """Parse live-log players_on into (name, active_position) pairs."""
    out: list[tuple[str, str]] = []
    for part in str(raw or "").replace("|", ";").split(";"):
        name, pos = parse_players_on_token(part)
        if name:
            out.append((name, pos))
    return out


def format_players_on(on_field: dict[str, str]) -> str:
    """Serialize {name: active_pos} for the live log."""
    parts = []
    for name in sorted(on_field.keys()):
        pos = str(on_field.get(name, "") or "").strip().upper()
        parts.append(f"{name}@{pos}" if pos else name)
    return ";".join(parts)


def format_lineup_slots(slots: dict[str, str] | None = None) -> str:
    """Formation snapshot: WR1:Smith@WR;LT:Jones@LT;… for CSV tracking."""
    if slots is None:
        slots = get_formation_slots()
    order = {s["id"]: i for i, s in enumerate(_all_formation_slots())}
    parts: list[str] = []
    for sid, name in sorted(slots.items(), key=lambda kv: order.get(kv[0], 999)):
        if not name:
            continue
        spec = _slot_by_id(sid) or {}
        label = spec.get("label") or sid
        log_pos = spec.get("log_pos") or ""
        # Slot id keeps WR1/WR2 distinct; log_pos is the +/- bucket
        parts.append(f"{sid}:{name}@{log_pos or label}")
    return ";".join(parts)


def player_plus_minus_table(
    live_logs: pd.DataFrame,
    opponent: str | None = None,
    by_position: bool = True,
) -> pd.DataFrame:
    """+/- while on field. by_position=True splits dual-threats by active @POS."""
    cols = ["player", "active_pos", "snaps", "plus_minus", "net_yards", "good", "bad"]
    if live_logs is None or live_logs.empty or "players_on" not in live_logs.columns:
        return pd.DataFrame(columns=cols)
    logs = live_logs.copy()
    if opponent and "opponent" in logs.columns:
        filt = logs[logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()]
        if not filt.empty:
            logs = filt
    tallies: dict[tuple[str, str], dict] = {}
    for _, row in logs.iterrows():
        players = parse_players_on(str(row.get("players_on", "") or ""))
        if not players:
            continue
        unit = str(row.get("unit", "Offense"))
        result = str(row.get("result", ""))
        try:
            yds = float(row.get("yards_gained", 0) or 0)
        except (TypeError, ValueError):
            yds = 0.0
        val = live_play_value(result, yds, unit)
        offense_good = result in {"Gain", "TD"}
        defense_good = result in {"Incomplete", "Sack / TFL", "Turnover", "No gain", "Punt"}
        good = offense_good if unit.lower() == "offense" else defense_good
        for name, pos in players:
            key_pos = pos if by_position else ""
            key = (name, key_pos)
            t = tallies.setdefault(
                key, {"snaps": 0, "plus_minus": 0.0, "net_yards": 0.0, "good": 0, "bad": 0}
            )
            t["snaps"] += 1
            t["plus_minus"] += val
            t["net_yards"] += yds if unit.lower() == "offense" else -yds
            if good:
                t["good"] += 1
            elif result not in {"Penalty", "Other", ""}:
                t["bad"] += 1
    if not tallies:
        return pd.DataFrame(columns=cols)
    rows = [
        {"player": name, "active_pos": pos or "—", **vals}
        for (name, pos), vals in tallies.items()
    ]
    out = pd.DataFrame(rows)
    out["plus_minus"] = out["plus_minus"].round(2)
    out["net_yards"] = out["net_yards"].round(0)
    if by_position:
        return out.sort_values(
            ["player", "plus_minus", "snaps"], ascending=[True, False, False]
        ).reset_index(drop=True)
    return out.sort_values(
        ["plus_minus", "snaps"], ascending=[False, False]
    ).reset_index(drop=True)


def lineup_slot_player(slot_id: str = "QB", slots: dict[str, str] | None = None) -> str:
    """Player currently in a formation slot (default QB)."""
    try:
        cur = slots if slots is not None else get_formation_slots()
    except Exception:
        cur = slots or {}
    return str((cur or {}).get(slot_id) or "").strip()


def resolve_pass_player(
    *,
    pass_player: str = "",
    play_type: str = "",
    touch_role: str = "",
    result: str = "",
    phrase: str = "",
    outcome_lane: str = "",
    slots: dict[str, str] | None = None,
) -> str:
    """
    Who threw it — explicit phrase/UI, else on-field QB on pass snaps.

    Sacks / incompletes / INTs still credit the QB so counting stats stay complete.
    """
    explicit = str(pass_player or "").strip()
    role = str(touch_role or "").strip().lower()
    ptype = str(play_type or "").strip().lower()
    res = str(result or "").strip()
    lane = str(outcome_lane or "").strip().lower()
    if lane not in {"run", "pass"}:
        lane = detect_outcome_lane(phrase=phrase, result=res, touch_role=role)

    is_pass = (
        ptype == "pass"
        or role == "target"
        or res == "Incomplete"
        or lane == "pass"
    )

    if explicit and explicit.lower() not in {"nan", "none", "—"}:
        # UI may pre-fill QB — drop it on pure runs / carries
        if not is_pass:
            return ""
        return explicit

    if not is_pass:
        return ""
    # Scrambles / QB keeps are rushes — no auto pass credit
    if role == "carry":
        return ""
    return lineup_slot_player("QB", slots)


def _blank_skill_tally() -> dict:
    return {
        "touches": 0,
        "targets": 0,
        "receptions": 0,
        "carries": 0,
        "rush_yds": 0.0,
        "rec_yds": 0.0,
        "rush_td": 0,
        "rec_td": 0,
        "cmp": 0,
        "att": 0,
        "pass_yds": 0.0,
        "pass_td": 0,
        "ints": 0,
        "sacks": 0,
        "yards": 0.0,
        "tds": 0,
        "total_value": 0.0,
    }


def player_skill_stats_table(
    live_logs: pd.DataFrame,
    opponent: str | None = None,
) -> pd.DataFrame:
    """
    Skill-position counting stats for per-player EPA work.

    Pass (QB): cmp / att / pass_yds / pass_td / int / sacks
    Rush: carries / rush_yds / rush_td
    Rec: targets / receptions / rec_yds / rec_td
    """
    cols = [
        "player",
        "cmp",
        "att",
        "pass_yds",
        "pass_td",
        "ints",
        "sacks",
        "carries",
        "rush_yds",
        "rush_td",
        "targets",
        "receptions",
        "rec_yds",
        "rec_td",
        "touches",
        "yards",
        "tds",
        "avg_value",
        "total_value",
    ]
    if live_logs is None or live_logs.empty:
        return pd.DataFrame(columns=cols)
    logs = live_logs.copy()
    if opponent and "opponent" in logs.columns:
        filt = logs[
            logs["opponent"].astype(str).str.strip().str.lower()
            == opponent.strip().lower()
        ]
        if not filt.empty:
            logs = filt
    tallies: dict[str, dict] = {}

    def _tally(name: str) -> dict:
        return tallies.setdefault(name, _blank_skill_tally())

    for _, row in logs.iterrows():
        result = str(row.get("result") or "")
        ptype = str(row.get("play_type") or "").strip().lower()
        role = str(row.get("touch_role") or "").strip().lower()
        try:
            yds = float(row.get("yards_gained", 0) or 0)
        except (TypeError, ValueError):
            yds = 0.0
        unit = str(row.get("unit") or "Offense")
        val = live_play_value(result, yds, unit)

        bp = str(row.get("ball_player") or "").strip()
        if bp.lower() in {"nan", "none", "—"}:
            bp = ""
        pp = str(row.get("pass_player") or "").strip()
        if pp.lower() in {"nan", "none", "—"}:
            pp = ""

        if bp and not role:
            role = infer_touch_role(ptype, result, bp)

        # --- Receiving / rushing (ball guy) ---
        if bp:
            t = _tally(bp)
            t["touches"] += 1
            t["yards"] += yds
            t["total_value"] += val
            if role == "target":
                t["targets"] += 1
                if result not in {"Incomplete", "Turnover"}:
                    t["receptions"] += 1
                    t["rec_yds"] += yds
                    if result == "TD":
                        t["rec_td"] += 1
                        t["tds"] += 1
            elif role == "carry":
                t["carries"] += 1
                t["rush_yds"] += yds
                if result == "TD":
                    t["rush_td"] += 1
                    t["tds"] += 1
            elif result == "TD":
                t["tds"] += 1

        # --- Passing (QB / explicit passer) ---
        if not pp:
            # Legacy rows: infer QB from lineup string when this was a pass snap
            if ptype == "pass" or role == "target" or result == "Incomplete":
                lineup = str(row.get("lineup") or "")
                import re

                m_qb = re.search(r"(?:^|;)\s*QB:([^;@]+)", lineup)
                if m_qb:
                    pp = m_qb.group(1).strip()
        if not pp:
            continue

        # Don't double-count QB value if they also had the ball (scramble)
        t = _tally(pp)
        if not bp or bp.lower() != pp.lower():
            t["total_value"] += val

        if result == "Sack / TFL" and (ptype == "pass" or role == "target"):
            t["sacks"] += 1
            continue
        if result == "Penalty" or result == "Punt":
            continue

        is_pass_stat = (
            ptype == "pass"
            or role == "target"
            or result == "Incomplete"
            or (bool(pp) and result == "Turnover" and role != "carry")
        )
        # Scramble / designed QB run: ball on QB as carry → rush only
        if role == "carry" and bp and bp.lower() == pp.lower():
            is_pass_stat = False
        if not is_pass_stat and result not in {"Incomplete", "Turnover"}:
            continue
        if result == "Turnover" and role == "carry":
            continue

        # Attempt = completion + incompletion + INT (not sack)
        if result != "Sack / TFL":
            t["att"] += 1
        if result == "Incomplete":
            continue
        if result == "Turnover":
            t["ints"] += 1
            continue
        # Completion (Gain / No gain / TD / Other on a throw)
        t["cmp"] += 1
        t["pass_yds"] += yds
        if result == "TD":
            t["pass_td"] += 1
            # Pass TD already counted on receiver rec_td; QB gets pass_td only
            if not bp or bp.lower() != pp.lower():
                pass  # qb tds tracked via pass_td
            t["tds"] += 1  # total scoring plays credited to passer

    if not tallies:
        return pd.DataFrame(columns=cols)
    rows = []
    for name, vals in tallies.items():
        # Skip pure empty
        if (
            vals["att"]
            + vals["carries"]
            + vals["targets"]
            + vals["touches"]
            + vals["sacks"]
            == 0
        ):
            continue
        n = max(1, int(vals["touches"] or vals["att"] or 1))
        rows.append(
            {
                "player": name,
                "cmp": vals["cmp"],
                "att": vals["att"],
                "pass_yds": round(vals["pass_yds"], 0),
                "pass_td": vals["pass_td"],
                "ints": vals["ints"],
                "sacks": vals["sacks"],
                "carries": vals["carries"],
                "rush_yds": round(vals["rush_yds"], 0),
                "rush_td": vals["rush_td"],
                "targets": vals["targets"],
                "receptions": vals["receptions"],
                "rec_yds": round(vals["rec_yds"], 0),
                "rec_td": vals["rec_td"],
                "touches": vals["touches"],
                "yards": round(vals["yards"], 0),
                "tds": vals["tds"],
                "avg_value": round(vals["total_value"] / n, 2),
                "total_value": round(vals["total_value"], 2),
            }
        )
    if not rows:
        return pd.DataFrame(columns=cols)
    return (
        pd.DataFrame(rows)
        .sort_values(
            ["total_value", "pass_yds", "yards", "touches"],
            ascending=[False, False, False, False],
        )
        .reset_index(drop=True)
    )


def player_touch_stats_table(
    live_logs: pd.DataFrame,
    opponent: str | None = None,
) -> pd.DataFrame:
    """Alias — skill counting board (pass + rush + rec)."""
    return player_skill_stats_table(live_logs, opponent)


LIVE_TAGS_FILE = PROJECT_DIR / "data" / "live_tags.json"

# Booth defaults when season film never tagged these (coverage was empty in Hudl).
DEFAULT_FILM_FRONTS = ["Even", "Odd", "Bear"]
DEFAULT_FILM_COVERAGES = [
    "Cover 3",
    "Cover 4",
    "Cover 2",
    "Cover 2 Man",
    "Cover 1",
]


def _load_learned_tags() -> dict[str, list[str]]:
    if not LIVE_TAGS_FILE.exists():
        return {}
    try:
        import json

        raw = json.loads(LIVE_TAGS_FILE.read_text())
        if not isinstance(raw, dict):
            return {}
        out: dict[str, list[str]] = {}
        for k, vals in raw.items():
            if isinstance(vals, list):
                cleaned = []
                seen: set[str] = set()
                for v in vals:
                    s = str(v).strip()
                    if not s or s.lower() in seen:
                        continue
                    seen.add(s.lower())
                    cleaned.append(s)
                out[str(k)] = cleaned
        return out
    except Exception:
        return {}


def _save_learned_tags(tags: dict[str, list[str]]) -> None:
    import json

    LIVE_TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIVE_TAGS_FILE.write_text(json.dumps(tags, indent=2))


def learn_live_tag(kind: str, value: str) -> None:
    """Remember a newly typed formation/play/etc so it stays in the dropdown."""
    val = str(value or "").strip()
    if not val or val.lower() in {"(none)", "none", "nan", "unknown"}:
        return
    if "unknown" in val.lower():
        return
    tags = _load_learned_tags()
    bucket = list(tags.get(kind, []))
    low = {x.lower() for x in bucket}
    if val.lower() not in low:
        bucket.append(val)
        tags[kind] = bucket
        _save_learned_tags(tags)
    # Session mirror for instant same-run visibility after rerun
    sess = st.session_state.setdefault("lt_learned_tags", {})
    if not isinstance(sess, dict):
        sess = {}
        st.session_state.lt_learned_tags = sess
    cur = list(sess.get(kind, []))
    if val.lower() not in {x.lower() for x in cur}:
        cur.append(val)
        sess[kind] = cur


def ensure_default_film_tags() -> None:
    """Seed Even/Odd + basic covers into learned tags so Fill Film dropdowns are ready."""
    tags = _load_learned_tags()
    changed = False
    for kind, defaults in (
        ("def_front", DEFAULT_FILM_FRONTS),
        ("coverage", DEFAULT_FILM_COVERAGES),
    ):
        bucket = list(tags.get(kind, []))
        low = {x.lower() for x in bucket}
        for d in defaults:
            if d.lower() not in low:
                bucket.append(d)
                low.add(d.lower())
                changed = True
        tags[kind] = bucket
    if changed:
        _save_learned_tags(tags)
    sess = st.session_state.setdefault("lt_learned_tags", {})
    if not isinstance(sess, dict):
        sess = {}
        st.session_state.lt_learned_tags = sess
    for kind, defaults in (
        ("def_front", DEFAULT_FILM_FRONTS),
        ("coverage", DEFAULT_FILM_COVERAGES),
    ):
        cur = list(sess.get(kind, []))
        low = {x.lower() for x in cur}
        for d in defaults:
            if d.lower() not in low:
                cur.append(d)
                low.add(d.lower())
        sess[kind] = cur


def _file_mtime_size(path: Path) -> tuple[float, int]:
    try:
        if path.exists():
            info = path.stat()
            return float(info.st_mtime), int(info.st_size)
    except OSError:
        pass
    return 0.0, 0


@st.cache_data(show_spinner=False)
def _cached_season_tag_col(unit: str, col: str, mtime: float, size: int) -> list[str]:
    """Unique season tags for one column — busts when football.db changes."""
    if not DB_FILE.exists() or size <= 0:
        return []
    df = _load_plays_cached(unit, mtime, size)
    if df is None or df.empty or col not in df.columns:
        return []
    return _tag_options(df[col])


def _season_tag_opts(col: str, *, unit: str = "Offense") -> list[str]:
    mtime, size = _file_mtime_size(DB_FILE)
    return list(_cached_season_tag_col(unit, col, mtime, size))


def _merge_film_tag_options(base: list[str], *extra: pd.Series, kind: str) -> list[str]:
    """Like _merge_tag_options but always prepends Even/Odd or Cover 1–4."""
    ensure_default_film_tags()
    defaults = DEFAULT_FILM_FRONTS if kind == "def_front" else DEFAULT_FILM_COVERAGES
    merged = _merge_tag_options(base, *extra, kind=kind)
    out: list[str] = []
    seen: set[str] = set()
    for v in list(defaults) + list(merged):
        s = str(v or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _merge_tag_options(
    base: list[str],
    *extra_series: pd.Series,
    kind: str | None = None,
    limit: int = 150,
) -> list[str]:
    """Season tags + live log + learned mid-game installs."""
    series_list = list(extra_series)
    if kind:
        learned = list((_load_learned_tags().get(kind) or []))
        sess = st.session_state.get("lt_learned_tags") or {}
        if isinstance(sess, dict):
            learned = list(dict.fromkeys(learned + list(sess.get(kind) or [])))
        if learned:
            series_list.append(pd.Series(learned, dtype=str))
    merged = _tag_options(pd.Series(base, dtype=str), *series_list, limit=limit)
    return merged


def _apply_pending_live_tags() -> None:
    """After a log, pin dropdown to the call just used and clear the type-in box."""
    pending = st.session_state.pop("lt_tag_pending", None)
    if not isinstance(pending, dict):
        return
    for key, val in pending.items():
        st.session_state[key] = val


def _tag_options(*series_list: pd.Series, limit: int = 80) -> list[str]:
    vals: list[str] = []
    seen: set[str] = set()
    for series in series_list:
        if series is None or getattr(series, "empty", True):
            continue
        for v in series.dropna().astype(str).str.strip():
            if not v or v.lower() == "unknown" or "unknown" in v.lower():
                continue
            key = v.lower()
            if key not in seen:
                seen.add(key)
                vals.append(v)
    vals.sort(key=str.upper)
    return vals[:limit]


@st.cache_data
def _hudl_motion_options() -> list[str]:
    """Pull MOTION tags from Hudl season export (and scout files if present)."""
    export_dir = PROJECT_DIR / "data" / "hudl_exports"
    series_list: list[pd.Series] = []
    for path in sorted(export_dir.glob("*.xlsx")):
        if path.name.startswith("~"):
            continue
        try:
            df = pd.read_excel(path, usecols=lambda c: str(c).strip().upper() in {"MOTION"})
        except Exception:
            try:
                raw = pd.read_excel(path)
                cols = {str(c).strip().upper(): c for c in raw.columns}
                if "MOTION" not in cols:
                    continue
                df = raw[[cols["MOTION"]]]
            except Exception:
                continue
        if not df.empty:
            series_list.append(df.iloc[:, 0])
    return _tag_options(*series_list, limit=100)


def _select_or_type(label: str, options: list[str], key: str) -> str:
    """Pick from known tags (season + tonight + learned), or type a new one once."""
    c_pick, c_type = st.columns([3, 2])
    with c_pick:
        opts = [""] + list(options)
        # If current selection isn't in opts yet (race), keep it selectable
        cur = str(st.session_state.get(key, "") or "").strip()
        if cur and cur not in opts:
            opts = [""] + [cur] + [o for o in options if o != cur]
        choice = st.selectbox(label, opts, key=key)
    with c_type:
        custom = st.text_input(
            f"Type {label.lower()}",
            key=f"{key}_custom",
            placeholder="new once → saved",
            help=(
                f"Type a new {label.lower()} the first time — it is saved to the dropdown "
                "for the rest of the game."
            ),
        )
    typed = str(custom or "").strip()
    if typed:
        return typed
    return str(choice or "").strip()


def _yards_to_distance_bucket(yards_to_go: int | float) -> str:
    y = float(yards_to_go)
    if y <= 3:
        return "short"
    if y <= 6:
        return "medium"
    return "long"


def advance_live_situation(
    down: int,
    distance_yards: int | float,
    yards_gained: int | float,
    result: str,
    field_zone: str,
    *,
    auto_first: bool = False,
    ball_yard: int | float | None = None,
) -> dict:
    """
    Compute the next down & distance after a charted play.

    Also moves the ball spot and refreshes field zone
    (e.g. own 10 + gain 25 → own 35 → own_territory).

    Examples:
      1st & 10, Penalty, −5 → 1st & 15 (replay down)
      1st & 15, loss of 9 → 2nd & 24
      1st & 10, gain of 4 → 2nd & 6
      2nd & 6, gain of 6+ → 1st & 10
      3rd & 8, Penalty +15 → 1st & 10 (yards ≥ to-go, or auto_first)
    """
    r = str(result or "").strip()
    d = int(down)
    to_go = max(1, int(distance_yards))
    try:
        yds = int(yards_gained)
    except (TypeError, ValueError):
        yds = 0

    zone = field_zone or "midfield"
    start_ball = (
        int(ball_yard)
        if ball_yard is not None
        else zone_default_ball_yard(zone)
    )

    def _with_ball(move_yds: int, **base) -> dict:
        new_ball = advance_ball_yard(start_ball, move_yds, zone)
        new_zone = ball_yard_to_zone(new_ball)
        spot = format_ball_spot(new_ball)
        note = str(base.get("note") or "")
        if spot and new_zone != zone:
            note = f"{note} · ball {spot} ({ZONE_LABELS.get(new_zone, new_zone)})".strip(" ·")
        elif spot:
            note = f"{note} · ball {spot}".strip(" ·")
        return {
            **base,
            "field_zone": new_zone,
            "ball_yard": new_ball,
            "note": note,
        }

    if r in {"TD", "Turnover", "Punt"}:
        # TD → end zone; turnover/punt → other unit (keep spot rough / midfield reset on punt)
        if r == "TD":
            new_ball = 99
            new_zone = "red_zone"
        elif r == "Punt":
            new_ball = zone_default_ball_yard("midfield")
            new_zone = "midfield"
        else:
            new_ball = start_ball
            new_zone = ball_yard_to_zone(new_ball)
        return {
            "down": 1,
            "distance_yards": 10,
            "field_zone": new_zone,
            "ball_yard": new_ball,
            "note": f"1st & 10 after {r} · ball {format_ball_spot(new_ball)}",
        }

    # Penalty: signed yards (e.g. −5 → 1st & 15; +15 past to-go → 1st & 10)
    if r == "Penalty":
        # Defensive 15-yard fouls / spoken "auto first" → first down
        if auto_first or (yds > 0 and yds >= to_go) or (yds >= 15 and yds > 0):
            return _with_ball(
                yds,
                down=1,
                distance_yards=10,
                note=f"Penalty +{yds} → automatic first down, 1st & 10",
            )
        new_to_go = int(max(1, min(99, to_go - yds)))
        return _with_ball(
            yds,
            down=d,
            distance_yards=new_to_go,
            note=f"Penalty ({yds:+d}) → same down, {d} & {new_to_go}",
        )

    if r == "Incomplete":
        yds = 0

    # Converted
    if yds >= to_go:
        return _with_ball(
            yds,
            down=1,
            distance_yards=10,
            note="First down → 1st & 10",
        )

    new_to_go = int(max(1, min(99, to_go - yds)))
    new_down = d + 1
    if new_down > 4:
        return _with_ball(
            yds,
            down=1,
            distance_yards=10,
            note="Turnover on downs → 1st & 10",
        )
    return _with_ball(
        yds,
        down=new_down,
        distance_yards=new_to_go,
        note=f"Next → {new_down} & {new_to_go}",
    )


def _apply_pending_live_situation() -> None:
    """Apply queued down/distance BEFORE situation widgets are created."""
    pending = st.session_state.pop("lt_situation_pending", None)
    if not pending:
        return
    st.session_state.lt_down = int(pending.get("down", 1))
    st.session_state.lt_dist_y = int(pending.get("distance_yards", 10))
    if pending.get("ball_yard") is not None:
        try:
            st.session_state.lt_ball_yard = int(pending["ball_yard"])
        except (TypeError, ValueError):
            st.session_state.lt_ball_yard = zone_default_ball_yard(
                pending.get("field_zone")
            )
        st.session_state.lt_zone = ball_yard_to_zone(st.session_state.lt_ball_yard)
    elif pending.get("field_zone"):
        st.session_state.lt_zone = pending["field_zone"]
        # Keep current ball spot when only down/distance resets
        if "lt_ball_yard" not in st.session_state or st.session_state.get("lt_ball_yard") in {
            None,
            "",
        }:
            st.session_state.lt_ball_yard = zone_default_ball_yard(pending["field_zone"])
        else:
            # Re-derive zone from the ball we already have
            st.session_state.lt_zone = ball_yard_to_zone(st.session_state.lt_ball_yard)
    st.session_state.lt_gain = 0
    note = pending.get("note")
    if note:
        st.session_state.lt_situation_note = note


def _look_table_for_display(rows: list[dict]) -> pd.DataFrame:
    """Coach-facing table for scout × our success rows."""
    if not rows:
        return pd.DataFrame()
    out = []
    for r in rows:
        suc = r.get("success_rate")
        epa = r.get("avg_epa")
        row = {
            "Look": r.get("look"),
            "Scout %": r.get("scout_pct"),
            "Scout n": r.get("scout_plays"),
            "Our n": r.get("our_plays"),
            "Our EPA": epa if epa is not None else "—",
            "Success": f"{100 * suc:.0f}%" if suc is not None else "—",
            "Verdict": str(r.get("verdict") or "—"),
        }
        if r.get("booth_tag"):
            row["Booth"] = r.get("booth_tag")
        out.append(row)
    return pd.DataFrame(out)


def _render_scout_matchup_report(
    report: dict,
    *,
    key_prefix: str = "scout_rpt",
    expanded: bool = True,
) -> None:
    """Show tendencies × our success after scout upload / on Scout page."""
    if not report or not report.get("scout_snaps"):
        st.info(report.get("summary") or "No scout defense data yet.")
        return

    st.markdown(f"### Scout matchup · vs {report.get('opponent')}")
    st.caption(str(report.get("summary") or ""))
    for note in report.get("notes") or []:
        st.caption(note)

    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Edges** (we good vs looks they run)")
        if report.get("edges"):
            for r in report["edges"]:
                calls = r.get("best_calls") or []
                call_bit = ""
                if calls:
                    call_bit = " · feature " + ", ".join(
                        f"{c['call']} ({c['avg_epa']:+.2f})" for c in calls[:2]
                    )
                epa = r.get("avg_epa")
                epa_s = f"{epa:+.3f}" if epa is not None else "—"
                st.success(
                    f"**{r['look']}** · scout {r['scout_pct']}% · "
                    f"EPA {epa_s} (n={r['our_plays']}){call_bit}"
                )
        else:
            st.caption("No clear edges yet (need more tagged snaps vs their looks).")
    with e2:
        st.markdown("**Traps / caution** (they run it · we struggle)")
        if report.get("traps"):
            for r in report["traps"]:
                epa = r.get("avg_epa")
                epa_s = f"{epa:+.3f}" if epa is not None else "—"
                st.warning(
                    f"**{r['look']}** · scout {r['scout_pct']}% · "
                    f"EPA {epa_s} (n={r['our_plays']})"
                )
        else:
            st.caption("No traps flagged.")

    front_label = (
        "Booth fronts · full table"
        if report.get("booth_front_mode") == "even_42"
        else "Fronts · full table"
    )
    with st.expander(front_label, expanded=expanded):
        tf = _look_table_for_display(report.get("fronts") or [])
        if tf.empty:
            st.caption("No fronts in scout.")
        else:
            st.dataframe(tf, hide_index=True, use_container_width=True)
    if report.get("fronts_detail") and report.get("booth_front_mode") == "even_42":
        with st.expander("Scout front detail (film only)", expanded=False):
            td = _look_table_for_display(report.get("fronts_detail") or [])
            if not td.empty:
                cols = [c for c in ["Look", "Booth", "Scout %", "Scout n"] if c in td.columns]
                st.dataframe(td[cols], hide_index=True, use_container_width=True)
    with st.expander("Coverages · full table", expanded=False):
        tc = _look_table_for_display(report.get("coverages") or [])
        if tc.empty:
            st.caption("No coverages in scout.")
        else:
            st.dataframe(tc, hide_index=True, use_container_width=True)
    with st.expander("Front | Coverage pairs", expanded=False):
        tp = _look_table_for_display(report.get("def_calls") or [])
        if tp.empty:
            st.caption("No paired calls in scout.")
        else:
            st.dataframe(tp, hide_index=True, use_container_width=True)

    from mesh_engine import scout_matchup_report_markdown

    md = scout_matchup_report_markdown(report)
    st.download_button(
        "Download matchup report (.md)",
        data=md,
        file_name=f"scout_matchup_{report.get('opponent', 'opp').replace(' ', '_')}.md",
        mime="text/markdown",
        key=f"{key_prefix}_dl",
        use_container_width=True,
        type="primary",
    )


def _save_scout_matchup_report(report: dict) -> Path | None:
    """Persist markdown under data/scout_reports/."""
    if not report or not report.get("scout_snaps"):
        return None
    try:
        from mesh_engine import scout_matchup_report_markdown

        out_dir = PROJECT_DIR / "data" / "scout_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        opp = str(report.get("opponent") or "opponent").replace("/", "-")
        path = out_dir / f"{opp}_matchup.md"
        path.write_text(scout_matchup_report_markdown(report), encoding="utf-8")
        return path
    except Exception:
        return None


def _render_scout_upload_matchup_panel(offense_df: pd.DataFrame) -> None:
    """Upload Hudl scout → match to stored EPA → downloadable report."""
    from mesh_engine import build_scout_matchup_report, load_season_opponents
    from team_config import current_season_id

    st.subheader("Upload scout → matchup report")
    st.caption(
        "Drop a Hudl D scout export (.xlsx). We match their looks to your stored "
        "offense EPA and build a downloadable call-sheet report."
    )

    season_opps = load_season_opponents()
    c1, c2 = st.columns([2, 1])
    with c1:
        typed = st.text_input(
            "Opponent name",
            value=st.session_state.get("scout_upload_opp")
            or (season_opps[0] if season_opps else ""),
            key="scout_upload_opp_input",
            placeholder="Farmersville",
        )
    with c2:
        if season_opps:
            pick = st.selectbox(
                "Or pick from schedule",
                ["—"] + season_opps,
                key="scout_upload_opp_pick",
            )
            if pick and pick != "—":
                typed = pick

    role = st.radio(
        "Scout file is…",
        [
            "Their defense (D) — match to our offense EPA",
            "Their offense (O) — stored only (matchup report is D-focused)",
        ],
        key="scout_upload_role",
        horizontal=False,
    )
    is_defense = role.startswith("Their defense")

    booth_even = st.checkbox(
        "4-2 booth tagging (map numbered fronts → Even)",
        value=True,
        key="scout_upload_even42",
        help="Use when the opponent is a 4-2 / Even front family but Hudl charts 31/13/22 detail.",
    )

    # Season sample for our EPA
    season_opts = []
    if offense_df is not None and not offense_df.empty and "season" in offense_df.columns:
        season_opts = sorted(
            {
                str(s).strip()
                for s in offense_df["season"].dropna().tolist()
                if str(s).strip() and str(s).strip().lower() != "nan"
            },
            reverse=True,
        )
    default_seasons = [
        s for s in season_opts if s in {"24-25", "25-26", "26-27", current_season_id()}
    ]
    if not default_seasons and season_opts:
        default_seasons = season_opts[:2]
    our_seasons = st.multiselect(
        "Our EPA seasons to include",
        options=season_opts or ["all"],
        default=default_seasons or season_opts,
        key="scout_upload_our_seasons",
        help="Last year + this year’s scrimmages is the usual week-1 mix.",
    )

    up = st.file_uploader(
        "Hudl scout export (.xlsx)",
        type=["xlsx", "xls"],
        key="scout_matchup_uploader",
    )

    save_db = st.checkbox(
        "Also save into scout database (for Live Track / tendencies)",
        value=True,
        key="scout_upload_save_db",
    )

    go = st.button(
        "Generate matchup report",
        type="primary",
        key="scout_upload_generate",
        disabled=up is None or not str(typed or "").strip(),
        use_container_width=True,
    )

    if not go:
        # Show last report if present
        prev = st.session_state.get("scout_upload_last_report")
        if prev:
            st.markdown("---")
            _render_scout_matchup_report(
                prev, key_prefix="scout_upload_prev", expanded=True
            )
        return

    opp_name = str(typed or "").strip()
    st.session_state["scout_upload_opp"] = opp_name
    scout_role = "opponent_defense" if is_defense else "opponent_offense"

    try:
        exports = PROJECT_DIR / "data" / "hudl_exports"
        exports.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in opp_name)
        side = "D" if is_defense else "O"
        dest = exports / f"{safe} {side} Scout.xlsx"
        dest.write_bytes(up.getvalue())

        n_rows = upsert_scout_plays_from_file(
            dest, opponent=opp_name, role=scout_role
        ) if save_db else 0

        # Stamp current season on just-imported rows
        if save_db and n_rows:
            try:
                import sqlite3

                from mesh_engine import DB_FILE

                sid = current_season_id()
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute(
                        "UPDATE scout_plays SET season=? "
                        "WHERE LOWER(TRIM(opponent))=? AND scout_role=?",
                        (sid, opp_name.lower(), scout_role),
                    )
            except Exception:
                pass

        if not is_defense:
            st.success(
                f"Saved **{n_rows or 'file'}** offense-scout rows for {opp_name}. "
                "Matchup report is built for D scout (their defense vs our offense)."
            )
            return

        # Build from freshly cleaned file when possible
        from step2_clean import assign_game_ids, clean_scout_file

        raw = pd.read_excel(dest)
        raw = raw.copy()
        raw["game_id"] = assign_game_ids(raw["PLAY #"])
        cleaned = clean_scout_file(
            raw, opp_name, scout_role, dest.name, season=current_season_id()
        )
        booth_mode = "even_42" if booth_even else "as_scouted"
        seasons = our_seasons if our_seasons else None
        report = build_scout_matchup_report(
            opp_name,
            offense_df,
            scout_df=cleaned if cleaned is not None and not cleaned.empty else None,
            booth_front_mode=booth_mode,
            our_seasons=seasons,
        )
        saved = _save_scout_matchup_report(report)
        st.session_state["scout_upload_last_report"] = report
        bits = [f"**{report.get('scout_snaps', 0)}** D snaps matched"]
        if save_db:
            bits.append(f"DB +{n_rows}")
        if saved:
            bits.append(f"saved `{saved.name}`")
        st.success(" · ".join(bits))
        _render_scout_matchup_report(
            report, key_prefix="scout_upload_new", expanded=True
        )
    except Exception as exc:
        st.error(f"Could not build matchup report: {exc}")


def scout_tendencies_page() -> None:
    from mesh_engine import (
        defense_scout_tendencies,
        load_scout,
        load_season_opponents,
        offense_scout_tendencies,
    )
    current_season_label = _season_api().current_season_label

    st.header("Opponent Scout")
    offense_df = load_plays("Offense")

    tab_upload, tab_tend = st.tabs(["Upload & matchup report", "Tendencies by situation"])

    with tab_upload:
        _render_scout_upload_matchup_panel(offense_df)

    with tab_tend:
        st.markdown(
            f"""
            From per-opponent scout files in `data/hudl_exports/`:
            - **`Farmersville D.xlsx`** = their defense (fronts/coverages) → helps **our offense**
            - **`Farmersville O.xlsx`** = their offense (formations/run-pass) → helps **our defense**
            - Defaults to **{current_season_label()}** scout only
            """
        )

        season_opps = load_season_opponents()
        f0, f1 = st.columns([2, 1])
        opp_choice = f0.selectbox(
            "Filter by opponent",
            ["All (pooled)"] + season_opps,
            key="scout_page_opp",
        )
        season_scope = f1.selectbox(
            "Season",
            [f"Current ({current_season_label()})", "All seasons"],
            key="scout_page_season",
        )
        opponent = None if opp_choice == "All (pooled)" else opp_choice
        scout_season = "current" if season_scope.startswith("Current") else "all"

        scout_d = load_scout("opponent_defense", opponent, season=scout_season)
        scout_o = load_scout("opponent_offense", opponent, season=scout_season)

        c1, c2, c3 = st.columns(3)
        c1.metric("Opponent defense snaps", f"{len(scout_d):,}")
        c2.metric("Opponent offense snaps", f"{len(scout_o):,}")
        mapped_note = opponent or "all cuts"
        c3.metric("Scope", mapped_note)

        if scout_d.empty and scout_o.empty:
            st.warning(
                "No scout data for this opponent. Use **Upload & matchup report**, "
                "or drop `{Opponent} D.xlsx` / `{Opponent} O.xlsx` into `data/hudl_exports/`."
            )
            return

        # Matchup from DB (no upload needed)
        if opponent and not scout_d.empty:
            try:
                from mesh_engine import build_scout_matchup_report

                report = build_scout_matchup_report(
                    opponent,
                    offense_df,
                    scout_season=scout_season,
                    booth_front_mode="even_42",
                )
                with st.expander("Matchup report · tendencies × our success", expanded=False):
                    _render_scout_matchup_report(
                        report, key_prefix="scout_page_match", expanded=False
                    )
            except Exception as exc:
                st.caption(f"Matchup report unavailable: {exc}")

        f1, f2, f3 = st.columns(3)
        down = f1.selectbox("Down", [1, 2, 3, 4], key="scout_down")
        dist = f2.selectbox("Distance", ["short", "medium", "long"], key="scout_dist")
        zone = f3.selectbox(
            "Field zone",
            ["backed_up", "own_territory", "midfield", "opp_territory", "red_zone"],
            index=2,
            key="scout_zone",
        )

        off_tend = offense_scout_tendencies(scout_d, down, dist, zone)
        def_tend = defense_scout_tendencies(scout_o, down, dist, zone)

        st.subheader(situation_label(down, dist, zone))
        left, right = st.columns(2)
        with left:
            st.markdown("**Their defense (for our offense)**")
            if off_tend["plays"]:
                st.info(
                    f"n={off_tend['plays']} ({off_tend['scope']}) · lean **{off_tend['lean']}**"
                )
                st.markdown(
                    f"Most called — Front **{_fmt_most(off_tend.get('most_front'))}** · "
                    f"Coverage **{_fmt_most(off_tend.get('most_coverage'))}** · "
                    f"Call **{_fmt_most(off_tend.get('most_play'))}**"
                )
                if off_tend["top_fronts"]:
                    st.write("Top fronts")
                    st.dataframe(
                        pd.DataFrame(off_tend["top_fronts"]),
                        hide_index=True,
                        use_container_width=True,
                    )
                if off_tend["top_coverages"]:
                    st.write("Top coverages")
                    st.dataframe(
                        pd.DataFrame(off_tend["top_coverages"]),
                        hide_index=True,
                        use_container_width=True,
                    )
                if off_tend.get("top_def_calls"):
                    st.write("Top front | coverage calls")
                    st.dataframe(
                        pd.DataFrame(off_tend["top_def_calls"]),
                        hide_index=True,
                        use_container_width=True,
                    )
            else:
                st.write("No opponent-defense scout in this bucket.")
        with right:
            st.markdown("**Their offense (for our defense)**")
            if def_tend["plays"]:
                st.info(
                    f"n={def_tend['plays']} ({def_tend['scope']}) · lean **{def_tend['lean']}** "
                    f"(Run {def_tend['run_pct']}% / Pass {def_tend['pass_pct']}%)"
                )
                st.markdown(
                    f"Most called — Formation **{_fmt_most(def_tend.get('most_formation'))}** · "
                    f"Play **{_fmt_most(def_tend.get('most_play'))}**"
                )
                if def_tend["top_formations"]:
                    st.write("Top formations")
                    st.dataframe(
                        pd.DataFrame(def_tend["top_formations"]),
                        hide_index=True,
                        use_container_width=True,
                    )
                if def_tend["top_plays"]:
                    st.write("Top plays")
                    st.dataframe(
                        pd.DataFrame(def_tend["top_plays"]),
                        hide_index=True,
                        use_container_width=True,
                    )
            else:
                st.write("No opponent-offense scout in this bucket.")

        map_path = PROJECT_DIR / "data" / "hudl_exports"
        with st.expander("Scout files on disk"):
            files = sorted(map_path.glob("*.xlsx"))
            names = [f.name for f in files if not f.name.startswith("~$")]
            st.write(names if names else "No Excel files found.")


def game_plan_page(offense_df: pd.DataFrame, defense_df: pd.DataFrame) -> None:
    """Pre-match identifier: what we do well × what they run × how we do vs that."""
    from mesh_engine import (
        defense_scout_tendencies,
        load_game_plan,
        load_scout,
        load_season_opponents,
        offense_scout_tendencies,
        pin_names,
        save_game_plan,
        suggest_edges,
    )

    st.markdown('<p class="live-title">Game Plan</p>', unsafe_allow_html=True)
    st.caption("Identify edges vs their looks, then pin what you’ll feature tonight.")

    season_opps = load_season_opponents()
    head = st.columns([2, 1, 1, 1])
    with head[0]:
        opponent = st.selectbox(
            "Opponent",
            season_opps if season_opps else ["Unknown"],
            key="gp_opponent",
        )
    with head[1]:
        gp_down = st.selectbox("Down", [1, 2, 3, 4], index=0, key="gp_down")
    with head[2]:
        dist_opts = ["short", "medium", "long"]
        gp_dist = st.selectbox("Distance", dist_opts, index=2, key="gp_dist")
    with head[3]:
        zone_opts = list(ZONE_LABELS.keys())
        gp_zone = st.selectbox(
            "Field",
            zone_opts,
            index=zone_opts.index("midfield") if "midfield" in zone_opts else 0,
            format_func=lambda z: ZONE_LABELS.get(z, z),
            key="gp_zone",
        )

    unit_tab = "Offense"
    st.session_state.gp_unit = "Offense"
    min_plays = st.slider("Min plays", 2, 15, 5, key="gp_min")

    plan = load_game_plan(opponent)
    scout_d = load_scout("opponent_defense", opponent)
    scout_o = load_scout("opponent_offense", opponent)
    if scout_d.empty and scout_o.empty:
        scout_d = load_scout("opponent_defense", None)
        scout_o = load_scout("opponent_offense", None)
        st.info("No opponent-specific scout files — using pooled scout. Add `Opponent D/O.xlsx`.")

    off_tend = offense_scout_tendencies(scout_d, int(gp_down), str(gp_dist), str(gp_zone))
    def_tend = defense_scout_tendencies(scout_o, int(gp_down), str(gp_dist), str(gp_zone))

    off_cfg, def_cfg = UNITS["Offense"], UNITS["Defense"]
    our_df = offense_df if unit_tab == "Offense" else defense_df
    cfg = off_cfg if unit_tab == "Offense" else def_cfg
    call_col = cfg["secondary_group"] if unit_tab == "Offense" else cfg["combo_col"]
    combo_col = cfg["combo_col"]

    we_well = avg_epa_table(our_df, call_col, min_plays)
    we_combos = avg_epa_table(our_df, combo_col, min_plays)

    if unit_tab == "Offense":
        their_names = {
            str(x["name"])
            for x in (off_tend.get("top_fronts", [])[:5] + off_tend.get("top_coverages", [])[:5])
        }
        vs = (
            our_df[
                our_df["def_front"].astype(str).isin(their_names)
                | our_df["coverage"].astype(str).isin(their_names)
            ]
            if their_names and not our_df.empty
            else our_df.iloc[0:0]
        )
        vs_table = avg_epa_table(vs, call_col, max(2, min_plays - 2)) if not vs.empty else pd.DataFrame()
        they_block = off_tend
    else:
        their_names = {
            str(x["name"])
            for x in (def_tend.get("top_formations", [])[:5] + def_tend.get("top_plays", [])[:5])
        }
        if their_names and not our_df.empty and "formation" in our_df.columns:
            vs = our_df[our_df["formation"].astype(str).isin(their_names)]
        else:
            vs = our_df.iloc[0:0]
        vs_table = avg_epa_table(vs, call_col, max(2, min_plays - 2)) if not vs.empty else pd.DataFrame()
        they_block = def_tend

    tab_id, tab_edge, tab_pin = st.tabs(["Identify", "Edges vs them", "Pin board"])

    with tab_id:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### What we do well")
            if we_well.empty:
                st.write("Not enough tagged season plays.")
            else:
                show = we_well.head(8).copy()
                if "success_rate" in show.columns:
                    show["success_rate"] = (
                        (show["success_rate"] * 100).round(0).astype("Int64").astype(str) + "%"
                    )
                st.dataframe(show, hide_index=True, use_container_width=True)
                with st.expander("Best combos"):
                    if we_combos.empty:
                        st.write("No combo data.")
                    else:
                        show_c = we_combos.head(8).copy()
                        if "success_rate" in show_c.columns:
                            show_c["success_rate"] = (
                                (show_c["success_rate"] * 100).round(0).astype("Int64").astype(str)
                                + "%"
                            )
                        st.dataframe(show_c, hide_index=True, use_container_width=True)
        with c2:
            st.markdown(
                f"#### What they run · {gp_down} & {gp_dist} · "
                f"{ZONE_LABELS.get(gp_zone, gp_zone)}"
            )
            if they_block.get("plays"):
                st.info(
                    f"Their D lean **{they_block.get('lean', '—')}** · "
                    f"n={they_block['plays']} ({they_block.get('scope')})"
                )
                st.markdown(
                    f"Most — Front **{_fmt_most(they_block.get('most_front'))}** · "
                    f"Cov **{_fmt_most(they_block.get('most_coverage'))}** · "
                    f"Call **{_fmt_most(they_block.get('most_play'))}**"
                )
                if they_block.get("top_fronts"):
                    st.write("Top fronts")
                    st.dataframe(
                        pd.DataFrame(they_block["top_fronts"]),
                        hide_index=True,
                        use_container_width=True,
                    )
                if they_block.get("top_coverages"):
                    st.write("Top coverages")
                    st.dataframe(
                        pd.DataFrame(they_block["top_coverages"]),
                        hide_index=True,
                        use_container_width=True,
                    )
            else:
                st.warning("No opponent-defense scout for this team / situation.")

    with tab_edge:
        st.markdown("#### How we do vs their common looks")
        if vs_table.empty:
            st.write(
                "Not enough of our snaps tagged against their common looks. "
                "Tag fronts/coverages in Hudl."
            )
        else:
            edges = vs_table[vs_table["avg_epa"] > 0].head(5)
            traps = vs_table[vs_table["avg_epa"] <= 0].sort_values("avg_epa").head(5)
            e1, e2 = st.columns(2)
            with e1:
                st.write("**Edges** (we good vs their looks)")
                if edges.empty:
                    st.caption("None yet.")
                else:
                    e = edges.copy()
                    if "success_rate" in e.columns:
                        e["success_rate"] = (
                            (e["success_rate"] * 100).round(0).astype("Int64").astype(str) + "%"
                        )
                    st.dataframe(e, hide_index=True, use_container_width=True)
            with e2:
                st.write("**Traps** (they run it · we struggle)")
                if traps.empty:
                    st.caption("None flagged.")
                else:
                    t = traps.copy()
                    if "success_rate" in t.columns:
                        t["success_rate"] = (
                            (t["success_rate"] * 100).round(0).astype("Int64").astype(str) + "%"
                        )
                    st.dataframe(t, hide_index=True, use_container_width=True)

    with tab_pin:
        st.markdown("#### Pinned game plan")
        pin_key = "offense_pins" if unit_tab == "Offense" else "defense_pins"
        suggestions = suggest_edges(
            we_well if not we_well.empty else vs_table,
            call_col,
            they_block.get("top_fronts") or they_block.get("top_formations") or [],
            vs if isinstance(vs, pd.DataFrame) else pd.DataFrame(),
            "def_front" if unit_tab == "Offense" else "formation",
            top_n=5,
        )
        if suggestions:
            st.caption("Suggested edges (click to pin):")
            cols = st.columns(min(5, len(suggestions)))
            for i, sug in enumerate(suggestions):
                if cols[i].button(
                    f"Pin {sug['call']}",
                    key=f"gp_sug_{unit_tab}_{i}",
                    use_container_width=True,
                ):
                    existing = {p.get("call") for p in plan.get(pin_key, [])}
                    if sug["call"] not in existing:
                        plan.setdefault(pin_key, []).append(sug)
                        save_game_plan(plan)
                        st.rerun()

        pins = plan.get(pin_key, [])
        if not pins:
            st.info("No pins yet — pin suggestions above or add manually.")
        else:
            for i, pin in enumerate(list(pins)):
                pc1, pc2 = st.columns([4, 1])
                pc1.markdown(f"**{pin.get('call', '')}** — {pin.get('why', '')}")
                if pc2.button("Unpin", key=f"gp_unpin_{unit_tab}_{i}"):
                    plan[pin_key] = [p for j, p in enumerate(pins) if j != i]
                    save_game_plan(plan)
                    st.rerun()

        manual = st.text_input("Add pin manually (call name)", key=f"gp_manual_{unit_tab}")
        if st.button("Add pin", key=f"gp_add_{unit_tab}") and manual.strip():
            existing = {p.get("call") for p in plan.get(pin_key, [])}
            if manual.strip() not in existing:
                plan.setdefault(pin_key, []).append({"call": manual.strip(), "why": "manual"})
                save_game_plan(plan)
                st.rerun()

        st.caption(
            f"Saved pins: O={len(plan.get('offense_pins', []))} · "
            f"D={len(plan.get('defense_pins', []))} · {plan.get('updated_at') or 'not saved'}"
        )


def in_game_page(offense_df: pd.DataFrame, defense_df: pd.DataFrame) -> None:
    """1st half situation mesh + halftime confirm/kill vs tonight."""
    try:
        from mesh_engine import (
            broaden_situation,
            defense_scout_tendencies,
            live_log_adjustments,
            load_game_plan,
            load_live_log,
            load_scout,
            load_season_opponents,
            mesh_rankings,
            offense_scout_tendencies,
            pin_names,
            plan_pin_status,
            score_live_calls,
        )
    except ImportError as exc:
        st.error("Could not load mesh engine. Restart Streamlit.")
        st.exception(exc)
        return

    st.markdown('<p class="live-title">In-Game</p>', unsafe_allow_html=True)
    st.caption(
        "1st Half = situation recommendations. End the half to generate the **Halftime report**, "
        "then confirm/kill plan items. Use **Live Track** to log full snaps and on-field +/-."
    )

    season_opps = load_season_opponents()
    opponent = st.selectbox(
        "Tonight's opponent",
        season_opps if season_opps else ["Unknown"],
        key="ig_opponent",
    )

    # Default to Halftime mode after 1st half is closed
    try:
        from mesh_engine import load_game_state

        gstate = load_game_state()
        if (
            gstate.get("opponent")
            and str(gstate.get("opponent")).strip().lower() == opponent.strip().lower()
            and gstate.get("phase") in {"halftime", "2nd"}
            and "ig_mode" not in st.session_state
        ):
            st.session_state.ig_mode = "Halftime"
    except Exception:
        pass

    mode = st.radio(
        "Mode",
        ["1st Half", "Halftime"],
        horizontal=True,
        key="ig_mode",
    )
    plan = load_game_plan(opponent)
    live_logs = load_live_log()

    # Plan strip
    o_pins = pin_names(plan, "offense")
    d_pins = pin_names(plan, "defense")
    if o_pins or d_pins:
        st.markdown(
            f"**Plan looks** — O: {', '.join(o_pins) or '—'} · D: {', '.join(d_pins) or '—'}"
        )
    else:
        st.info("No pinned game plan yet. Build one on the **Game Plan** page.")

    if mode == "Halftime":
        _halftime_panel(opponent, plan, live_logs, offense_df, defense_df)
        return

    # ---- 1st Half (situation recommendations) ----
    _end_first_half_action(opponent, live_logs, key_prefix="ig1")
    st.markdown("---")

    if "ig_down" not in st.session_state:
        st.session_state.ig_down = 1
    if "ig_dist" not in st.session_state:
        st.session_state.ig_dist = "long"
    if "ig_zone" not in st.session_state:
        st.session_state.ig_zone = "midfield"

    down = _choice_buttons("Down", [1, 2, 3, 4], "ig_down", 1)
    dist = _choice_buttons(
        "Distance",
        ["short", "medium", "long"],
        "ig_dist",
        "long",
        labels={"short": "Short (1-3)", "medium": "Medium (4-6)", "long": "Long (7+)"},
    )
    st.markdown("**Field zone**")
    zone_options = [
        ("backed_up", "Backed up"),
        ("own_territory", "Own"),
        ("midfield", "Midfield"),
        ("opp_territory", "Opp"),
        ("red_zone", "Red zone"),
    ]
    zcols = st.columns(len(zone_options))
    current_zone = st.session_state.ig_zone
    for i, (zone_key, zone_label) in enumerate(zone_options):
        selected = current_zone == zone_key
        if zcols[i].button(
            zone_label,
            key=f"ig_zone_{zone_key}",
            type="primary" if selected else "secondary",
            use_container_width=True,
        ):
            st.session_state.ig_zone = zone_key
            current_zone = zone_key
    zone = st.session_state.ig_zone
    min_plays = st.slider("Min plays (confidence)", 2, 12, 3, key="ig_min")

    st.markdown(
        f'<p class="live-situation">vs {opponent} · {situation_label(down, dist, zone)}</p>',
        unsafe_allow_html=True,
    )

    scout_d = load_scout("opponent_defense", opponent)
    scout_o = load_scout("opponent_offense", opponent)
    scout_scope = "opponent-specific"
    if scout_d.empty and scout_o.empty:
        scout_d = load_scout("opponent_defense", None)
        scout_o = load_scout("opponent_offense", None)
        scout_scope = "pooled"

    off_tend = offense_scout_tendencies(scout_d, down, dist, zone)
    def_tend = defense_scout_tendencies(scout_o, down, dist, zone)
    off_live = live_log_adjustments(
        live_logs, "Offense", down, dist, zone, opponent=opponent, half=1, weight=1.0
    )
    def_live = live_log_adjustments(
        live_logs, "Defense", down, dist, zone, opponent=opponent, half=1, weight=1.0
    )

    volume_floor = max(min_plays * 4, 12)
    off_matched, off_scope = broaden_situation(
        offense_df, down, dist, zone,
        exact_min=volume_floor, down_dist_min=volume_floor, down_min=min_plays,
    )
    def_matched, def_scope = broaden_situation(
        defense_df, down, dist, zone,
        exact_min=volume_floor, down_dist_min=volume_floor, down_min=min_plays,
    )

    off_cfg, def_cfg = UNITS["Offense"], UNITS["Defense"]
    off_combos = avg_epa_table(off_matched, off_cfg["combo_col"], min_plays)
    off_base = avg_epa_table(off_matched, off_cfg["secondary_group"], min_plays)
    def_base = avg_epa_table(def_matched, def_cfg["combo_col"], min_plays)
    def_cov = avg_epa_table(def_matched, def_cfg["secondary_group"], min_plays)
    best_off = _best_epa_row(off_combos, off_cfg["combo_col"])
    best_def = _best_epa_row(def_base, def_cfg["combo_col"])

    off_status = plan_pin_status(plan, "offense", score_live_calls(live_logs, "Offense", opponent))
    def_status = plan_pin_status(plan, "defense", score_live_calls(live_logs, "Defense", opponent))

    st.markdown("#### Situation snapshot")
    snap_l, snap_r = st.columns(2)
    with snap_l:
        if off_tend["plays"]:
            _live_spot(
                "Their D — most called",
                f"Front {_fmt_most(off_tend.get('most_front'))} · Cov {_fmt_most(off_tend.get('most_coverage'))}",
                meta=f"Call {_fmt_most(off_tend.get('most_play'))} · n={off_tend['plays']} ({off_tend['scope']})",
            )
        else:
            _live_spot("Their D — most called", "No scout in this bucket")
        if best_off:
            name, epa, n = best_off
            row_sr = ""
            if not off_combos.empty and off_cfg["combo_col"] in off_combos.columns:
                hit = off_combos[off_combos[off_cfg["combo_col"]] == name]
                if not hit.empty and "success_rate" in hit.columns:
                    row_sr = f" · succ {float(hit.iloc[0]['success_rate']):.0%}"
            epa_cls = "live-good" if epa >= 0 else "live-bad"
            _live_spot(
                "Our best EPA play (offense)",
                name,
                meta=f'<span class="{epa_cls}">EPA {epa:+.3f}</span>{row_sr} · n={n} · {off_scope}',
                accent=True,
            )
        else:
            _live_spot("Our best EPA play (offense)", "Not enough tagged plays", accent=True)
    with snap_r:
        if def_tend["plays"]:
            lean_bits = f"lean {def_tend['lean']}"
            if def_tend.get("run_pct") is not None:
                lean_bits += f" ({def_tend['run_pct']}% run / {def_tend['pass_pct']}% pass)"
            _live_spot(
                "Their O — most called",
                f"Form {_fmt_most(def_tend.get('most_formation'))} · Play {_fmt_most(def_tend.get('most_play'))}",
                meta=f"{lean_bits} · n={def_tend['plays']} ({def_tend['scope']})",
            )
        else:
            _live_spot("Their O — most called", "No scout in this bucket")
        if best_def:
            name, epa, n = best_def
            row_sr = ""
            if not def_base.empty:
                hit = def_base[def_base[def_cfg["combo_col"]] == name]
                if not hit.empty and "success_rate" in hit.columns:
                    row_sr = f" · succ {float(hit.iloc[0]['success_rate']):.0%}"
            epa_cls = "live-good" if epa >= 0 else "live-bad"
            _live_spot(
                "Our best EPA call (defense)",
                name,
                meta=f'<span class="{epa_cls}">EPA {epa:+.3f}</span>{row_sr} · n={n} · {def_scope}',
                accent=True,
            )
        else:
            _live_spot("Our best EPA call (defense)", "Not enough tagged calls", accent=True)

    st.caption(f"Scout={scout_scope} · season match O={off_scope}, D={def_scope}")

    off_calls = mesh_rankings(
        off_base, off_cfg["secondary_group"], off_tend, off_live, "offense", top_n=3,
        plan_pins=o_pins, plan_status=off_status, plan_weight=0.08,
        live_weight=1.8, scout_weight=0.75, season_weight=0.4,
    )
    def_calls = mesh_rankings(
        def_base, def_cfg["combo_col"], def_tend, def_live, "defense", top_n=3,
        plan_pins=d_pins, plan_status=def_status, plan_weight=0.08,
        live_weight=1.8, scout_weight=0.75, season_weight=0.4,
    )

    left, right = st.columns(2)
    with left:
        _render_live_recs(
            off_calls,
            "OFFENSE — Top 3 (EPA + success + plan + scout + live)",
            "Not enough tagged offense plays. Lower min plays.",
            call_col=off_cfg["secondary_group"],
        )
    with right:
        _render_live_recs(
            def_calls,
            "DEFENSE — Top 3 (EPA + success + plan + scout + live)",
            "Not enough tagged defense calls.",
            call_col=def_cfg["combo_col"],
        )

    st.markdown("---")
    st.subheader("Quick log (1st half)")
    log_unit = st.radio("Unit", ["Offense", "Defense"], horizontal=True, key="ig_log_unit")
    recs = off_calls if log_unit == "Offense" else def_calls
    call_col = off_cfg["secondary_group"] if log_unit == "Offense" else def_cfg["combo_col"]
    rec_options = (
        [getattr(r, call_col) for r in recs.itertuples(index=False)]
        if not recs.empty and call_col in recs.columns
        else []
    )
    # Also offer plan pins
    pin_opts = o_pins if log_unit == "Offense" else d_pins
    for p in pin_opts:
        if p not in rec_options:
            rec_options.append(p)

    l1, l2, l3, l4 = st.columns(4)
    recommended = l1.selectbox(
        "Recommended / called",
        rec_options if rec_options else ["(none)"],
        key="ig_log_call",
    )
    result = l2.selectbox(
        "Result",
        ["Gain", "No gain", "Incomplete", "TD", "Turnover", "Penalty", "Sack / TFL", "Punt", "Other"],
        key="ig_log_result",
    )
    yards = l3.number_input("Yards (optional)", value=0, step=1, key="ig_log_yards")
    note = l4.text_input("Note", key="ig_log_note")

    if st.button("Log this play", type="primary", use_container_width=True):
        append_live_log(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "opponent": opponent,
                "half": 1,
                "unit": log_unit,
                "down": down,
                "distance": dist,
                "field_zone": zone,
                "situation": situation_label(down, dist, zone),
                "call": recommended,
                "result": result,
                "yards_gained": yards,
                "note": note,
            }
        )
        st.success("Logged.")
        st.rerun()

    if LIVE_LOG_FILE.exists():
        logs = pd.read_csv(LIVE_LOG_FILE)
        with st.expander(f"Tonight's log ({len(logs)} plays)"):
            st.dataframe(logs.tail(25), use_container_width=True, hide_index=True)
            _render_live_log_delete_controls(opponent, key_prefix="ig_log")


def _render_start_new_game_panel(season_opps: list[str]) -> None:
    """Booth control: start a fresh game night (scout optional)."""
    st.caption(
        "Saves tonight’s finished log into **Game Review** (EPA graph), archives the CSV, "
        "resets drives / half, and sets the opponent. Scout file is optional."
    )
    known = [o for o in (season_opps or []) if str(o).strip()]
    name_opts = ["(type a new name)"] + known
    c1, c2 = st.columns([1.4, 1])
    with c1:
        pick = st.selectbox(
            "Opponent / game",
            name_opts,
            key="lt_newgame_pick",
            help="Pick a scheduled opponent or type a new name (e.g. Scrimmage).",
        )
        custom = st.text_input(
            "New name",
            value="",
            key="lt_newgame_custom",
            placeholder="Scrimmage · JV · Parents Night",
            disabled=pick != "(type a new name)",
        )
        notes = st.text_input("Notes (schedule)", value="", key="lt_newgame_notes", placeholder="optional")
    with c2:
        archive = st.checkbox("Archive & clear live log", value=True, key="lt_newgame_archive")
        add_sched = st.checkbox("Add to schedule if new", value=True, key="lt_newgame_sched")
        load_st = st.checkbox("Load starters into lineup", value=True, key="lt_newgame_starters")

    scout_files = list_available_scout_files()
    scout_labels = ["(no scout — OK for scrimmage)"] + [f["label"] for f in scout_files]
    scout_pick = st.selectbox("Scout file (optional)", scout_labels, key="lt_newgame_scout")
    uploaded = st.file_uploader(
        "Or upload a Hudl scout export (.xlsx)",
        type=["xlsx"],
        key="lt_newgame_upload",
        help="Saved into data/hudl_exports and merged into scout_plays. Not required.",
    )
    scout_side = st.radio(
        "Scout side",
        ["Their defense (for our offense)", "Their offense (for our defense)"],
        horizontal=True,
        key="lt_newgame_scout_side",
    )
    role = (
        "opponent_defense"
        if scout_side.startswith("Their defense")
        else "opponent_offense"
    )

    opp_name = custom.strip() if pick == "(type a new name)" else str(pick).strip()
    go = st.button(
        "Start new game ▶",
        type="primary",
        use_container_width=True,
        key="lt_newgame_go",
        disabled=not opp_name,
    )
    if not go:
        return
    if not opp_name:
        st.error("Enter an opponent / game name.")
        return

    scout_path = None
    if uploaded is not None:
        # Persist upload into hudl_exports with a conventional name
        from step2_clean import SCOUT_DIR

        SCOUT_DIR.mkdir(parents=True, exist_ok=True)
        side_letter = "D" if role == "opponent_defense" else "O"
        dest = SCOUT_DIR / f"{opp_name} {side_letter}.xlsx"
        dest.write_bytes(uploaded.getvalue())
        scout_path = dest
    elif scout_pick != "(no scout — OK for scrimmage)":
        hit = next((f for f in scout_files if f["label"] == scout_pick), None)
        if hit:
            scout_path = hit["path"]
            role = hit.get("role") or role

    try:
        result = start_new_live_game(
            opp_name,
            notes=notes,
            add_to_schedule=add_sched,
            archive_log=archive,
            load_starters_lineup=load_st,
            scout_path=scout_path,
            scout_role=role,
        )
    except Exception as exc:
        st.error(f"Could not start game: {exc}")
        return

    _reset_live_track_session_for_new_game(opp_name)
    bits = [f"Ready vs **{opp_name}** · 1st half"]
    promo = result.get("promoted") or {}
    if promo.get("merged"):
        bits.append(
            f"Game Review +{promo.get('plays', 0)} vs {promo.get('opponent')}"
        )
    elif promo.get("promoted") and promo.get("reason") == "hudl_exists":
        bits.append(
            f"saved live game vs {promo.get('opponent')} (Hudl already has that game)"
        )
    elif promo.get("promoted"):
        bits.append(f"saved live game vs {promo.get('opponent')}")
    if result.get("archived"):
        bits.append(f"log archived → `{Path(result['archived']).name}`")
    else:
        bits.append("live log cleared")
    if result.get("schedule_added"):
        bits.append("added to schedule")
    if result.get("starters_loaded"):
        bits.append("starters loaded")
    if scout_path:
        bits.append(f"scout {result.get('scout_rows', 0)} plays")
    else:
        bits.append("no scout (tracking-only)")
    if result.get("scout_error"):
        st.warning(f"Scout import issue: {result['scout_error']} — tracking still works.")
    if result.get("promote_error"):
        st.warning(f"Game Review save issue: {result['promote_error']}")
    st.success(" · ".join(bits))

    # Auto matchup report when scout defense landed
    if (
        scout_path
        and result.get("scout_rows")
        and role == "opponent_defense"
        and not result.get("scout_error")
    ):
        try:
            from mesh_engine import build_scout_matchup_report

            off_epa = load_plays("Offense")
            report = build_scout_matchup_report(
                opp_name,
                off_epa,
                booth_front_mode="even_42",
            )
            saved = _save_scout_matchup_report(report)
            st.session_state["lt_scout_matchup_report"] = report
            if saved:
                st.caption(f"Matchup report saved → `{saved.name}`")
            _render_scout_matchup_report(
                report, key_prefix="lt_newgame_match", expanded=True
            )
            st.info(
                "Review edges/traps above, then open **Game Plan** to pin calls for tonight."
            )
            # Don't auto-rerun — leave report on screen
            return
        except Exception as exc:
            st.warning(f"Scout imported, but matchup report failed: {exc}")

    st.rerun()


def _render_booth_role_gate() -> None:
    """First screen after unlock: Main (full app) or Tagger (pick focuses)."""
    from booth_stations import apply_bookmark_role, role_chosen

    # Bookmarks skip the chooser
    if apply_bookmark_role(st.session_state, st.query_params) and role_chosen(st.session_state):
        return

    if role_chosen(st.session_state) and not st.session_state.get("booth_role_force_pick"):
        return

    st.session_state.pop("booth_role_force_pick", None)

    st.markdown(
        """
        <style>
        div[data-testid="stMainBlockContainer"] { max-width: 520px; margin: 0 auto; }
        div[data-testid="stButton"] > button {
            min-height: 4.5rem !important;
            font-size: 1.35rem !important;
            border-radius: 12px !important;
            font-weight: 600 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("## Who is this device?")
    st.caption("Main sees the full booth. Taggers only see what they pick next.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Main", type="primary", use_container_width=True, key="role_main"):
            st.session_state.booth_role = "main"
            st.session_state.booth_station = "full"
            st.session_state.booth_station_locked = False
            try:
                if "station" in st.query_params:
                    del st.query_params["station"]
                if "focus" in st.query_params:
                    del st.query_params["focus"]
            except Exception:
                pass
            st.rerun()
    with c2:
        if st.button("Tagger", use_container_width=True, key="role_tagger"):
            st.session_state.booth_role = "tagger"
            st.session_state.booth_station = "tag"
            st.session_state.booth_station_locked = True
            st.session_state.tag_focuses = []
            st.session_state.tag_focus_force_edit = True
            try:
                st.query_params["station"] = "tag"
            except Exception:
                pass
            st.rerun()
    st.stop()


def _render_tag_focus_picker(*, require_save: bool = True) -> list[str]:
    """Pick a pre+post pack (2-tagger default) — balanced across the snap."""
    from booth_stations import (
        FOCUS_HELP,
        FOCUS_LABELS,
        TAGGER_JOBS,
        TAGGER_PACK_THIRD,
        TAGGER_PACKS,
        TAGGER_SPLIT_HELP,
        normalize_focuses,
    )

    st.markdown(
        """
        <style>
        div[data-testid="stMainBlockContainer"] { max-width: 480px; margin: 0 auto; }
        div[data-testid="stButton"] > button {
            min-height: 4.2rem !important;
            font-size: 1.25rem !important;
            border-radius: 12px !important;
            font-weight: 700 !important;
        }
        [data-testid="stSidebar"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("## Your phone")
    st.caption(TAGGER_SPLIT_HELP)

    def _pick_pack(pack: dict) -> None:
        foc = list(pack["focuses"])
        st.session_state.tag_focuses = foc
        st.session_state.tag_pack_id = pack["id"]
        st.session_state.tag_focus_force_edit = False
        st.session_state.pop("tag_focus_draft", None)
        try:
            st.query_params["station"] = "tag"
            st.query_params["focus"] = ",".join(foc)
        except Exception:
            pass
        st.rerun()

    st.markdown("### 1 tagger (recommended)")
    for pack in TAGGER_PACKS:
        if st.button(
            f"{pack['label']}",
            key=f"tag_pack_{pack['id']}",
            use_container_width=True,
            type="primary",
            help=pack["subtitle"],
        ):
            _pick_pack(pack)
        st.caption(pack["subtitle"])

    st.markdown("### 2nd phone (optional)")
    if st.button(
        TAGGER_PACK_THIRD["label"],
        key=f"tag_pack_{TAGGER_PACK_THIRD['id']}",
        use_container_width=True,
        type="secondary",
        help=TAGGER_PACK_THIRD["subtitle"],
    ):
        _pick_pack(TAGGER_PACK_THIRD)
    st.caption(TAGGER_PACK_THIRD["subtitle"])

    with st.expander("Single field only (not recommended)", expanded=False):
        for key in TAGGER_JOBS:
            if st.button(
                FOCUS_LABELS.get(key, key),
                key=f"tag_job_single_{key}",
                use_container_width=True,
            ):
                st.session_state.tag_focuses = [key]
                st.session_state.tag_focus_force_edit = False
                try:
                    st.query_params["station"] = "tag"
                    st.query_params["focus"] = key
                except Exception:
                    pass
                st.rerun()
            st.caption(FOCUS_HELP.get(key, ""))

    if require_save:
        st.caption("Tap a pack above.")
    return normalize_focuses(st.session_state.get("tag_focuses"))


def _booth_upsert_snap(
    *,
    drive_id: int,
    play_n: int,
    updates: dict,
    opponent: str,
    half: int = 1,
) -> tuple[bool, int | None, str]:
    from booth_snaps import upsert_live_snap
    from mesh_engine import load_live_log

    return upsert_live_snap(
        drive_id=drive_id,
        play_n=play_n,
        updates=updates,
        opponent=opponent,
        half=half,
        append_fn=append_live_log,
        update_at_fn=update_live_log_at,
        load_fn=load_live_log,
    )


def _render_shared_snap_bar(
    opponent: str,
    *,
    can_control: bool = True,
    key_prefix: str = "snap",
    minimal: bool = False,
) -> tuple[int | None, int]:
    """
    Shared Drive # · Play # bar.
    minimal=True (taggers): independent play index — only join Main on a new drive.
    Full/Main: can follow or set the shared booth_snap pointer.
    """
    from booth_snaps import (
        load_booth_snap,
        set_booth_snap_play,
        snap_label,
        sync_booth_snap_to_drive,
    )
    from mesh_engine import load_live_log

    did = current_drive_id(opponent)
    half = int(st.session_state.get("lt_half") or 1)
    logs = load_live_log()
    if did is not None:
        shared = sync_booth_snap_to_drive(opponent, int(did), half=half, live_logs=logs)
    else:
        shared = load_booth_snap()
        did = shared.get("drive_id")

    shared_pn = int(shared.get("play_n") or 1)
    tagger_mode = bool(minimal and not can_control)
    bound_key = f"{key_prefix}_bound_drive"
    follow = st.session_state.get(f"{key_prefix}_follow", not tagger_mode)

    if tagger_mode:
        # Independent pace: only reset when Main opens a different drive
        prev_did = st.session_state.get(bound_key)
        if did is None:
            st.session_state.pop(bound_key, None)
            st.session_state[f"{key_prefix}_view_drive"] = None
            if f"{key_prefix}_view_play" not in st.session_state:
                st.session_state[f"{key_prefix}_view_play"] = 1
        elif prev_did != did:
            st.session_state[bound_key] = int(did)
            st.session_state[f"{key_prefix}_view_drive"] = int(did)
            # Join Main's open slot on a new drive; pace independently after that
            st.session_state[f"{key_prefix}_view_play"] = int(shared_pn)
            st.session_state[f"{key_prefix}_follow"] = False
            st.session_state.pop("tagger_done_play", None)
        elif f"{key_prefix}_view_play" not in st.session_state:
            st.session_state[f"{key_prefix}_view_drive"] = int(did)
            st.session_state[f"{key_prefix}_view_play"] = int(shared_pn)
            st.session_state[f"{key_prefix}_follow"] = False
        # Optional: user hit "Sync to Main" → follow for one sync then stay independent
        if follow:
            st.session_state[f"{key_prefix}_view_drive"] = did
            st.session_state[f"{key_prefix}_view_play"] = shared_pn
            st.session_state[f"{key_prefix}_follow"] = False
    else:
        if follow or f"{key_prefix}_view_drive" not in st.session_state:
            st.session_state[f"{key_prefix}_view_drive"] = did
            st.session_state[f"{key_prefix}_view_play"] = shared_pn

    view_did = st.session_state.get(f"{key_prefix}_view_drive")
    view_pn = int(st.session_state.get(f"{key_prefix}_view_play") or shared_pn)

    st.markdown(
        f'<div class="ql-drive{" open" if did else ""}">{snap_label(view_did, view_pn)}</div>',
        unsafe_allow_html=True,
    )

    if minimal:
        if did is None:
            st.caption("Waiting for Main to start a drive…")
        elif tagger_mode:
            lag = int(view_pn) - int(shared_pn)
            if lag == 0:
                pace = "same play as Main"
            elif lag < 0:
                pace = f"Main on #{shared_pn} · you behind"
            else:
                pace = f"Main on #{shared_pn} · you ahead"
            st.caption(f"Your play · {pace} · merges by Drive+Play #")
            if int(view_pn) != int(shared_pn):
                if st.button(
                    f"Jump to Main · Play #{shared_pn}",
                    use_container_width=True,
                    key=f"{key_prefix}_sync_main",
                ):
                    st.session_state[f"{key_prefix}_follow"] = True
                    st.rerun()
        elif follow:
            st.caption("Following live")
        else:
            st.caption(f"Catch-up · Play #{view_pn}")
            if st.button(
                "Back to live",
                type="primary",
                use_container_width=True,
                key=f"{key_prefix}_follow_btn",
            ):
                st.session_state[f"{key_prefix}_follow"] = True
                st.session_state[f"{key_prefix}_view_drive"] = did
                st.session_state[f"{key_prefix}_view_play"] = shared_pn
                st.rerun()
        # Catch-up buried — stays out of the hot path
        with st.expander("More · jump / catch-up", expanded=False):
            j1, j2, j3 = st.columns([1, 1, 1])
            with j1:
                if st.button(
                    "◀",
                    use_container_width=True,
                    key=f"{key_prefix}_prev",
                    disabled=view_pn <= 1,
                ):
                    st.session_state[f"{key_prefix}_follow"] = False
                    st.session_state[f"{key_prefix}_view_play"] = max(1, view_pn - 1)
                    st.rerun()
            with j2:
                if st.button("▶", use_container_width=True, key=f"{key_prefix}_next"):
                    st.session_state[f"{key_prefix}_follow"] = False
                    st.session_state[f"{key_prefix}_view_play"] = view_pn + 1
                    st.rerun()
            with j3:
                jump_n = st.number_input(
                    "Play",
                    min_value=1,
                    value=int(view_pn),
                    step=1,
                    key=f"{key_prefix}_jump_n",
                    label_visibility="collapsed",
                )
                if st.button("Go", use_container_width=True, key=f"{key_prefix}_jump_go"):
                    st.session_state[f"{key_prefix}_follow"] = False
                    st.session_state[f"{key_prefix}_view_play"] = int(jump_n)
                    if did is not None:
                        st.session_state[f"{key_prefix}_view_drive"] = int(did)
                    st.rerun()
    else:
        live_lbl = snap_label(did, shared_pn) if did else "No drive — Start on Main"
        st.caption(f"Live pointer: {live_lbl}" + (" · following" if follow else " · jumped"))
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1.2, 1.4])
        with c1:
            if st.button("◀ Prev", use_container_width=True, key=f"{key_prefix}_prev", disabled=view_pn <= 1):
                st.session_state[f"{key_prefix}_follow"] = False
                st.session_state[f"{key_prefix}_view_play"] = max(1, view_pn - 1)
                st.rerun()
        with c2:
            if st.button("Next ▶", use_container_width=True, key=f"{key_prefix}_next"):
                st.session_state[f"{key_prefix}_follow"] = False
                st.session_state[f"{key_prefix}_view_play"] = view_pn + 1
                st.rerun()
        with c3:
            if st.button("Follow live", use_container_width=True, key=f"{key_prefix}_follow_btn"):
                st.session_state[f"{key_prefix}_follow"] = True
                st.session_state[f"{key_prefix}_view_drive"] = did
                st.session_state[f"{key_prefix}_view_play"] = shared_pn
                st.rerun()
        with c4:
            jump_n = st.number_input(
                "Play #",
                min_value=1,
                value=int(view_pn),
                step=1,
                key=f"{key_prefix}_jump_n",
                label_visibility="collapsed",
            )
        with c5:
            if st.button("Go to play", use_container_width=True, key=f"{key_prefix}_jump_go"):
                st.session_state[f"{key_prefix}_follow"] = False
                st.session_state[f"{key_prefix}_view_play"] = int(jump_n)
                if did is not None:
                    st.session_state[f"{key_prefix}_view_drive"] = int(did)
                st.rerun()

        if can_control and did is not None:
            if st.button(
                "Set shared pointer here (all devices)",
                key=f"{key_prefix}_set_shared",
                help="Moves Drive/Play for every tagger following live.",
            ):
                set_booth_snap_play(
                    int(did),
                    int(st.session_state.get(f"{key_prefix}_view_play") or shared_pn),
                    opponent=opponent,
                    half=half,
                )
                st.session_state[f"{key_prefix}_follow"] = True
                st.rerun()

    view_did = st.session_state.get(f"{key_prefix}_view_drive")
    view_pn = int(st.session_state.get(f"{key_prefix}_view_play") or 1)
    try:
        view_did_i = int(view_did) if view_did is not None else None
    except (TypeError, ValueError):
        view_did_i = None
    return view_did_i, view_pn


def _tagger_focus_to_col(fid: str) -> str:
    from booth_stations import FOCUS_BLITZ, FOCUS_COVERAGE, FOCUS_FRONT, FOCUS_MOTION

    return {
        FOCUS_FRONT: "def_front",
        FOCUS_COVERAGE: "coverage",
        FOCUS_BLITZ: "blitz",
        FOCUS_MOTION: "motion",
    }.get(fid, fid)


def _tagger_field_filled(row: dict, fid: str) -> bool:
    from booth_stations import FOCUS_BLITZ

    col = _tagger_focus_to_col(fid)
    val = str(row.get(col) or "").strip()
    if fid == FOCUS_BLITZ:
        return val.lower() in {"yes", "no"}
    return bool(val)


def _tagger_pack_complete(row: dict, focuses: list[str]) -> bool:
    from booth_stations import FOCUS_COVERAGE, FOCUS_FRONT

    needed = [f for f in focuses if f != "snaps"]
    if not needed:
        return False
    if not all(_tagger_field_filled(row, f) for f in needed):
        return False
    # 1-tagger Front+Coverage pack also needs end yard (auto gain)
    if FOCUS_FRONT in focuses and FOCUS_COVERAGE in focuses:
        end = row.get("end_ball_yard")
        if end is None or str(end).strip() == "":
            return False
    return True


def _tagger_status_bits(row: dict, focuses: list[str], *, need_end_yard: bool) -> str:
    """Compact Front ✓ · Cov · End strip."""
    from booth_stations import FOCUS_BLITZ, FOCUS_COVERAGE, FOCUS_FRONT, FOCUS_MOTION

    bits: list[str] = []
    checks = [
        (FOCUS_FRONT, "Front", "def_front"),
        (FOCUS_COVERAGE, "Cov", "coverage"),
        (FOCUS_BLITZ, "Blitz", "blitz"),
        (FOCUS_MOTION, "Motion", "motion"),
    ]
    for fid, label, col in checks:
        if fid not in focuses:
            continue
        ok = _tagger_field_filled(row, fid)
        bits.append(f"{label} ✓" if ok else label)
    if need_end_yard:
        end = row.get("end_ball_yard")
        end_ok = end is not None and str(end).strip() != ""
        bits.append("End ✓" if end_ok else "End")
    return " · ".join(bits) if bits else ""


def _tagger_advance_after_save(play_n: int, key_prefix: str = "tag") -> None:
    """Pack done — advance THIS tagger only; Main keeps its own play pointer."""
    nxt = int(play_n) + 1
    st.session_state[f"{key_prefix}_follow"] = False
    st.session_state[f"{key_prefix}_view_play"] = nxt
    st.session_state.pop("tagger_done_play", None)
    st.session_state["tagger_flash"] = f"✓ Play #{int(play_n)} saved — on Play #{nxt}"
    st.session_state["tagger_flash_strong"] = True


def _tagger_focus_clear_updates(focuses: list[str], *, need_end_yard: bool) -> dict:
    """Blank the fields this tagger owns (does not wipe Main call/result)."""
    from booth_stations import FOCUS_SNAPS

    updates: dict = {}
    for fid in focuses:
        if fid == FOCUS_SNAPS:
            continue
        col = _tagger_focus_to_col(fid)
        if col:
            updates[col] = ""
    if need_end_yard:
        updates["end_ball_yard"] = ""
    updates["film_pending"] = "Yes"
    return updates


def _tagger_row_has_tags(row: dict, focuses: list[str], *, need_end_yard: bool) -> bool:
    if any(_tagger_field_filled(row, f) for f in focuses if f != "snaps"):
        return True
    if need_end_yard:
        end = row.get("end_ball_yard")
        if end is not None and str(end).strip() != "":
            return True
    return False


def _tagger_undo_tags(
    *,
    opponent: str,
    half: int,
    drive_id: int,
    play_n: int,
    focuses: list[str],
    key_prefix: str = "tag",
) -> None:
    """
    Undo this tagger's last mistake:
    - If current play has tags → clear them and stay.
    - Else if play > 1 → step back one play and clear that play's tags.
    Never deletes Main's LOG fields or advances/rewinds the shared pointer.
    """
    from booth_stations import FOCUS_COVERAGE, FOCUS_FRONT
    from booth_snaps import find_snap_index
    from mesh_engine import load_live_log

    need_end = FOCUS_FRONT in focuses and FOCUS_COVERAGE in focuses
    target_pn = int(play_n)
    logs = load_live_log()
    idx = find_snap_index(logs, int(drive_id), target_pn)
    row = {}
    if idx is not None and logs is not None and not logs.empty:
        row = logs.reset_index(drop=True).loc[idx].to_dict()

    if not _tagger_row_has_tags(row, focuses, need_end_yard=need_end) and target_pn > 1:
        target_pn = target_pn - 1
        idx = find_snap_index(logs, int(drive_id), target_pn)
        row = {}
        if idx is not None and logs is not None and not logs.empty:
            row = logs.reset_index(drop=True).loc[idx].to_dict()

    if idx is None or not _tagger_row_has_tags(row, focuses, need_end_yard=need_end):
        st.session_state["tagger_flash"] = "Nothing to undo"
        st.session_state[f"{key_prefix}_view_play"] = target_pn
        st.rerun()
        return

    # Force-clear (upsert merge intentionally ignores blanks to protect parallel tags)
    clear = _tagger_focus_clear_updates(focuses, need_end_yard=need_end)
    ok = update_live_log_at(int(idx), clear)
    st.session_state.pop(f"tg_draft_front_{drive_id}_{target_pn}", None)
    st.session_state.pop(f"tg_draft_cov_{drive_id}_{target_pn}", None)
    st.session_state.pop(f"tg_edit_look_{drive_id}_{target_pn}", None)
    st.session_state.pop("tagger_done_play", None)
    st.session_state[f"{key_prefix}_follow"] = False
    st.session_state[f"{key_prefix}_view_play"] = int(target_pn)
    if ok:
        st.session_state["tagger_flash"] = f"Undid tags on Play #{int(target_pn)}"
        st.session_state["tagger_flash_strong"] = True
    else:
        st.session_state["tagger_flash"] = "Undo failed"
    st.rerun()


def _tagger_pulse_done() -> None:
    """Strong flash + light haptic on phones that support vibrate."""
    try:
        import streamlit.components.v1 as components

        components.html(
            "<script>try{navigator.vibrate([50,40,50]);}catch(e){}</script>",
            height=0,
        )
    except Exception:
        pass


def _tagger_recalc_yards_from_end(row: dict) -> dict:
    """If Main already logged result + start ball, apply end → yards_gained."""
    raw_end = row.get("end_ball_yard")
    raw_start = row.get("ball_yard")
    if raw_end is None or str(raw_end).strip() == "":
        return {}
    if raw_start is None or str(raw_start).strip() == "":
        return {}
    result_l = str(row.get("result") or "").strip().lower()
    if result_l in {"incomplete", "inc", "turnover", "int", "fumble"}:
        return {"yards_gained": 0}
    if not result_l:
        # Main hasn't logged outcome yet — end spot waits for commit
        return {}
    auto = yards_from_ball_span(raw_start, raw_end)
    if auto is None:
        return {}
    return {"yards_gained": int(auto)}


def _tagger_instant_save(
    *,
    opponent: str,
    half: int,
    drive_id: int,
    play_n: int,
    focuses: list[str],
    field_updates: dict,
    key_prefix: str = "tag",
) -> None:
    """Save field(s), remember sticky last, mark done when pack is complete."""
    from booth_stations import FOCUS_BLITZ, FOCUS_COVERAGE, FOCUS_FRONT, FOCUS_MOTION
    from booth_snaps import find_snap_index
    from mesh_engine import load_live_log

    clean = {}
    for k, v in field_updates.items():
        if v is None:
            continue
        if isinstance(v, str) and not str(v).strip() and k != "blitz":
            continue
        clean[k] = v
    if not clean:
        return

    ok, _, msg = _booth_upsert_snap(
        drive_id=int(drive_id),
        play_n=int(play_n),
        updates=clean,
        opponent=opponent,
        half=half,
    )
    if not ok:
        st.session_state["tagger_flash"] = msg or "Save failed"
        st.rerun()
        return

    # Sticky last values
    col_to_focus = {
        "def_front": FOCUS_FRONT,
        "coverage": FOCUS_COVERAGE,
        "blitz": FOCUS_BLITZ,
        "motion": FOCUS_MOTION,
    }
    for col, val in clean.items():
        fid = col_to_focus.get(col)
        if fid:
            st.session_state[f"tag_last_{fid}"] = val
    if "end_ball_yard" in clean:
        try:
            end_i = int(clean["end_ball_yard"])
            st.session_state["tag_last_end_side"] = "Own" if end_i <= 50 else "Opp"
            st.session_state["tag_last_end_yard"] = end_i if end_i <= 50 else 100 - end_i
        except (TypeError, ValueError):
            pass

    # Clear look drafts after a committed look save
    if "def_front" in clean or "coverage" in clean:
        st.session_state.pop(f"tg_draft_front_{drive_id}_{play_n}", None)
        st.session_state.pop(f"tg_draft_cov_{drive_id}_{play_n}", None)

    logs = load_live_log()
    idx = find_snap_index(logs, int(drive_id), int(play_n))
    row = {}
    if idx is not None and logs is not None and not logs.empty:
        row = logs.reset_index(drop=True).loc[idx].to_dict()
    row.update(clean)

    if "end_ball_yard" in clean:
        yard_fix = _tagger_recalc_yards_from_end(row)
        if yard_fix:
            _booth_upsert_snap(
                drive_id=int(drive_id),
                play_n=int(play_n),
                updates=yard_fix,
                opponent=opponent,
                half=half,
            )
            row.update(yard_fix)
            st.session_state["tagger_flash"] = (
                f"End {format_ball_spot(clean['end_ball_yard'])} → "
                f"{int(yard_fix['yards_gained']):+d} yds"
            )

    if _tagger_pack_complete(row, focuses):
        _tagger_advance_after_save(play_n, key_prefix=key_prefix)
    else:
        if "tagger_flash" not in st.session_state:
            st.session_state["tagger_flash"] = "Saved"
    st.rerun()


def _render_current_snap_tagger(
    opponent: str,
    offense_df: pd.DataFrame,
    focuses: list[str],
    *,
    drive_id: int | None,
    play_n: int,
) -> None:
    """Tagger editor: tap chip = save; Same as last; advances on own pace."""
    from booth_stations import (
        FOCUS_BLITZ,
        FOCUS_COVERAGE,
        FOCUS_FRONT,
        FOCUS_LABELS,
        FOCUS_MOTION,
        FOCUS_SNAPS,
        POST_SNAP_FOCUSES,
        PRE_SNAP_FOCUSES,
        focus_summary,
        has_snaps_focus,
    )
    from booth_snaps import find_snap_index
    from mesh_engine import load_live_log, scout_favorite_looks

    if drive_id is None:
        st.info("Waiting for Main to start the drive…")
        return

    half = int(st.session_state.get("lt_half") or 1)
    logs = load_live_log()
    idx = find_snap_index(logs, int(drive_id), int(play_n))
    row = {}
    if idx is not None and logs is not None and not logs.empty:
        row = logs.reset_index(drop=True).loc[idx].to_dict()

    pre = [f for f in focuses if f in PRE_SNAP_FOCUSES]
    post = [f for f in focuses if f in POST_SNAP_FOCUSES]
    need_end_yard = FOCUS_FRONT in focuses and FOCUS_COVERAGE in focuses
    batch_look = need_end_yard  # Front+Coverage pack → one write when both set
    title = " · ".join(FOCUS_LABELS.get(f, f) for f in focuses) or focus_summary(focuses)
    st.markdown(f'<p class="live-title">{title}</p>', unsafe_allow_html=True)

    undo_col, _ = st.columns([1, 2])
    with undo_col:
        if st.button(
            "Undo tags",
            use_container_width=True,
            key=f"tg_undo_{drive_id}_{play_n}",
            help="Clear your tags on this play (or the previous play if this one is empty).",
        ):
            _tagger_undo_tags(
                opponent=opponent,
                half=half,
                drive_id=int(drive_id),
                play_n=int(play_n),
                focuses=focuses,
                key_prefix="tag",
            )

    # Start LOS from Main (once logged / stubbed)
    start_ball = row.get("ball_yard")
    try:
        start_i = (
            int(start_ball)
            if start_ball is not None and str(start_ball).strip() != ""
            else None
        )
    except (TypeError, ValueError):
        start_i = None
    if start_i is not None:
        st.markdown(
            f'<div class="tg-start">Start · <b>{format_ball_spot(start_i)}</b></div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("Start yard — waiting for Main (optional; you can still tag ahead)")

    status = _tagger_status_bits(row, focuses, need_end_yard=need_end_yard)
    if status:
        done = _tagger_pack_complete(row, focuses)
        cls = "tg-status done" if done else "tg-status"
        st.markdown(f'<div class="{cls}">{status}</div>', unsafe_allow_html=True)

    flash = st.session_state.pop("tagger_flash", None)
    strong = st.session_state.pop("tagger_flash_strong", False)
    if flash:
        if strong:
            st.markdown(
                f'<div class="tg-flash-ok">{flash}</div>',
                unsafe_allow_html=True,
            )
            _tagger_pulse_done()
        else:
            st.caption(str(flash))

    ensure_default_film_tags()
    full = logs if logs is not None and not logs.empty else pd.DataFrame()
    scout_looks = scout_favorite_looks(opponent, n=8)
    scout_fronts = list(scout_looks.get("fronts") or [])
    scout_covs = list(scout_looks.get("coverages") or [])

    draft_f_key = f"tg_draft_front_{drive_id}_{play_n}"
    draft_c_key = f"tg_draft_cov_{drive_id}_{play_n}"
    edit_look_key = f"tg_edit_look_{drive_id}_{play_n}"

    # SAME LOOK only (end almost never repeats) — layout 4
    look_bits = []
    look_updates: dict = {}
    for fid in focuses:
        if fid == FOCUS_SNAPS:
            continue
        raw = st.session_state.get(f"tag_last_{fid}")
        if raw is None or (isinstance(raw, str) and not str(raw).strip()):
            continue
        look_bits.append(f"{FOCUS_LABELS.get(fid, fid)} {raw}")
        look_updates[_tagger_focus_to_col(fid)] = raw

    if look_updates:
        st.markdown('<div class="tg-same-last">', unsafe_allow_html=True)
        if st.button(
            "SAME LOOK · " + " · ".join(look_bits),
            type="primary",
            use_container_width=True,
            key=f"tg_same_look_{drive_id}_{play_n}",
        ):
            _tagger_instant_save(
                opponent=opponent,
                half=half,
                drive_id=int(drive_id),
                play_n=int(play_n),
                focuses=focuses,
                field_updates=look_updates,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    def _save_look_fields(updates: dict) -> None:
        if "def_front" in updates or "coverage" in updates:
            st.session_state.pop(edit_look_key, None)
        _tagger_instant_save(
            opponent=opponent,
            half=half,
            drive_id=int(drive_id),
            play_n=int(play_n),
            focuses=focuses,
            field_updates=updates,
        )

    def _tap_front_or_cov(col: str, opt: str) -> None:
        """Batch Front+Coverage into one save when both are chosen."""
        if not batch_look:
            _save_look_fields({col: opt})
            return
        if col == "def_front":
            st.session_state[draft_f_key] = opt
        else:
            st.session_state[draft_c_key] = opt
        front = str(
            st.session_state.get(draft_f_key)
            or (opt if col == "def_front" else "")
            or row.get("def_front")
            or ""
        ).strip()
        cov = str(
            st.session_state.get(draft_c_key)
            or (opt if col == "coverage" else "")
            or row.get("coverage")
            or ""
        ).strip()
        if col == "def_front":
            front = opt
        if col == "coverage":
            cov = opt
        if front and cov:
            _save_look_fields({"def_front": front, "coverage": cov})
            return
        missing = "Coverage" if front and not cov else "Front"
        st.session_state["tagger_flash"] = f"{'Front' if col == 'def_front' else 'Coverage'} set · tap {missing}"
        st.rerun()

    def _chip_row(
        label: str,
        options: list[str],
        col: str,
        current: str = "",
        *,
        more: list[str] | None = None,
        batch: bool = False,
    ) -> None:
        st.caption(f"{label} · tap to save")
        opts = list(options)
        cols = st.columns(min(3, max(len(opts), 1)))
        for i, opt in enumerate(opts):
            with cols[i % len(cols)]:
                active = str(current or "").strip().lower() == str(opt).strip().lower()
                if st.button(
                    opt,
                    key=f"tg_chip_{col}_{drive_id}_{play_n}_{i}",
                    use_container_width=True,
                    type="primary" if active else "secondary",
                ):
                    if batch:
                        _tap_front_or_cov(col, opt)
                    else:
                        _save_look_fields({col: opt})
        extra = [x for x in (more or []) if x not in opts]
        if extra:
            with st.expander("More…", expanded=False):
                mcols = st.columns(min(3, max(len(extra), 1)))
                for i, opt in enumerate(extra):
                    with mcols[i % len(mcols)]:
                        active = (
                            str(current or "").strip().lower()
                            == str(opt).strip().lower()
                        )
                        if st.button(
                            opt,
                            key=f"tg_chip_more_{col}_{drive_id}_{play_n}_{i}",
                            use_container_width=True,
                            type="primary" if active else "secondary",
                        ):
                            if batch:
                                _tap_front_or_cov(col, opt)
                            else:
                                _save_look_fields({col: opt})

    def _render_field(fid: str) -> None:
        cur_col = _tagger_focus_to_col(fid)
        current = str(row.get(cur_col) or "")
        if fid == FOCUS_FRONT:
            draft = str(st.session_state.get(draft_f_key) or "").strip()
            if draft:
                current = draft
            ordered = list(scout_fronts) if scout_fronts else list(DEFAULT_FILM_FRONTS)
            src = "scout" if scout_fronts else "defaults"
            top, rest = ordered[:3], ordered[3:]
            _chip_row(
                f"Front · {src} top 3",
                top,
                "def_front",
                current,
                more=rest,
                batch=batch_look,
            )
        elif fid == FOCUS_COVERAGE:
            draft = str(st.session_state.get(draft_c_key) or "").strip()
            if draft:
                current = draft
            ordered = list(scout_covs) if scout_covs else list(DEFAULT_FILM_COVERAGES)
            src = "scout" if scout_covs else "defaults"
            top, rest = ordered[:3], ordered[3:]
            _chip_row(
                f"Coverage · {src} top 3",
                top,
                "coverage",
                current,
                more=rest,
                batch=batch_look,
            )
        elif fid == FOCUS_BLITZ:
            st.caption("Blitz · tap to save")
            cur_b = current.strip().title() if current else ""
            b1, b2 = st.columns(2)
            with b1:
                if st.button(
                    "No",
                    key=f"tg_blitz_no_{drive_id}_{play_n}",
                    use_container_width=True,
                    type="primary" if cur_b == "No" else "secondary",
                ):
                    _save_look_fields({"blitz": "No"})
            with b2:
                if st.button(
                    "Yes",
                    key=f"tg_blitz_yes_{drive_id}_{play_n}",
                    use_container_width=True,
                    type="primary" if cur_b == "Yes" else "secondary",
                ):
                    _save_look_fields({"blitz": "Yes"})
        elif fid == FOCUS_MOTION:
            motion_opts = _merge_tag_options(
                _tag_options(
                    offense_df["motion"]
                    if "motion" in offense_df.columns
                    else pd.Series(dtype=str),
                ),
                full["motion"] if "motion" in full.columns else pd.Series(dtype=str),
                kind="motion",
            )
            for m in _hudl_motion_options():
                if m not in motion_opts:
                    motion_opts.append(m)
            preferred = ["None", "Orbit", "Jet", "Across"]
            ordered = list(preferred)
            for p in motion_opts:
                if p not in ordered:
                    ordered.append(p)
            _chip_row("Motion", ordered[:3], "motion", current, more=ordered[3:8])

    front_saved = str(row.get("def_front") or "").strip()
    cov_saved = str(row.get("coverage") or "").strip()
    look_complete = bool(front_saved and cov_saved) if need_end_yard else False
    editing_look = bool(st.session_state.get(edit_look_key))

    # Layout 4 — collapse look when Front+Cov set; keep End pinned
    if look_complete and not editing_look:
        st.markdown(
            f'<div class="tg-look-collapsed">Look · {front_saved} / {cov_saved}</div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "Edit look",
            key=f"tg_edit_look_btn_{drive_id}_{play_n}",
            use_container_width=True,
        ):
            st.session_state[edit_look_key] = True
            st.rerun()
    else:
        if pre:
            st.markdown("##### Pre-snap")
            for fid in pre:
                _render_field(fid)
        if post:
            st.markdown("##### Post-snap")
            for fid in post:
                _render_field(fid)

    if need_end_yard:
        st.markdown('<div class="tg-end-pin">', unsafe_allow_html=True)
        st.markdown("##### End of play")
        st.caption("Tap side + yard · saves immediately · gain = end − start")
        side_key = f"tg_end_side_{drive_id}_{play_n}"
        if side_key not in st.session_state:
            st.session_state[side_key] = st.session_state.get("tag_last_end_side") or "Own"
        cur_end = row.get("end_ball_yard")
        try:
            cur_end_i = (
                int(cur_end)
                if cur_end is not None and str(cur_end).strip() != ""
                else None
            )
        except (TypeError, ValueError):
            cur_end_i = None
        if cur_end_i is not None:
            st.session_state[side_key] = "Own" if cur_end_i <= 50 else "Opp"

        s1, s2 = st.columns(2)
        with s1:
            if st.button(
                "Own",
                key=f"tg_side_own_{drive_id}_{play_n}",
                use_container_width=True,
                type="primary" if st.session_state[side_key] == "Own" else "secondary",
            ):
                st.session_state[side_key] = "Own"
                st.rerun()
        with s2:
            if st.button(
                "Opp",
                key=f"tg_side_opp_{drive_id}_{play_n}",
                use_container_width=True,
                type="primary" if st.session_state[side_key] == "Opp" else "secondary",
            ):
                st.session_state[side_key] = "Opp"
                st.rerun()

        end_side = st.session_state[side_key]
        yard_opts = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
        cur_yd = None
        if cur_end_i is not None:
            cur_yd = cur_end_i if cur_end_i <= 50 else 100 - cur_end_i
        ycols = st.columns(5)
        for i, yd in enumerate(yard_opts):
            with ycols[i % 5]:
                active = False
                if cur_end_i is not None and cur_yd == yd:
                    saved_side = "Own" if cur_end_i <= 50 else "Opp"
                    active = saved_side == end_side
                if st.button(
                    str(yd),
                    key=f"tg_yd_{drive_id}_{play_n}_{yd}",
                    use_container_width=True,
                    type="primary" if active else "secondary",
                ):
                    end_ball = side_yard_to_ball_yard(end_side, int(yd))
                    _save_look_fields({"end_ball_yard": end_ball})

        z1, z2 = st.columns(2)
        with z1:
            same_disabled = start_i is None
            if st.button(
                "Same as start (0)",
                use_container_width=True,
                key=f"tg_end_same_{drive_id}_{play_n}",
                disabled=same_disabled,
                help="No gain — end = start",
            ):
                _save_look_fields({"end_ball_yard": int(start_i)})
        with z2:
            if st.button(
                "Inc → 0",
                use_container_width=True,
                key=f"tg_end_inc_{drive_id}_{play_n}",
                disabled=same_disabled,
                help="Incomplete / no gain — end = start",
            ):
                _save_look_fields({"end_ball_yard": int(start_i)})
        if start_i is None:
            st.caption("Same as start / Inc need Main’s start yard")
        elif cur_end_i is not None:
            g = yards_from_ball_span(start_i, cur_end_i)
            if g is not None:
                st.caption(
                    f"{format_ball_spot(start_i)} → {format_ball_spot(cur_end_i)} = {g:+d}"
                )
        st.markdown("</div>", unsafe_allow_html=True)

    if has_snaps_focus(focuses) and FOCUS_SNAPS in focuses:
        st.caption("Snap fields still use Save (Main usually logs these).")
        form = st.text_input(
            "Formation",
            value=str(row.get("formation") or ""),
            key=f"snap_form_{drive_id}_{play_n}",
        )
        play = st.text_input(
            "Play",
            value=str(row.get("play_call") or ""),
            key=f"snap_play_{drive_id}_{play_n}",
        )
        if st.button(
            "Save snap fields",
            type="primary",
            use_container_width=True,
            key=f"snap_save_{drive_id}_{play_n}",
        ):
            _tagger_instant_save(
                opponent=opponent,
                half=half,
                drive_id=int(drive_id),
                play_n=int(play_n),
                focuses=focuses,
                field_updates={
                    "formation": form,
                    "play_call": play,
                    "film_pending": "Yes",
                },
            )


def _booth_switch_role_control() -> None:
    """Small escape hatch to re-open Main / Tagger chooser."""
    if st.sidebar.button("Switch Main / Tagger", key="booth_switch_role"):
        for k in (
            "booth_role",
            "booth_station",
            "booth_station_locked",
            "tag_focuses",
            "tag_focus_draft",
            "tag_focus_force_edit",
            "booth_role_force_pick",
        ):
            st.session_state.pop(k, None)
        st.session_state.booth_role_force_pick = True
        try:
            if "station" in st.query_params:
                del st.query_params["station"]
            if "focus" in st.query_params:
                del st.query_params["focus"]
        except Exception:
            pass
        st.rerun()


def _resolve_booth_base_url() -> str:
    """Best-known public URL for sharing tagger invites."""
    import os

    from booth_stations import normalize_base_url
    from team_config import booth_public_url

    for candidate in (
        st.session_state.get("booth_base_url"),
        os.environ.get("BOOTH_PUBLIC_URL"),
        booth_public_url(),
    ):
        base = normalize_base_url(str(candidate or ""))
        if base:
            return base
    try:
        headers = getattr(st, "context", None) and st.context.headers
        if headers:
            host = headers.get("Host") or headers.get("host") or ""
            proto = headers.get("X-Forwarded-Proto") or headers.get("x-forwarded-proto") or "https"
            if host and "localhost" not in str(host).lower():
                return normalize_base_url(f"{proto}://{host}")
    except Exception:
        pass
    return ""


def _import_booth_stations():
    """Load local booth_stations.py (avoids stale/shadowed Cloud imports)."""
    import importlib
    import importlib.util
    import sys
    from pathlib import Path

    # Prefer the file next to this dashboard (Streamlit Cloud /mount/src/…)
    path = Path(__file__).resolve().parent / "booth_stations.py"
    if path.is_file():
        spec = importlib.util.spec_from_file_location("_booth_stations_app", path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["_booth_stations_app"] = mod
            spec.loader.exec_module(mod)
            return mod
    return importlib.import_module("booth_stations")


def _render_home_page() -> None:
    """Main booth home: tonight status + tagger invite links."""
    try:
        bs = _import_booth_stations()
        FOCUS_HELP = bs.FOCUS_HELP
        FOCUS_LABELS = bs.FOCUS_LABELS
        TAGGER_PACK_THIRD = bs.TAGGER_PACK_THIRD
        TAGGER_PACKS = bs.TAGGER_PACKS
        TAGGER_SPLIT_HELP = bs.TAGGER_SPLIT_HELP
        main_invite_url = bs.main_invite_url
        tagger_invite_url = bs.tagger_invite_url
    except Exception as exc:
        st.error(
            "Could not load booth invite helpers. "
            "Reboot the Streamlit Cloud app or redeploy from latest `main` "
            "(needs current `booth_stations.py`)."
        )
        st.exception(exc)
        return
    from team_config import booth_pin, load_team_config, save_booth_public_url

    cfg = load_team_config()
    team = str(cfg.get("team_name") or "Home")
    pin = booth_pin() or "—"

    st.markdown(
        f'<p class="live-title">{team} · Booth</p>',
        unsafe_allow_html=True,
    )
    st.caption("Main device · share invite links with extra taggers")

    # Opponent / half snapshot
    try:
        from mesh_engine import load_game_state, load_season_opponents

        gstate = load_game_state()
        opp = str(
            st.session_state.get("lt_page_opponent")
            or gstate.get("opponent")
            or ""
        ).strip()
        if not opp:
            opps = load_season_opponents()
            opp = opps[0] if opps else "—"
        half = st.session_state.get("lt_half") or gstate.get("half") or 1
    except Exception:
        opp, half = "—", 1

    m1, m2, m3 = st.columns(3)
    m1.metric("Opponent", opp)
    m2.metric("Half", str(half))
    m3.metric("Booth PIN", pin)

    # Main-only DB setup (taggers never see this page)
    try:
        off = load_plays("Offense")
        deff = load_plays("Defense")
    except Exception:
        off, deff = None, None
    if not _epa_db_ready(off, deff):
        st.warning(
            "Season database not loaded yet — upload it here once. "
            "Taggers will wait until you finish."
        )
        with st.expander("Upload database (Main only)", expanded=True):
            _render_first_run_wizard()
        st.markdown("---")
    else:
        n = len(off) if off is not None and not off.empty else 0
        st.success(f"Database ready · **{n:,}** offense plays · taggers can join")

    if st.button("Open Live Track →", type="primary", key="home_goto_live"):
        st.session_state.lt_nav_page = "Live Track"
        st.rerun()

    st.markdown("---")
    st.markdown("### Invite taggers")
    st.caption(TAGGER_SPLIT_HELP)

    base = _resolve_booth_base_url()
    with st.expander("Set booth website URL", expanded=not bool(base)):
        st.caption(
            "Paste your Streamlit Cloud link once (e.g. https://your-app.streamlit.app). "
            "Saved for invite links on this Home page."
        )
        url_in = st.text_input(
            "Booth URL",
            value=base,
            key="home_booth_url_input",
            placeholder="https://your-app.streamlit.app",
            label_visibility="collapsed",
        )
        if st.button("Save URL", key="home_save_booth_url"):
            cleaned = save_booth_public_url(url_in)
            st.session_state.booth_base_url = cleaned
            st.success("Saved." if cleaned else "Cleared.")
            st.rerun()

    base = _resolve_booth_base_url()
    if not base:
        st.warning("Set the booth website URL above so invite links work.")
        return

    st.markdown("**Send one link (1 tagger)**")
    for pack in TAGGER_PACKS:
        foc = list(pack["focuses"])
        link = tagger_invite_url(base, foc)
        st.markdown(f"**Phone {pack['slot']}: {pack['label']}**")
        st.caption(pack["subtitle"])
        st.code(link, language=None)

    with st.expander("2nd phone (optional)"):
        foc = list(TAGGER_PACK_THIRD["focuses"])
        st.caption(TAGGER_PACK_THIRD["subtitle"])
        st.code(tagger_invite_url(base, foc), language=None)

    with st.expander("Let them pick the pack"):
        st.code(tagger_invite_url(base), language=None)

    with st.expander("Main device link"):
        st.code(main_invite_url(base) or base, language=None)
        st.caption("Opens as Main (full booth) after PIN.")


def live_track_page(offense_df: pd.DataFrame, defense_df: pd.DataFrame) -> None:
    """Live Track: offense play log + lineup (booth-simple)."""
    from booth_stations import (
        focus_summary,
        has_film_focus,
        has_snaps_focus,
        is_tagger_station,
        resolve_booth_station,
        resolve_tag_focuses,
    )
    from mesh_engine import load_live_log, load_season_opponents

    booth_station = resolve_booth_station(st.session_state, st.query_params)
    tagger = str(st.session_state.get("booth_role") or "").lower() == "tagger" or (
        is_tagger_station(booth_station) and st.session_state.get("booth_station_locked")
    )
    focuses = resolve_tag_focuses(st.session_state, st.query_params, booth_station)

    if tagger:
        # Stripped chrome — tagging only
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"] { display: none !important; }
            [data-testid="stHeader"] { background: transparent !important; }
            #MainMenu, footer { visibility: hidden !important; }
            div[data-testid="stMainBlockContainer"] {
                padding-top: 0.35rem !important;
                max-width: 480px !important;
            }
            div[data-testid="stButton"] > button {
                min-height: 3.4rem !important;
                font-size: 1.15rem !important;
                font-weight: 700 !important;
            }
            .tg-same-last div[data-testid="stButton"] > button {
                min-height: 4.4rem !important;
                font-size: 1.05rem !important;
                letter-spacing: 0.02em;
            }
            .tg-start {
                font-size: 1.15rem;
                font-weight: 700;
                color: #1B4332;
                margin: 0.15rem 0 0.35rem 0;
            }
            .tg-status {
                font-size: 0.95rem;
                font-weight: 600;
                color: #5c6b62;
                margin: 0 0 0.4rem 0;
                padding: 0.35rem 0.55rem;
                background: #F4F7F5;
                border-radius: 8px;
                border: 1px solid #D0DAD4;
            }
            .tg-status.done {
                color: #1B4332;
                background: #D8F3DC;
                border-color: #40916C;
            }
            .tg-flash-ok {
                font-size: 1.15rem;
                font-weight: 800;
                color: #081c15;
                background: #95D5B2;
                border: 2px solid #1B4332;
                border-radius: 10px;
                padding: 0.75rem 0.85rem;
                margin: 0.35rem 0 0.6rem 0;
                text-align: center;
            }
            /* Layout 4 — end pinned */
            .tg-end-pin {
                position: sticky;
                bottom: 0;
                z-index: 30;
                background: #ffffff;
                border-top: 2px solid #1B4332;
                padding: 0.55rem 0 0.85rem 0;
                margin-top: 0.5rem;
            }
            .tg-look-collapsed {
                font-size: 1.05rem;
                font-weight: 700;
                color: #1B4332;
                padding: 0.45rem 0.55rem;
                background: #D8F3DC;
                border-radius: 8px;
                border: 1px solid #40916C;
                margin: 0.25rem 0 0.4rem 0;
            }
            .tg-wait-lock {
                text-align: center;
                padding: 1.25rem 0.75rem;
                margin: 0.5rem 0;
                background: #F4F7F5;
                border: 2px solid #1B4332;
                border-radius: 12px;
            }
            .tg-wait-lock h3 {
                margin: 0 0 0.35rem 0;
                font-size: 1.35rem;
                color: #1B4332;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

    # Taggers must pick focuses before the simplified UI
    if tagger and (
        not focuses or st.session_state.get("tag_focus_force_edit")
    ):
        _render_tag_focus_picker()
        st.stop()
        return

    if tagger:
        pass  # title comes from current-snap editor
    elif booth_station == "full":
        # Professional Main chrome injected after opponent/half known
        pass
    else:
        st.markdown('<p class="live-title">Live Track</p>', unsafe_allow_html=True)

    season_opps = load_season_opponents()

    # Apply pending Start-new-game / half changes BEFORE those widgets exist
    pending_opp = st.session_state.pop("lt_page_opponent_pending", None)
    if pending_opp:
        st.session_state.lt_page_opponent = str(pending_opp).strip()
    pending_half = st.session_state.pop("lt_half_pending", None)
    if pending_half is not None:
        try:
            st.session_state.lt_half = int(pending_half)
        except (TypeError, ValueError):
            st.session_state.lt_half = 1

    if "lt_tablet" not in st.session_state:
        st.session_state.lt_tablet = True
    if "lt_half" not in st.session_state:
        st.session_state.lt_half = 1

    # Seed opponent early so game_state can auto-advance half before the radio exists
    default_opp = (season_opps[0] if season_opps else "Unknown")
    opponent = st.session_state.get("lt_page_opponent", default_opp)

    # Follow active game on tagger devices (coach sets opponent on Full / Call)
    try:
        from mesh_engine import load_game_state

        gstate = load_game_state()
        g_opp = str(gstate.get("opponent") or "").strip()
        if tagger and g_opp:
            st.session_state.lt_page_opponent = g_opp
            opponent = g_opp
        if (
            gstate.get("opponent")
            and str(gstate.get("opponent")).strip().lower() == str(opponent).strip().lower()
            and gstate.get("phase") in {"halftime", "2nd"}
            and int(st.session_state.get("lt_half") or 1) == 1
            and "lt_half_auto_done" not in st.session_state
        ):
            st.session_state.lt_half = 2
            st.session_state.lt_half_auto_done = True
    except Exception:
        pass

    # --- Tagger: Drive·Play + one job only ---
    if tagger and (has_film_focus(focuses) or has_snaps_focus(focuses)):
        st.session_state.lt_unit = "Offense"
        from datetime import timedelta

        @st.fragment(run_every=timedelta(seconds=1))
        def _tagger_snap_loop() -> None:
            view_did, view_pn = _render_shared_snap_bar(
                opponent, can_control=False, key_prefix="tag", minimal=True
            )
            _render_current_snap_tagger(
                opponent,
                offense_df,
                focuses,
                drive_id=view_did,
                play_n=view_pn,
            )
            with st.expander("More · change job", expanded=False):
                if st.button("Change job", key="tag_refocus_bottom"):
                    st.session_state.tag_focus_force_edit = True
                    st.rerun()

        _tagger_snap_loop()
        return

    # --- Call / Full chrome ---
    snaps_mode = (not tagger) or has_snaps_focus(focuses)
    if not snaps_mode:
        st.warning("No focuses selected.")
        _render_tag_focus_picker()
        return

    if tagger and has_snaps_focus(focuses):
        st.caption(f"vs {opponent}")
        # Keep opponent/half out of the hot path; seed keys for session
        if "lt_page_opponent" not in st.session_state:
            st.session_state.lt_page_opponent = opponent
        if "lt_half" not in st.session_state:
            st.session_state.lt_half = 1
        sheet = "Log"
        st.session_state.lt_main_sheet = "Log"
        opp_choices = list(season_opps) if season_opps else []
        cur = str(st.session_state.get("lt_page_opponent") or "").strip()
        if cur and cur not in opp_choices:
            opp_choices = [cur] + opp_choices
        if not opp_choices:
            opp_choices = ["Unknown"]
        half_now = int(st.session_state.get("lt_half") or 1)
        with st.expander(
            f"Game setup · vs {cur or opponent} · H{half_now}",
            expanded=False,
        ):
            opponent = st.selectbox(
                "Tonight's opponent",
                opp_choices,
                key="lt_page_opponent",
            )
            st.radio("Half", [1, 2], horizontal=True, key="lt_half")
            if booth_station == "full" or has_snaps_focus(focuses):
                st.markdown("---")
                _render_start_new_game_panel(season_opps)
        opponent = str(st.session_state.get("lt_page_opponent") or opponent)
    else:
        if "lt_page_opponent" not in st.session_state:
            st.session_state.lt_page_opponent = default_opp
        if "lt_half" not in st.session_state:
            st.session_state.lt_half = 1
        if st.session_state.get("lt_main_sheet") == "Play log":
            st.session_state.lt_main_sheet = "Log"
        if "lt_main_sheet" not in st.session_state:
            st.session_state.lt_main_sheet = "Log"

        opp_choices = list(season_opps) if season_opps else []
        cur = str(st.session_state.get("lt_page_opponent") or "").strip()
        if cur and cur not in opp_choices:
            opp_choices = [cur] + opp_choices
        if not opp_choices:
            opp_choices = ["Unknown"]
        half_now = int(st.session_state.get("lt_half") or 1)
        sheet_now = str(st.session_state.get("lt_main_sheet") or "Log")
        setup_open = sheet_now == "Lineup"
        with st.expander(
            f"Game setup · vs {cur or default_opp} · H{half_now}"
            + (f" · {sheet_now}" if sheet_now != "Log" else ""),
            expanded=setup_open,
        ):
            opponent = st.selectbox(
                "Tonight's opponent",
                opp_choices,
                key="lt_page_opponent",
            )
            st.radio("Half", [1, 2], horizontal=True, key="lt_half")
            sheet = st.radio(
                "Sheet",
                ["Log", "Lineup"],
                horizontal=True,
                key="lt_main_sheet",
            )
            if booth_station == "full":
                st.markdown("---")
                st.caption("Start new game")
                _render_start_new_game_panel(season_opps)
        opponent = str(st.session_state.get("lt_page_opponent") or opponent)
        sheet = str(st.session_state.get("lt_main_sheet") or "Log")

    live_logs = load_live_log()
    st.session_state.lt_unit = "Offense"

    if "lt_slots" not in st.session_state:
        st.session_state.lt_slots = {}
    if "lt_slot_gen" not in st.session_state:
        st.session_state.lt_slot_gen = 0
    get_on_field()

    if st.session_state.get("lt_tablet") or booth_station == "full":
        if booth_station == "full":
            _inject_main_booth_css()
        else:
            st.markdown(
                """
                <style>
                /* Live Track — denser booth layout (still tappable) */
                [data-testid="stMainBlockContainer"] {
                    padding-top: 0.6rem !important;
                    padding-bottom: 1rem !important;
                }
                [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {
                    gap: 0.35rem !important;
                }
                [data-testid="stHorizontalBlock"] {
                    gap: 0.4rem !important;
                }
                div[data-testid="stButton"] > button {
                    min-height: 2.35rem !important;
                    font-size: 0.95rem !important;
                    border-radius: 8px !important;
                    padding-top: 0.25rem !important;
                    padding-bottom: 0.25rem !important;
                }
                div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
                div[data-testid="stNumberInput"] input,
                div[data-testid="stTextInput"] input {
                    min-height: 2.25rem !important;
                    font-size: 0.95rem !important;
                }
                div[data-testid="stCaptionContainer"] {
                    margin-bottom: 0.1rem !important;
                }
                .block-container { max-width: 1180px; padding-top: 0.5rem !important; }
                hr { margin: 0.35rem 0 !important; }
                </style>
                """,
                unsafe_allow_html=True,
            )

    pending_n = count_film_pending(live_logs, opponent)
    _apply_pending_live_situation()

    # Main app bar (after opponent / half / pending known)
    if booth_station == "full" and not tagger:
        drive_id_bar = None
        play_n_bar = None
        try:
            drive_id_bar = current_drive_id(opponent)
            from booth_snaps import load_booth_snap

            snap = load_booth_snap()
            if drive_id_bar is not None and snap.get("drive_id") == int(drive_id_bar):
                play_n_bar = int(snap.get("play_n") or 1)
        except Exception:
            pass
        _render_main_app_bar(
            str(opponent),
            half=int(st.session_state.get("lt_half") or 1),
            pending_n=int(pending_n or 0),
            drive_id=drive_id_bar,
            play_n=play_n_bar,
        )

    if sheet == "Lineup" and booth_station == "full":
        # Compact drive bar still available on Lineup sheet
        dstate = load_drive_state()
        active_did = current_drive_id(opponent)
        can_undo = bool(dstate.get("undo_stack"))
        drive_lbl = (
            f"Drive #{active_did}" if active_did is not None else "No drive · LOG starts one"
        )
        d1, d2, d3, d4 = st.columns([1.6, 1, 1, 1])
        d1.markdown(
            f'<div class="ql-drive{" open" if active_did else ""}">{drive_lbl}</div>',
            unsafe_allow_html=True,
        )
        if d2.button(
            "Start",
            use_container_width=True,
            key="lt_start_drive",
            disabled=active_did is not None,
        ):
            st.success(f"Drive #{start_drive(opponent)} started.")
            st.rerun()
        if d3.button(
            "End drive",
            use_container_width=True,
            key="lt_end_fill",
            disabled=active_did is None,
        ):
            ended = end_drive()
            if ended is not None:
                st.session_state.ff_drive_filter = str(ended)
            st.rerun()
        if d4.button(
            "Undo", use_container_width=True, key="lt_undo_drive", disabled=not can_undo
        ):
            entry = undo_drive_action()
            if entry:
                st.success(f"Undid {entry.get('action')}.")
            st.rerun()
        _live_track_field_screen(opponent, live_logs)
        return

    # Mixed tagger: snaps + film on one device
    if tagger and has_snaps_focus(focuses) and has_film_focus(focuses):
        tab_log, tab_film = st.tabs(["Log snaps", f"Film ({focus_summary([f for f in focuses if f != 'snaps'])})"])
        with tab_log:
            _live_track_log_screen(opponent, offense_df, defense_df, live_logs, quick=True)
        with tab_film:
            _live_track_fill_film(opponent, offense_df, live_logs, focuses=focuses)
        return

    # Log vs Fill Film — only Full can switch; snap taggers stay on Log
    if "lt_play_sheet" not in st.session_state:
        st.session_state.lt_play_sheet = "Log"
    if tagger:
        st.session_state.lt_play_sheet = "Log"

    mode_opts = ["Log"]
    if booth_station == "full" and (
        pending_n or st.session_state.get("lt_play_sheet") == "Fill Film"
    ):
        mode_opts.append(f"Film ({pending_n})" if pending_n else "Film")

    label_to_mode = {"Log": "Log"}
    for o in mode_opts:
        if o.startswith("Film"):
            label_to_mode[o] = "Fill Film"
    cur_mode = st.session_state.get("lt_play_sheet") or "Log"
    default_label = next(
        (k for k, v in label_to_mode.items() if v == cur_mode),
        mode_opts[0],
    )
    # Film mode buried — keep Log hot path clean unless pending or already on Film
    if booth_station == "full" and len(mode_opts) > 1:
        if cur_mode == "Fill Film":
            chosen = st.radio(
                "Mode",
                mode_opts,
                index=mode_opts.index(default_label) if default_label in mode_opts else 0,
                horizontal=True,
                key="lt_play_sheet_label",
                label_visibility="collapsed",
            )
            st.session_state.lt_play_sheet = label_to_mode.get(chosen, "Log")
        else:
            with st.expander(f"Film inbox ({pending_n})", expanded=False):
                if st.button("Open Fill Film", key="lt_open_film", use_container_width=True):
                    st.session_state.lt_play_sheet = "Fill Film"
                    st.rerun()
            st.session_state.lt_play_sheet = "Log"
    else:
        st.session_state.lt_play_sheet = "Log"

    if st.session_state.get("lt_play_sheet") == "Fill Film" and booth_station == "full":
        _live_track_fill_film(opponent, offense_df, live_logs, focuses=None)
    elif booth_station == "full":
        # Layout C — dual pane: phrase left · situation/drive right
        @st.fragment
        def _main_dual_fragment() -> None:
            logs_now = load_live_log()
            left, right = st.columns([1.35, 1])
            with left:
                st.markdown(
                    '<div class="mb-console-title">Snap log</div>',
                    unsafe_allow_html=True,
                )
                _live_track_log_screen(
                    opponent,
                    offense_df,
                    defense_df,
                    logs_now,
                    quick=True,
                    dual_pane=True,
                )
            with right:
                _render_main_dual_rail(
                    opponent,
                    logs_now,
                    pending_n=count_film_pending(logs_now, opponent),
                    can_control_snap=True,
                )

        _main_dual_fragment()
        with st.expander("Tonight’s log", expanded=False):
            _render_live_log_tail(opponent, load_live_log())
    else:
        # Snap-only tagger / call station — single column
        dstate = load_drive_state()
        active_did = current_drive_id(opponent)
        can_undo = bool(dstate.get("undo_stack"))
        play_n_lbl = ""
        try:
            from booth_snaps import load_booth_snap

            snap = load_booth_snap()
            if active_did is not None and snap.get("drive_id") == int(active_did):
                play_n_lbl = f" · Play #{int(snap.get('play_n') or 1)}"
        except Exception:
            pass
        drive_lbl = (
            f"Drive #{active_did}{play_n_lbl}"
            if active_did is not None
            else "No drive · LOG starts one"
        )
        d1, d2, d3, d4 = st.columns([1.6, 1, 1, 1])
        d1.markdown(
            f'<div class="ql-drive{" open" if active_did else ""}">{drive_lbl}</div>',
            unsafe_allow_html=True,
        )
        if d2.button(
            "Start",
            use_container_width=True,
            key="lt_start_drive",
            disabled=active_did is not None,
        ):
            st.success(f"Drive #{start_drive(opponent)} started.")
            st.rerun()
        if d3.button(
            "End drive",
            use_container_width=True,
            key="lt_end_fill",
            disabled=active_did is None,
        ):
            ended = end_drive()
            if ended is not None:
                st.session_state.ff_drive_filter = str(ended)
            st.rerun()
        if d4.button(
            "Undo", use_container_width=True, key="lt_undo_drive", disabled=not can_undo
        ):
            entry = undo_drive_action()
            if entry:
                st.success(f"Undid {entry.get('action')}.")
            st.rerun()

        @st.fragment
        def _main_log_fragment() -> None:
            _live_track_log_screen(
                opponent, offense_df, defense_df, live_logs, quick=True
            )

        _main_log_fragment()

    if booth_station == "full":
        with st.expander("Halftime / end 1st half", expanded=False):
            _end_first_half_action(opponent, live_logs, key_prefix="lt")
        with st.expander("Drive repair (resume / reassign)", expanded=False):
            drive_choices = known_drive_ids(live_logs) or [1]
            r1, r2 = st.columns(2)
            resume_pick = r1.selectbox("Resume drive #", drive_choices, key="lt_resume_drive_pick")
            if r2.button("Resume", type="primary", key="lt_resume_drive", use_container_width=True):
                resume_drive(int(resume_pick), opponent)
                st.success(f"Back on drive #{int(resume_pick)}.")
                st.rerun()
    elif tagger and has_snaps_focus(focuses):
        with st.expander("Halftime / end 1st half", expanded=False):
            _end_first_half_action(opponent, live_logs, key_prefix="lt")



def _quick_chip_row(label: str, options: list[str], key: str, columns: int = 4) -> str:
    """Big tap chips that set session state; returns current value."""
    st.caption(label)
    if key not in st.session_state:
        st.session_state[key] = options[0] if options else ""
    cols = st.columns(min(columns, max(len(options), 1)))
    for i, opt in enumerate(options):
        with cols[i % len(cols)]:
            active = str(st.session_state.get(key, "")) == opt
            if st.button(
                opt,
                key=f"{key}_chip_{i}",
                use_container_width=True,
                type="primary" if active else "secondary",
            ):
                st.session_state[key] = opt
                st.rerun()
    return str(st.session_state.get(key, options[0] if options else ""))


def _ql_norm(val: str | None) -> str:
    """Strip + canonicalize play-call aliases (Axel → Axle)."""
    return normalize_play_call(str(val or "").strip())


def _ql_chip_active(cur: str, opt: str, *, none_label: str, allow_none: bool) -> bool:
    c = _ql_norm(cur)
    o = _ql_norm(opt)
    if allow_none and o == _ql_norm(none_label):
        return not c
    return bool(c) and c.lower() == o.lower()


def _favorite_chip_picker(
    label: str,
    favorites: list[str],
    key: str,
    *,
    columns: int = 3,
    allow_none: bool = False,
    none_label: str = "—",
    clear_keys: list[str] | None = None,
    advance_step: int | None = None,
    key_prefix: str = "",
) -> str:
    """
    One-handed favorites: tap sets sticky session value for `key` only.
    Does not clear sibling call pieces (formation / motion / play stay independent).
    """
    st.caption(label)
    opts = list(favorites)
    if allow_none:
        opts = [none_label] + opts
    if not opts:
        st.caption("No favorites yet — open Edit favorites below.")
        return _ql_norm(st.session_state.get(key))
    cols = st.columns(min(columns, max(len(opts), 1)))
    for i, opt in enumerate(opts):
        with cols[i % len(cols)]:
            cur = _ql_norm(st.session_state.get(key))
            active = _ql_chip_active(cur, opt, none_label=none_label, allow_none=allow_none)
            btn_key = f"{key_prefix}{key}_chip_{i}"
            if st.button(
                opt,
                key=btn_key,
                use_container_width=True,
                type="primary" if active else "secondary",
            ):
                st.session_state[key] = (
                    "" if (allow_none and _ql_norm(opt) == _ql_norm(none_label)) else _ql_norm(opt)
                )
                for ck in clear_keys or []:
                    st.session_state[ck] = ""
                if advance_step is not None:
                    st.session_state.ql_step = int(advance_step)
                st.rerun()
    cur = _ql_norm(st.session_state.get(key))
    if allow_none and cur.lower() == _ql_norm(none_label).lower():
        return ""
    return cur


def _ql_resolve_piece(chip_key: str, *, typed_key: str | None = None, dd_key: str | None = None) -> str:
    """Prefer typed-in override, then sticky chip, then dropdown (stale dd must not win)."""
    if typed_key:
        typed = _ql_norm(st.session_state.get(typed_key))
        if typed:
            return typed
    chip = _ql_norm(st.session_state.get(chip_key))
    if chip:
        return chip
    if dd_key:
        return _ql_norm(st.session_state.get(dd_key))
    return ""


# Quick Log wizard steps (one decision at a time)
QL_STEPS = [
    ("situation", "Down / distance"),
    ("formation", "Formation"),
    ("variant", "Variant"),
    ("motion", "Motion"),
    ("play", "Play"),
    ("result", "Result"),
    ("defense", "Defense"),
]


def _ql_step_index(name: str) -> int:
    for i, (key, _) in enumerate(QL_STEPS):
        if key == name:
            return i
    return 0


def _all_favorite_plays(favs: dict) -> list[tuple[str, str]]:
    """[(play_name, play_type), ...] longest names first for phrase parsing."""
    out: list[tuple[str, str]] = []
    for ptype in PLAY_TYPES:
        for name in favs.get("plays", {}).get(ptype) or []:
            s = _ql_norm(name)
            if s:
                out.append((s, ptype))
    out.sort(key=lambda x: len(x[0]), reverse=True)
    return out


def _season_phrase_plays(offense_df: pd.DataFrame | None) -> list[tuple[str, str]]:
    """All season play calls (incl. rare n=1) for phrase matching."""
    out: list[tuple[str, str]] = []
    if offense_df is None or offense_df.empty or "play_call" not in offense_df.columns:
        return out
    src = offense_df
    # Include tagged prior-year play calls; skip blank/unknown
    if "play_tagged" in src.columns:
        src = src[src["play_tagged"].fillna(0).astype(int) == 1]
    tmp = src[["play_call"]].copy()
    tmp["play_type"] = src["play_type"] if "play_type" in src.columns else "inbox"
    tmp["_play"] = tmp["play_call"].dropna().astype(str).str.strip()
    tmp = tmp[tmp["_play"].ne("") & ~tmp["_play"].str.contains("unknown", case=False, na=False)]
    tmp["_ptype"] = tmp["play_type"].map(_map_db_play_type)
    seen: set[str] = set()
    for play, grp in tmp.groupby("_play"):
        name = _ql_norm(_tag_display(str(play)))
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        mode = grp["_ptype"].value_counts()
        ptype = str(mode.index[0]) if not mode.empty else "inbox"
        if ptype not in PLAY_TYPES:
            ptype = "pass"
        out.append((name, ptype))
    out.sort(key=lambda x: len(x[0]), reverse=True)
    return out


@st.cache_data(show_spinner=False)
def _cached_season_phrase_plays() -> list[tuple[str, str]]:
    """Full offense play-call dictionary from the season DB (every niche tag)."""
    try:
        return _season_phrase_plays(load_plays("Offense"))
    except Exception:
        return []


def _live_log_phrase_plays() -> list[tuple[str, str]]:
    """Plays already logged tonight (new installs not yet in season DB)."""
    out: list[tuple[str, str]] = []
    if not LIVE_LOG_FILE.exists():
        return out
    try:
        df = pd.read_csv(LIVE_LOG_FILE)
    except Exception:
        return out
    if df is None or df.empty or "play_call" not in df.columns:
        return out
    seen: set[str] = set()
    for _, row in df.iterrows():
        name = _ql_norm(_tag_display(str(row.get("play_call") or "")))
        if not name or name.lower() in seen or "unknown" in name.lower():
            continue
        seen.add(name.lower())
        ptype = str(row.get("play_type") or "").strip().lower()
        if ptype not in PLAY_TYPES:
            ptype = "pass"
        out.append((name, ptype))
    return out


def _phrase_play_catalog(
    favs: dict,
    extra_plays: list[tuple[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """
    Favorites first, then ALL season play calls, tonight's log, inbox, learned tags.

    Niche / one-off Hudl tags are matched even when not in booth favorites.
    """
    plays: list[tuple[str, str]] = []
    plays.extend(_all_favorite_plays(favs))
    # Full season dictionary — always (caller extras override/extend if provided)
    season = list(extra_plays) if extra_plays is not None else list(_cached_season_phrase_plays())
    plays.extend(season)
    plays.extend(_live_log_phrase_plays())
    for name in favs.get("inbox_plays") or []:
        s = _ql_norm(name)
        if s:
            plays.append((s, "pass"))
    for name in (_load_learned_tags().get("play_call") or []):
        s = _ql_norm(name)
        if s:
            plays.append((s, "pass"))

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, ptype in plays:
        s = _ql_norm(name)
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append((s, ptype if ptype in PLAY_TYPES else "pass"))

    # Pass concepts from favorites + season runs/passes (Bear, Seattle, …)
    for concept in _derive_pass_concepts(favs, all_plays=deduped):
        if concept.lower() not in seen:
            deduped.append((concept, "pass"))
            seen.add(concept.lower())
    deduped.sort(key=lambda x: len(x[0]), reverse=True)
    return deduped


# Pass tags that glue onto a run for RPOs (RB/OL run concept + WR pass concept).
DEFAULT_PASS_CONCEPTS = [
    "Bear",
    "Seattle",
    "Stab",
    "Bronco",
    "Backside",
    "Return",
]


def _derive_pass_concepts(
    favs: dict,
    all_plays: list[tuple[str, str]] | None = None,
) -> list[str]:
    """
    Pass-only tags used in RPOs.

    From run+pass names: if 'Army Bear' is pass and 'Army' is run → 'Bear'.
    Uses favorites and (when provided) the full season play catalog.
    """
    runs = [
        _ql_norm(x)
        for x in (favs.get("plays", {}) or {}).get("run") or []
        if _ql_norm(x)
    ]
    passes = [
        _ql_norm(x)
        for x in (favs.get("plays", {}) or {}).get("pass") or []
        if _ql_norm(x)
    ]
    for name, ptype in all_plays or []:
        s = _ql_norm(name)
        if not s:
            continue
        if ptype == "run":
            runs.append(s)
        elif ptype == "pass":
            passes.append(s)
    # unique preserve longest-first later
    run_low: dict[str, str] = {}
    for r in runs:
        run_low.setdefault(r.lower(), r)
    runs_sorted = sorted(run_low.values(), key=len, reverse=True)
    concepts: dict[str, str] = {}
    for pname in passes:
        p = _ql_norm(pname)
        if not p:
            continue
        plow = p.lower()
        for r in runs_sorted:
            if plow.startswith(r.lower() + " "):
                rest = p[len(r) :].strip()
                if rest and rest.lower() not in run_low:
                    concepts[rest.lower()] = rest
                break
    for extra in DEFAULT_PASS_CONCEPTS:
        if extra.lower() not in run_low:
            concepts.setdefault(extra.lower(), extra)
    return sorted(concepts.values(), key=len, reverse=True)


def _split_play_tags(
    play_call: str, play_type: str, favs: dict
) -> dict[str, str]:
    """
    Split a call into run_tag + pass_tag.

    RPOs are tracked as separate tags (Army + Bear), not one compound play
    ('Army Bear'). Either tag may be blank. play_call is a display join only.
    """
    name = _ql_norm(play_call)
    ptype = str(play_type or "").strip().lower()
    empty = {"run_tag": "", "pass_tag": "", "play_type": ptype or "", "play_call": name}
    if not name:
        return empty

    runs = sorted(
        [
            _ql_norm(x)
            for x in (favs.get("plays", {}) or {}).get("run") or []
            if _ql_norm(x)
        ],
        key=len,
        reverse=True,
    )
    season = _cached_season_phrase_plays()
    concept_low = {c.lower() for c in _derive_pass_concepts(favs, all_plays=season)}
    pass_low = {
        _ql_norm(x).lower()
        for x in (favs.get("plays", {}) or {}).get("pass") or []
        if _ql_norm(x)
    }
    for sname, stype in season:
        s = _ql_norm(sname)
        if not s:
            continue
        if stype == "pass":
            pass_low.add(s.lower())
        elif stype == "run":
            if s.lower() not in {r.lower() for r in runs}:
                runs.append(s)
    runs = sorted(runs, key=len, reverse=True)

    # Compound: known run prefix + remainder as pass concept.
    # Prefer splits where the pass half is a known concept; otherwise allow a
    # single-token remainder (new combo like Army + Bear even if Bear is new).
    best = None
    for r in runs:
        if not name.lower().startswith(r.lower() + " "):
            continue
        rest = name[len(r) :].strip()
        if not rest:
            continue
        rlow = rest.lower()
        known_pass = rlow in concept_low or rlow in pass_low
        new_combo = " " not in rest  # single token after the run
        if known_pass:
            best = (r, rest, True)
            break  # longest run with known pass concept wins
        if new_combo and best is None and ptype in {"", "pass", "rpo"}:
            best = (r, rest, False)
    if best:
        r, rest, _ = best
        return {
            "run_tag": r,
            "pass_tag": rest,
            "play_type": "rpo",
            "play_call": f"{r} {rest}",
        }

    # Exact single-tag matches
    if any(name.lower() == r.lower() for r in runs):
        canon = next(r for r in runs if name.lower() == r.lower())
        return {
            "run_tag": canon,
            "pass_tag": "",
            "play_type": "run" if ptype in {"", "run", "rpo"} else ptype,
            "play_call": canon,
        }
    if name.lower() in pass_low or name.lower() in concept_low:
        return {
            "run_tag": "",
            "pass_tag": name,
            "play_type": "pass" if ptype in {"", "pass", "rpo"} else ptype,
            "play_call": name,
        }

    if ptype == "run":
        return {"run_tag": name, "pass_tag": "", "play_type": "run", "play_call": name}
    if ptype == "pass":
        return {"run_tag": "", "pass_tag": name, "play_type": "pass", "play_call": name}
    if ptype == "rpo":
        return {"run_tag": "", "pass_tag": "", "play_type": "rpo", "play_call": name}
    return empty


def _compose_play_parts(
    parts: list[tuple[str, str]], favs: dict
) -> dict[str, str]:
    """Merge matched play tokens into run_tag / pass_tag (RPO = both)."""
    if not parts:
        return {}
    if len(parts) == 1:
        return _split_play_tags(parts[0][0], parts[0][1], favs)

    run_names = [_ql_norm(n) for n, t in parts if t == "run" and _ql_norm(n)]
    pass_names = [
        _ql_norm(n) for n, t in parts if t in {"pass", "rpo"} and _ql_norm(n)
    ]
    # Prefer longest run / first pass concept when multiple tokens matched
    run_tag = sorted(run_names, key=len, reverse=True)[0] if run_names else ""
    pass_tag = pass_names[0] if pass_names else ""

    # A lone "rpo" catalog hit that is itself a compound — split it
    if not run_tag and not pass_tag and parts:
        return _split_play_tags(parts[0][0], parts[0][1], favs)
    if len(parts) >= 1 and not pass_tag:
        for n, t in parts:
            if t == "rpo":
                split = _split_play_tags(n, "rpo", favs)
                if split.get("run_tag") or split.get("pass_tag"):
                    run_tag = run_tag or split.get("run_tag") or ""
                    pass_tag = split.get("pass_tag") or ""
                    break

    if run_tag and pass_tag:
        ptype = "rpo"
    elif run_tag:
        ptype = "run"
    elif pass_tag:
        ptype = "pass"
    else:
        ptype = parts[0][1] if parts else ""
        return _split_play_tags(" ".join(n for n, _ in parts), ptype, favs)

    display = " ".join(x for x in (run_tag, pass_tag) if x)
    return {
        "run_tag": run_tag,
        "pass_tag": pass_tag,
        "play_type": ptype,
        "play_call": display,
    }


def _display_play_call(run_tag: str = "", pass_tag: str = "", play_call: str = "") -> str:
    bits = [ _ql_norm(run_tag), _ql_norm(pass_tag) ]
    joined = " ".join(b for b in bits if b)
    return joined or _ql_norm(play_call)


def learn_favorite_play(play_call: str, play_type: str) -> None:
    """Remember a play under run/pass/rpo/special favorites."""
    name = _ql_norm(play_call)
    ptype = str(play_type or "").strip().lower()
    if not name or ptype not in PLAY_TYPES:
        return
    # Never park split RPO tags as a single compound under rpo
    if ptype == "rpo" and " " in name:
        return
    favs = load_live_favorites()
    plays = dict(favs.get("plays") or {})
    for t in PLAY_TYPES:
        plays.setdefault(t, [])
    # Prefer the typed bucket; drop duplicates from other buckets
    for t in PLAY_TYPES:
        if t == ptype:
            continue
        plays[t] = [
            p
            for p in (plays.get(t) or [])
            if _ql_norm(p).lower() != name.lower()
        ]
    plays[ptype] = _add_favorite_name(list(plays.get(ptype) or []), name)
    favs["plays"] = plays
    # Drop from inbox if present
    favs["inbox_plays"] = [
        p
        for p in (favs.get("inbox_plays") or [])
        if _ql_norm(p).lower() != name.lower()
    ]
    save_live_favorites(favs)


def learn_rpo_tags(run_tag: str = "", pass_tag: str = "") -> None:
    """Learn RPO pieces into run / pass favorites (not a compound rpo name)."""
    if _ql_norm(run_tag):
        learn_favorite_play(run_tag, "run")
    if _ql_norm(pass_tag):
        learn_favorite_play(pass_tag, "pass")


def _all_favorite_variants(favs: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in favs.get("variants") or []:
        s = _ql_norm(v)
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    for vals in (favs.get("variants_by_formation") or {}).values():
        for v in vals or []:
            s = _ql_norm(v)
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
    out.sort(key=len, reverse=True)
    return out


_PHRASE_STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "and",
    "to",
    "for",
    "on",
    "at",
    "in",
    "by",
    "with",
    "from",
    "yards",
    "yard",
    "yds",
    "yd",
    "gain",
    "loss",
    "complete",
    "completed",
    "catch",
    "caught",
    "pass",
    "passed",
    "thrown",
    "throw",
    "carry",
    "carries",
    "rush",
    "rushes",
    "rushed",
    "run",
    "runs",
    "keeper",
    "keep",
    "scramble",
    "handoff",
    "reception",
}


def _leftover_play_candidate(unmatched: list[str]) -> str:
    """Title-case leftover tokens into a first-time play name guess."""
    toks = [
        t
        for t in (unmatched or [])
        if t
        and t.lower() not in _PHRASE_STOPWORDS
        and not t.isdigit()
        and len(t) > 1
    ]
    if not toks:
        return ""
    return " ".join(t[:1].upper() + t[1:] if t.islower() else t for t in toks)


# 1–2 spoken name tokens (Luke / Luke Harris / O'Brien).
# Second token must not be booth filler (for / incomplete / yards…).
_BALL_NAME = (
    r"([A-Za-z][A-Za-z\-']+"
    r"(?:\s+(?!for\b|to\b|of\b|and\b|a\b|the\b|gain\b|loss\b|yards?\b|yds?\b|"
    r"incomplete\b|complet(?:e[sd]?|ion)\b|catch(?:es|ed)?\b|caught\b|"
    r"carr(?:y|ies)\b|rush(?:es|ed)?\b|run(?:s)?\b|td\b|touchdown\b|"
    r"penalty\b|sack\b|punt\b|no\b|pass(?:ed|es)?\b|throw(?:s|n)?\b)"
    r"[A-Za-z][A-Za-z\-']+)?)"
)


def _resolve_spoken_ball_name(raw_name: str, roster: list[dict]) -> str:
    """Map spoken name to roster (or title-case fallback)."""
    import re

    spoken = re.sub(r"\s+", " ", str(raw_name or "").strip())
    if not spoken:
        return ""
    hit = match_roster_name(spoken, roster)
    if hit:
        return hit
    parts = spoken.split()
    if len(parts) >= 2:
        hit = match_roster_name(parts[-1], roster) or match_roster_name(parts[0], roster)
        if hit:
            return hit
    if spoken.lower() in _PHRASE_STOPWORDS:
        return ""
    return spoken[:1].upper() + spoken[1:]


def parse_passer_and_touch(
    work: str, roster: list[dict] | None = None
) -> tuple[str, str, str, str]:
    """
    Pull passer + ball carrier/target from a phrase remnant.

    Returns (pass_player, ball_player, touch_role, cleaned_work).

    Recognizes:
      Garrett to Luke for 10 · from Garrett · Garrett throws
      (+ all parse_ball_touch patterns for the ball guy)
    """
    import re

    roster = roster if roster is not None else load_roster()
    text = str(work or "")
    if not text.strip():
        return "", "", "", text

    # PASSER to TARGET — both must be real roster names (not play tags like Bear)
    m = re.search(rf"\b{_BALL_NAME}\s+to\s+{_BALL_NAME}\b", text, flags=re.I)
    if m:
        passer = match_roster_name(m.group(1), roster)
        target = match_roster_name(m.group(2), roster) or _resolve_spoken_ball_name(
            m.group(2), roster
        )
        if (
            passer
            and target
            and passer.lower() != target.lower()
            and m.group(1).strip().lower() not in _PHRASE_STOPWORDS
        ):
            cleaned = (text[: m.start()] + " " + text[m.end() :]).strip()
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return passer, target, "target", cleaned

    pass_player = ""
    # pass/throw/complete from PASSER
    m = re.search(
        rf"\b(?:(?:pass(?:ed)?|throw(?:n)?|complete(?:d|ion)?|catch(?:es|ed)?)\s+)?from\s+{_BALL_NAME}\b",
        text,
        flags=re.I,
    )
    if m:
        hit = _resolve_spoken_ball_name(m.group(1), roster)
        if hit:
            pass_player = hit
            text = (text[: m.start()] + " " + text[m.end() :]).strip()
            text = re.sub(r"\s+", " ", text).strip()

    # PASSER throws / passes / fires / finds
    if not pass_player:
        m = re.search(
            rf"\b{_BALL_NAME}\s+(?:throws?|passes|fired?|finds?|hits?)\b",
            text,
            flags=re.I,
        )
        if m:
            hit = _resolve_spoken_ball_name(m.group(1), roster)
            if hit and m.group(1).strip().lower() not in _PHRASE_STOPWORDS:
                pass_player = hit
                text = (text[: m.start()] + " " + text[m.end() :]).strip()
                text = re.sub(r"\s+", " ", text).strip()

    bp, role, cleaned = parse_ball_touch(text, roster)
    return pass_player, bp, role, cleaned


def parse_ball_touch(
    work: str, roster: list[dict] | None = None
) -> tuple[str, str, str]:
    """
    Pull ball carrier / target (+ role) from a phrase remnant.

    Returns (player, touch_role, cleaned_work).
    touch_role is 'carry' | 'target' | ''.

    Recognizes booth lines like:
      luke carry for 10 · carry for Walker · Walker rushes for 8
      complete to luke for 10 · completion to Cheatham · luke catch for 12
      pass to luke incomplete · handoff to luke · ball to Cheatham
    """
    import re

    roster = roster if roster is not None else load_roster()
    text = str(work or "")
    if not text.strip():
        return "", "", text

    # (role, pattern) — more specific first; NAME group is always group 1
    patterns: list[tuple[str, str]] = [
        # Pass / receiving — cue before name
        (
            "target",
            rf"\b(?:caught\s+by|catch(?:es|ed)?\s+by|completion\s+to|complete(?:d)?\s+to|"
            rf"thrown\s+to|throw\s+to|passed\s+to|pass(?:ed)?\s+to|"
            rf"target(?:ed)?\s+(?:to\s+)?|ball\s+to)\s+{_BALL_NAME}",
        ),
        # Pass — name-first: "luke catch for 12", "Cheatham reception"
        (
            "target",
            rf"\b{_BALL_NAME}\s+(?:catch(?:es|ed)?|reception|receives?|hauled\s+in)\b",
        ),
        # Run — cue before name: "carry for Walker", "handoff to luke"
        # (before name-first so "Army Bear carry for Walker" doesn't eat Bear)
        (
            "carry",
            rf"\b(?:carr(?:y|ies)|rush(?:es|ed)?|run|keeper|keep|scramble|"
            rf"hand(?:\s|-)?off|handed\s+off)\s+(?:by\s+|to\s+|for\s+)?{_BALL_NAME}",
        ),
        # Run — name-first: "luke carry for 10", "Walker rushes for 8"
        (
            "carry",
            rf"\b{_BALL_NAME}\s+(?:carr(?:y|ies)|rush(?:es|ed)?|run(?:s)?|"
            rf"keeper|keep|scramble(?:s|d)?)\b",
        ),
        # Bare "to NAME" (role from lane / play type later)
        ("", rf"\bto\s+{_BALL_NAME}"),
        # "for Cheatham" but not "for 5" / "for yards"
        ("", rf"\bfor\s+{_BALL_NAME}(?!\s*(?:\d|yards?|yds?)\b)"),
    ]
    for role, pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if not m:
            continue
        player = _resolve_spoken_ball_name(m.group(1), roster)
        if not player:
            continue
        cleaned = (text[: m.start()] + " " + text[m.end() :]).strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return player, role, cleaned
    return "", "", text


def _strip_ball_player_from_work(
    work: str, roster: list[dict] | None = None
) -> tuple[str, str]:
    """Back-compat: (player, cleaned_work). Prefer parse_ball_touch."""
    player, _role, cleaned = parse_ball_touch(work, roster)
    return player, cleaned


def infer_touch_role(
    play_type: str,
    result: str,
    ball_player: str,
    phrase: str = "",
    touch_role: str = "",
) -> str:
    """carry | target | touch | blank."""
    if not str(ball_player or "").strip():
        return ""
    explicit = str(touch_role or "").strip().lower()
    if explicit in {"carry", "target"}:
        return explicit
    # Phrase cues beat sticky play_type (RPO / last snap)
    lane = detect_outcome_lane(phrase=phrase, result=result, touch_role="")
    if lane == "pass":
        return "target"
    if lane == "run":
        return "carry"
    ptype = str(play_type or "").strip().lower()
    res = str(result or "").strip()
    if ptype == "pass" or res == "Incomplete":
        return "target"
    if ptype == "run":
        return "carry"
    return "touch"


def detect_outcome_lane(phrase: str = "", result: str = "", touch_role: str = "") -> str:
    """
    'pass' | 'run' | '' from spoken outcome / result / touch role.

    Used so dual-tag RPOs (Army + Bear) log as pass or run by how the snap ended,
    not as play_type=rpo.
    """
    import re

    role = str(touch_role or "").strip().lower()
    if role == "target":
        return "pass"
    if role == "carry":
        return "run"

    res = str(result or "").strip()
    if res == "Incomplete":
        return "pass"

    text = str(phrase or "")
    if text:
        if re.search(
            r"\b(?:complet(?:e[sd]?|ion)|catch(?:es|ed)?|caught|incomplete|thrown|throw|"
            r"pass(?:ed)?\s+to|target(?:ed)?|reception|receiver|to\s+wr|for\s+wr)\b",
            text,
            flags=re.I,
        ):
            return "pass"
        if re.search(
            r"\b(?:carr(?:y|ies)|rush(?:es|ed|ing)?|keeper|keep|scramble|"
            r"hand\s*-?off|handed\s+off|for\s+rb|to\s+rb|running\s+back)\b",
            text,
            flags=re.I,
        ):
            return "run"

    return ""


def resolve_logged_play_type(
    *,
    run_tag: str = "",
    pass_tag: str = "",
    play_type: str = "",
    result: str = "",
    touch_role: str = "",
    phrase: str = "",
    outcome_lane: str = "",
) -> str:
    """
    Final play_type for the live log: run | pass | special (not rpo).

    Dual tags (RPO concepts) resolve to run or pass from the snap outcome.
    """
    run_tag = _ql_norm(run_tag)
    pass_tag = _ql_norm(pass_tag)
    ptype = str(play_type or "").strip().lower()
    if ptype == "special":
        return "special"

    lane = str(outcome_lane or "").strip().lower()
    if lane not in {"run", "pass"}:
        lane = detect_outcome_lane(phrase=phrase, result=result, touch_role=touch_role)

    if run_tag and pass_tag:
        if lane in {"run", "pass"}:
            return lane
        res = str(result or "").strip()
        if res == "Incomplete":
            return "pass"
        if res in {"Sack / TFL", "No gain"}:
            return "run"
        # Ambiguous Gain/TD — honor explicit run/pass, else default run (keep)
        if ptype in {"run", "pass"}:
            return ptype
        return "run"

    if run_tag and not pass_tag:
        return "run"
    if pass_tag and not run_tag:
        return "pass"
    if ptype in {"run", "pass"}:
        return ptype
    if ptype == "rpo":
        return lane if lane in {"run", "pass"} else "run"
    return ptype if ptype in PLAY_TYPES else ""



def learn_inbox_play(play_call: str) -> None:
    """Park an unmapped verbal play in favorites inbox until typed."""
    name = _ql_norm(play_call)
    if not name:
        return
    favs = load_live_favorites()
    plays = favs.get("plays") or {}
    known = {
        _ql_norm(p).lower()
        for bucket in (plays.values() if isinstance(plays, dict) else [])
        for p in (bucket or [])
    }
    if name.lower() in known:
        return
    favs["inbox_plays"] = _add_favorite_name(list(favs.get("inbox_plays") or []), name)
    save_live_favorites(favs)


def parse_call_phrase(phrase: str, favs: dict) -> dict[str, str]:
    """Parse formation / variant / motion / play from a call phrase."""
    return {
        k: v
        for k, v in parse_live_phrase(phrase, favs).items()
        if k in {"formation", "variant", "motion", "play_call", "play_type"}
    }


def parse_live_phrase(
    phrase: str,
    favs: dict,
    extra_plays: list[tuple[str, str]] | None = None,
    *,
    start_ball_yard: int | float | None = None,
) -> dict:
    """
    Parse a booth line into situation + call + result (+ optional defense).

    Examples:
      '1st and 10, own 20, Slot Dip Bash Sooner Molly, gain of 2'
      'Slot Trig Sooner Ireland gain of 5'   # uses current down/distance
      'Fox RT Bash Sooner Mary incomplete'
      'Illinois Bear'  → run Illinois + pass Bear (type from outcome)
      'Army Bear completion to Cheatham' → tags Army/Bear, play_type=pass
      'Army Bear carry for Walker' → tags Army/Bear, play_type=run
      'luke carry for 10' → ball Luke, carry, Gain 10
      'complete to luke for 10' → ball Luke, target, Gain 10
      'completed to the opp 45' → Gain of (end − current LOS)
      'Army'           → run tag only
      'Bear'           → pass tag only (e.g. new combo with any run)
    """
    import re

    raw = _ql_norm(phrase)
    result: dict = {
        "formation": "",
        "variant": "",
        "motion": "",
        "play_call": "",
        "play_type": "",
        "run_tag": "",
        "pass_tag": "",
        "down": None,
        "distance_yards": None,
        "field_zone": None,
        "ball_yard": None,
        "result": None,
        "yards_gained": None,
        "def_front": "",
        "coverage": "",
        "blitz": None,
        "auto_first": False,
        "has_situation": False,
        "has_outcome": False,
        "ball_player": "",
        "touch_role": "",
        "pass_player": "",
        "outcome_lane": "",
        "unmatched": [],
        "new_play_guess": "",
        "play_is_new": False,
        "end_ball_yard": None,
    }
    if not raw:
        return result

    # Normalize speech/punctuation early so "penalty, loss of 5" still matches
    work = re.sub(r"[,;:]+", " ", raw)
    work = re.sub(r"\s+", " ", work).strip()

    # Common speech-to-text formation mishears / aliases
    # IMPORTANT: "Tricks" = Trix (do NOT map trick→Slot Trig)
    # IMPORTANT: "Wright" = Right (Fox/Pack/Fever RT) — never Slot Trig
    for pat, repl in (
        (r"\bwright\b", "right"),
        (r"\bwrite\b", "right"),  # occasional STT near-miss for "right"
        (r"\bslot\s+rig\b", "slot trig"),  # "rig" only — not "wright"/"right"
        (r"\bslot\s+tip\b", "slot dip"),
        (r"\bslot\s+tricks?\b", "trix"),  # STT sometimes says "slot tricks" for Trix
        (r"\btricks\b", "trix"),
        (r"\btrick\b", "trix"),
        (r"\bbare\b", "bear"),  # STT: "Bear" / "Bear Front"
        (r"\b(fox|pack|fever)\s+right\b", r"\1 rt"),
        (r"\b(fox|pack|fever)\s+left\b", r"\1 lt"),
        (r"\b(fox|pack|fever)\s+rt\b", r"\1 rt"),
        (r"\b(fox|pack|fever)\s+lt\b", r"\1 lt"),
    ):
        work = re.sub(pat, repl, work, flags=re.I)

    # Spoken numbers → digits ("loss of nine" → "loss of 9")
    word_nums = {
        "zero": "0",
        "oh": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
        "eleven": "11",
        "twelve": "12",
        "thirteen": "13",
        "fourteen": "14",
        "fifteen": "15",
        "sixteen": "16",
        "seventeen": "17",
        "eighteen": "18",
        "nineteen": "19",
        "twenty": "20",
    }
    work = re.sub(
        r"\b(" + "|".join(word_nums.keys()) + r")\b",
        lambda m: word_nums[m.group(1).lower()],
        work,
        flags=re.I,
    )

    # Normalize spoken ordinals: "first and/in 10" → parseable down & distance
    word_downs = {
        "first": "1",
        "second": "2",
        "third": "3",
        "fourth": "4",
        "1st": "1",
        "2nd": "2",
        "3rd": "3",
        "4th": "4",
    }
    def _down_repl(m: re.Match) -> str:
        d = word_downs.get(m.group(1).lower(), m.group(1))
        return f"{d} and {m.group(2)}"

    work = re.sub(
        r"\b(first|second|third|fourth|1st|2nd|3rd|4th|[1-4])\s*(?:and|&|in|n)\s*(\d{1,2})\b",
        _down_repl,
        work,
        flags=re.I,
    )

    # Down & distance: 1st and 10 / 2nd & 8 / first in 10 (after normalize)
    m = re.search(
        r"\b([1-4])(?:st|nd|rd|th)?\s*(?:and|&)\s*(\d{1,2})\b",
        work,
        flags=re.I,
    )
    if m:
        result["down"] = int(m.group(1))
        result["distance_yards"] = int(m.group(2))
        result["has_situation"] = True
        work = work[: m.start()] + " " + work[m.end() :]

    def _side_token(raw_side: str) -> str:
        s = str(raw_side or "").lower()
        if s.startswith("own") or s == "our":
            return "own"
        return "opp"

    # End spot BEFORE start spot so "to the opp 45" is not treated as LOS.
    # "completed to the opp 45" / "carry to own 40" / "to the opp 45"
    end_ball: int | None = None
    m_end = re.search(
        r"\bto\s+(?:the\s+)?(own|our|opp(?:onent)?|their)\s+(\d{1,2})\b",
        work,
        flags=re.I,
    )
    if m_end:
        end_ball = side_yard_to_ball_yard(_side_token(m_end.group(1)), int(m_end.group(2)))
        result["end_ball_yard"] = end_ball
        result["has_outcome"] = True
        if result.get("result") is None:
            result["result"] = "Gain"
        work = work[: m_end.start()] + " " + work[m_end.end() :]

    # Field zone / ball spot ("own 10", "opp 35") — pre-snap LOS
    m = re.search(r"\b(own|our|opp(?:onent)?|their)\s*(\d{1,2})\b", work, flags=re.I)
    if m:
        side = _side_token(m.group(1))
        yd = int(m.group(2))
        ball = side_yard_to_ball_yard(side, yd)
        result["ball_yard"] = ball
        result["field_zone"] = ball_yard_to_zone(ball)
        result["has_situation"] = True
        work = work[: m.start()] + " " + work[m.end() :]
    else:
        for label, zone in (
            (r"\bred\s*zone\b", "red_zone"),
            (r"\bmidfield\b", "midfield"),
            (r"\bbacked\s*up\b", "backed_up"),
            (r"\bown\s*territory\b", "own_territory"),
            (r"\bopp(?:onent)?\s*territory\b", "opp_territory"),
        ):
            m = re.search(label, work, flags=re.I)
            if m:
                result["field_zone"] = zone
                result["ball_yard"] = zone_default_ball_yard(zone)
                result["has_situation"] = True
                work = work[: m.start()] + " " + work[m.end() :]
                break

    # Yards from end spot vs LOS (phrase start or current booth ball)
    if end_ball is not None:
        start_fp = result.get("ball_yard")
        if start_fp is None and start_ball_yard is not None:
            try:
                start_fp = int(start_ball_yard)
            except (TypeError, ValueError):
                start_fp = None
        if start_fp is not None:
            result["yards_gained"] = int(end_ball) - int(start_fp)
            result["has_outcome"] = True
            if result.get("result") is None:
                result["result"] = "Gain"

    # Ball carrier / target / passer before outcome so "luke catch for 12" keeps the name
    pp, bp, touch_role, work = parse_passer_and_touch(work, load_roster())
    if bp:
        result["ball_player"] = bp
    if touch_role:
        result["touch_role"] = touch_role
    if pp:
        result["pass_player"] = pp
    work = re.sub(r"\s+", " ", work).strip()

    # Outcome phrases (order matters — specific before generic)
    # Note: "-5" has no word-boundary before the minus, so use (?<!\w)
    # "completion" is complet+ion (not complete+ion) — keep both forms
    complete = r"(?:complete[ds]?|completion|caught|catch(?:es|ed)?)"
    outcome_patterns = [
        (r"\bincomplete\b", "Incomplete", 0),
        (r"\bno\s*gain\b", "No gain", 0),
        (r"\btouchdown\b|\btd\b", "TD", None),
        (
            r"\binterception\b|\bintercepted\b|\bpick\s*six\b|\bturnover\b|"
            r"\bpicked\s*off\b|\bpick\b|\bfumble\b|\bint\b",
            "Turnover",
            0,
        ),
        (r"\bsack\b", "Sack / TFL", -1),
        # Completed catch/pass — keep as Gain even on a loss of yards
        (rf"\b{complete}\s*(?:for\s*)?(?:a\s*)?loss\s*(?:of\s*)?(\d{{1,2}})\b", "Gain", "g1_neg"),
        (rf"\b{complete}\s*(?:for\s*)?(?:a\s*)?gain\s*(?:of\s*)?(\d{{1,2}})\b", "Gain", "g1"),
        (rf"\b{complete}\s*(?:for\s*)?(?:minus\s*|[-−–]\s*)(\d{{1,2}})\b", "Gain", "g1_neg"),
        (rf"\b{complete}\s*(?:for\s*)?(\d{{1,2}})\b", "Gain", "g1"),
        (rf"\b{complete}\b", "Gain", "complete_mark"),
        # penalty +15 / penalty -5 / plus/minus / loss/gain of N
        # Allow commas/words between "penalty" and "gain of 15"
        (r"\bpenalty\b(?:\s|\W)+(?:for\s*)?(?:a\s*)?loss\s*(?:of\s*)?(\d{1,2})\b", "Penalty", "g1_neg"),
        (r"\bpenalty\s*(?:for\s*)?(?:a\s*)?loss\s*(?:of\s*)?(\d{1,2})\b", "Penalty", "g1_neg"),
        (r"\bloss\s*(?:of\s*)?(\d{1,2})\s*(?:yards?|yds?)?\s*penalty\b", "Penalty", "g1_neg"),
        (r"\bpenalty\b(?:\s|\W)+(?:for\s*)?(?:a\s*)?gain\s*(?:of\s*)?(\d{1,2})\b", "Penalty", "g1"),
        (r"\bpenalty\s*(?:for\s*)?(?:a\s*)?gain\s*(?:of\s*)?(\d{1,2})\b", "Penalty", "g1"),
        (r"\bgain\s*(?:of\s*)?(\d{1,2})\s*(?:yards?|yds?)?\s*penalty\b", "Penalty", "g1"),
        (r"\bpenalty\s*(?:of\s*)?\+\s*(\d{1,2})\b", "Penalty", "g1"),
        (r"\bpenalty\s+plus\s+(\d{1,2})\b", "Penalty", "g1"),
        (r"\bpenalty\s*(?:of\s*)?(?:minus\s*)?[-−–]\s*(\d{1,2})\b", "Penalty", "g1_neg"),
        (r"\bpenalty\s+minus\s+(\d{1,2})\b", "Penalty", "g1_neg"),
        # bare "penalty 5" = −5 (offense foul default); "penalty 15" alone still −15
        (r"\bpenalty\s*(?:of\s*)?(\d{1,2})\b", "Penalty", "g1_neg"),
        # Bare "penalty" — yards scraped from remainder ("… penalty, gain of 15")
        (r"\bpenalty\b", "Penalty", "penalty_bare"),
        (r"\bpunt\b", "Punt", 0),
        (r"\bloss\s*(?:of\s*)?(\d{1,2})\b", "Sack / TFL", "g1_neg"),
        (r"\bgain\s*(?:of\s*)?(\d{1,2})\b", "Gain", "g1"),
        (r"\bfor\s*(\d{1,2})\s*yards?\b", "Gain", "g1"),
        # Booth shorthand: "carry for 10" / "to luke for 10"
        (r"\bfor\s+(\d{1,2})\b", "Gain", "g1"),
        (r"(?<!\w)([+-]|[-−–])\s*(\d{1,2})\s*(?:yards?|yds?)?\b", None, "signed2"),
        (r"\bminus\s+(\d{1,2})\b", "Sack / TFL", "g1_neg"),
    ]
    end_spot_yards = result.get("yards_gained") if end_ball is not None else None
    for pat, res_name, ymode in outcome_patterns:
        m = re.search(pat, work, flags=re.I)
        if not m:
            continue
        result["has_outcome"] = True
        if ymode == "g1":
            result["result"] = res_name
            result["yards_gained"] = int(m.group(1))
        elif ymode == "g1_neg":
            result["result"] = res_name
            result["yards_gained"] = -abs(int(m.group(1)))
        elif ymode == "signed2":
            sign, num = m.group(1), m.group(2)
            y = -abs(int(num)) if sign.strip() in {"-", "−", "–"} else abs(int(num))
            result["yards_gained"] = y
            if y > 0:
                result["result"] = "Gain"
            elif y < 0:
                result["result"] = "Sack / TFL"
            else:
                result["result"] = "No gain"
        elif ymode == "complete_mark":
            result["result"] = "Gain"
            result["has_outcome"] = True
        elif ymode == "penalty_bare":
            result["result"] = "Penalty"
            # yards left unset so remainder scrape can pick up "gain of 15"
        else:
            result["result"] = res_name
            if ymode is not None:
                result["yards_gained"] = int(ymode)
            elif res_name == "TD":
                result["yards_gained"] = result.get("yards_gained")
        work = work[: m.start()] + " " + work[m.end() :]
        break

    # Prefer end-spot yards over "gain of N" when both appear
    if end_spot_yards is not None:
        result["yards_gained"] = int(end_spot_yards)
        if result.get("result") in {None, "Gain", "No gain"}:
            if int(end_spot_yards) == 0:
                result["result"] = "No gain"
            else:
                result["result"] = "Gain"
        # Keep Sack / TFL / TD / Turnover if the phrase already said so
        result["has_outcome"] = True

    def _scrape_yards_from_remainder(default_neg: bool = False) -> bool:
        """Pull yards still sitting in `work` after a bare result word."""
        nonlocal work
        # +15 / plus 15 first (important for "penalty +15")
        m_plus = re.search(r"(?<!\w)(?:\+|plus\s+)(\d{1,2})\b", work, flags=re.I)
        if m_plus:
            result["yards_gained"] = abs(int(m_plus.group(1)))
            work = work[: m_plus.start()] + " " + work[m_plus.end() :]
            return True
        m_signed = re.search(r"(?<!\w)(?:minus\s+|[-−–]\s*)(\d{1,2})\b", work, flags=re.I)
        if m_signed:
            result["yards_gained"] = -abs(int(m_signed.group(1)))
            work = work[: m_signed.start()] + " " + work[m_signed.end() :]
            return True
        m_loss = re.search(r"\bloss\s*(?:of\s*)?(\d{1,2})\b", work, flags=re.I)
        if m_loss:
            result["yards_gained"] = -abs(int(m_loss.group(1)))
            work = work[: m_loss.start()] + " " + work[m_loss.end() :]
            return True
        m_gain = re.search(r"\bgain\s*(?:of\s*)?(\d{1,2})\b", work, flags=re.I)
        if m_gain:
            result["yards_gained"] = abs(int(m_gain.group(1)))
            work = work[: m_gain.start()] + " " + work[m_gain.end() :]
            return True
        m_yd = re.search(r"\b(\d{1,2})\s*(?:yards?|yds?)\b", work, flags=re.I)
        if m_yd:
            y = int(m_yd.group(1))
            result["yards_gained"] = -abs(y) if default_neg else abs(y)
            work = work[: m_yd.start()] + " " + work[m_yd.end() :]
            return True
        m_for = re.search(r"\bfor\s+(\d{1,2})\b", work, flags=re.I)
        if m_for:
            y = int(m_for.group(1))
            result["yards_gained"] = -abs(y) if default_neg else abs(y)
            work = work[: m_for.start()] + " " + work[m_for.end() :]
            return True
        return False

    # Bare "complete" / "penalty" with yards still in the phrase
    if result.get("result") == "Gain" and result.get("yards_gained") is None:
        if _scrape_yards_from_remainder(default_neg=False):
            result["has_outcome"] = True
    if result.get("result") == "Penalty" and not result.get("yards_gained"):
        # yards None or 0 — pull "gain of 15" / "+15" left in the phrase
        if _scrape_yards_from_remainder(default_neg=False):
            result["has_outcome"] = True

    # Spoken completion / catch with no other result word → Gain
    if (
        not result.get("result")
        and str(result.get("touch_role") or "") == "target"
    ):
        result["result"] = "Gain"
        result["has_outcome"] = True
    elif (
        not result.get("result")
        and str(result.get("touch_role") or "") == "carry"
        and result.get("yards_gained") is not None
    ):
        result["result"] = "Gain"
        result["has_outcome"] = True

    # "auto first" / "automatic first down" on a penalty
    if re.search(
        r"\bauto(?:matic)?\s*first(?:\s*down)?\b|\bfirst\s*down\s*penalty\b",
        raw,
        flags=re.I,
    ):
        result["auto_first"] = True
        if result.get("result") == "Penalty":
            result["has_outcome"] = True

    # Strip filler words before call parse
    work = re.sub(
        r"\b(ball\s*on|at\s*the|on\s*the|yards?|yds?|to\s*go|and\s*then)\b",
        " ",
        work,
        flags=re.I,
    )

    # Optional defense spoken on the same line (Fill Film tags)
    film = parse_film_phrase(work)
    if film.get("def_front"):
        result["def_front"] = film["def_front"]
        work = re.sub(r"\b(even|odd)(?:\s+fronts?)?\b", " ", work, flags=re.I)
        work = re.sub(r"\b(?:bear|bare)\s+fronts?\b", " ", work, flags=re.I)
    if film.get("blitz") in {"Yes", "No"}:
        result["blitz"] = film["blitz"]
        work = re.sub(
            r"\bno\s+blitz\b|\bwithout\s+blitz\b|\bnon[- ]?blitz\b|\bblitz\b",
            " ",
            work,
            flags=re.I,
        )
    if film.get("coverage"):
        result["coverage"] = film["coverage"]
        work = re.sub(
            r"cover\s*2\s*man|c2\s*man|two\s*man|cover\s*[0-6]|c[0-6]\b|"
            r"quarters|tampa\s*2|three\s*deep|two\s*deep|man\s*free|zero\s*man",
            " ",
            work,
            flags=re.I,
        )
    work = re.sub(r"\s+", " ", work).strip()

    # Second pass: residual passer / ball cues after yards / result words were stripped
    if not result.get("ball_player") or not result.get("pass_player"):
        pp2, bp2, role2, work = parse_passer_and_touch(work, load_roster())
        if bp2 and not result.get("ball_player"):
            result["ball_player"] = bp2
        if role2 and not result.get("touch_role"):
            result["touch_role"] = role2
        if pp2 and not result.get("pass_player"):
            result["pass_player"] = pp2
    # Pass vs run lane from how the snap ended (completion / carry / incomplete…)
    result["outcome_lane"] = detect_outcome_lane(
        phrase=raw,
        result=str(result.get("result") or ""),
        touch_role=str(result.get("touch_role") or ""),
    )
    bp = str(result.get("ball_player") or "")
    if not result.get("touch_role") and bp:
        result["touch_role"] = infer_touch_role(
            str(result.get("play_type") or ""),
            str(result.get("result") or ""),
            bp,
            phrase=raw,
        )
    # Auto-credit on-field QB when this was a pass and no passer spoken
    if not result.get("pass_player"):
        try:
            slots = get_formation_slots()
        except Exception:
            slots = {}
        result["pass_player"] = resolve_pass_player(
            play_type=str(result.get("play_type") or ""),
            touch_role=str(result.get("touch_role") or ""),
            result=str(result.get("result") or ""),
            phrase=raw,
            outcome_lane=str(result.get("outcome_lane") or ""),
            slots=slots,
        )
    work = re.sub(r"\s+", " ", work).strip()

    words = [w for w in work.split() if w]
    if not words:
        return result

    forms = sorted(
        [_ql_norm(x) for x in (favs.get("formations") or []) if _ql_norm(x)],
        key=len,
        reverse=True,
    )
    variants = _all_favorite_variants(favs)
    motions = sorted(
        [_ql_norm(x) for x in (favs.get("motions") or []) if _ql_norm(x)],
        key=len,
        reverse=True,
    )
    # Favorites + ALL season play calls (+ tonight + learned) — niche tags included
    plays = _phrase_play_catalog(favs, extra_plays=extra_plays)

    catalogs: list[tuple[str, list]] = [
        ("formation", forms),
        ("variant", variants),
        ("motion", motions),
        ("play", plays),
    ]

    # Extra one-token aliases from team_config.json (Axle, STT near-misses, etc.)
    from team_config import phrase_token_aliases

    token_aliases = phrase_token_aliases()

    def _norm_candidate(text: str) -> str:
        t = text.lower().strip()
        t = token_aliases.get(t, t)
        # "fox wright" / "pack right" → canonical RT/LT form names
        t = re.sub(r"\b(fox|pack|fever)\s+right\b", r"\1 rt", t, flags=re.I)
        t = re.sub(r"\b(fox|pack|fever)\s+left\b", r"\1 lt", t, flags=re.I)
        t = re.sub(r"\b(fox|pack|fever)\s+wright\b", r"\1 rt", t, flags=re.I)
        return t

    play_parts: list[tuple[str, str]] = []
    unmatched: list[str] = []
    i = 0
    while i < len(words):
        matched = False
        max_len = min(5, len(words) - i)
        for length in range(max_len, 0, -1):
            candidate = " ".join(words[i : i + length])
            clow = _norm_candidate(candidate)
            for kind, lookup in catalogs:
                if kind == "play":
                    hit = next((p for p in lookup if p[0].lower() == clow), None)
                    # Allow multiple play tokens so run + pass concept → RPO
                    if hit:
                        play_parts.append((hit[0], hit[1]))
                        i += length
                        matched = True
                        break
                else:
                    hit = next((p for p in lookup if p.lower() == clow), None)
                    if hit and not result.get(kind):
                        result[kind] = hit
                        i += length
                        matched = True
                        break
            if matched:
                break
        if not matched:
            unmatched.append(words[i])
            i += 1
    composed = _compose_play_parts(play_parts, favs)
    if composed.get("play_call") or composed.get("run_tag") or composed.get("pass_tag"):
        result["run_tag"] = composed.get("run_tag") or ""
        result["pass_tag"] = composed.get("pass_tag") or ""
        result["play_call"] = _display_play_call(
            result["run_tag"], result["pass_tag"], composed.get("play_call") or ""
        )
        result["play_type"] = resolve_logged_play_type(
            run_tag=result["run_tag"],
            pass_tag=result["pass_tag"],
            play_type=composed.get("play_type") or "",
            result=str(result.get("result") or ""),
            phrase=raw,
            outcome_lane=str(result.get("outcome_lane") or ""),
            touch_role=str(result.get("touch_role") or ""),
        )
    result["unmatched"] = unmatched
    result["new_play_guess"] = _leftover_play_candidate(unmatched)
    if (
        not result.get("play_call")
        and not result.get("run_tag")
        and not result.get("pass_tag")
        and result.get("new_play_guess")
    ):
        # First-time / unmapped verbal call — surface for confirm UI
        result["play_call"] = result["new_play_guess"]
        result["play_is_new"] = True
    else:
        result["play_is_new"] = False
    # Re-resolve passer after play_type is known (on-field QB on pass snaps)
    if not result.get("pass_player"):
        try:
            slots = get_formation_slots()
        except Exception:
            slots = {}
        result["pass_player"] = resolve_pass_player(
            play_type=str(result.get("play_type") or ""),
            touch_role=str(result.get("touch_role") or ""),
            result=str(result.get("result") or ""),
            phrase=raw,
            outcome_lane=str(result.get("outcome_lane") or ""),
            slots=slots,
        )
    return result


def _ql_apply_phrase_parse(parsed: dict) -> None:
    if parsed.get("formation"):
        st.session_state.ql_form = parsed["formation"]
        st.session_state.ql_form_typed = ""
        st.session_state.ql_form_dd = ""
    if "variant" in parsed:
        st.session_state.ql_variant = parsed.get("variant") or ""
        st.session_state.ql_variant_typed = ""
    if "motion" in parsed:
        st.session_state.ql_motion = parsed.get("motion") or ""
        st.session_state.ql_motion_typed = ""
    # Named play in this phrase: write both tags so a pass-only call
    # does not keep the previous snap's run tag (e.g. Mary).
    if parsed.get("run_tag") or parsed.get("pass_tag") or parsed.get("play_call"):
        st.session_state.ql_run_tag = parsed.get("run_tag") or ""
        st.session_state.ql_pass_tag = parsed.get("pass_tag") or ""
    if parsed.get("play_call"):
        st.session_state.ql_play = parsed["play_call"]
        st.session_state.ql_play_typed = ""
        st.session_state.ql_play_dd = ""
    if parsed.get("play_type") in PLAY_TYPES:
        st.session_state.ql_play_type = parsed["play_type"]
    if parsed.get("down") is not None:
        st.session_state.lt_down = int(parsed["down"])
    if parsed.get("distance_yards") is not None:
        st.session_state.lt_dist_y = int(parsed["distance_yards"])
    if parsed.get("ball_yard") is not None:
        try:
            st.session_state.lt_ball_yard = int(parsed["ball_yard"])
            st.session_state.lt_zone = ball_yard_to_zone(st.session_state.lt_ball_yard)
        except (TypeError, ValueError):
            pass
    elif parsed.get("field_zone"):
        st.session_state.lt_zone = parsed["field_zone"]
        st.session_state.lt_ball_yard = zone_default_ball_yard(parsed["field_zone"])
    if parsed.get("result"):
        st.session_state.lt_result = parsed["result"]
    if parsed.get("yards_gained") is not None:
        st.session_state.lt_gain = int(parsed["yards_gained"])
    if parsed.get("def_front"):
        st.session_state.ql_front = parsed["def_front"]
        st.session_state.ql_front_custom = ""
    if parsed.get("coverage"):
        st.session_state.ql_cov = parsed["coverage"]
        st.session_state.ql_cov_custom = ""
    if parsed.get("blitz") in {"Yes", "No"}:
        st.session_state.ql_blitz = parsed["blitz"]


def parse_film_phrase(phrase: str) -> dict:
    """
    Parse Sky Coach / booth film line into front / blitz / coverage.

    Examples:
      'Even front, no blitz, cover 3'
      'odd front, blitz, cover 4'
      'cover 2 man'
      'even no blitz c3'
    """
    import re

    out: dict = {
        "def_front": "",
        "coverage": "",
        "blitz": None,
        "raw": str(phrase or "").strip(),
    }
    raw = str(phrase or "").strip()
    if not raw:
        return out

    work = re.sub(r"[,;:]+", " ", raw)
    work = re.sub(r"\s+", " ", work).strip()
    # Common STT mishears for coverages
    for pat, repl in (
        (r"\bcover\s+for\b", "cover 4"),
        (r"\bcover\s+fore\b", "cover 4"),
        (r"\bcover\s+four\b", "cover 4"),
        (r"\bcover\s+tree\b", "cover 3"),
        (r"\bcover\s+three\b", "cover 3"),
        (r"\bcover\s+too\b", "cover 2"),
        (r"\bcover\s+to\b", "cover 2"),
        (r"\bcover\s+two\b", "cover 2"),
        (r"\bcover\s+one\b", "cover 1"),
        (r"\bcover\s+won\b", "cover 1"),
    ):
        work = re.sub(pat, repl, work, flags=re.I)
    low = work.lower()

    # Blitz — check "no blitz" before bare "blitz"
    if re.search(r"\bno\s+blitz\b|\bwithout\s+blitz\b|\bnon[- ]?blitz\b|\bblitz\s*:\s*no\b", low):
        out["blitz"] = "No"
    elif re.search(r"\bblitz\b", low):
        out["blitz"] = "Yes"

    if re.search(r"\b(?:bear|bare)\s+fronts?\b", low):
        out["def_front"] = "Bear"
    elif re.search(r"\beven\b", low):
        out["def_front"] = "Even"
    elif re.search(r"\bodd\b", low):
        out["def_front"] = "Odd"

    # Coverage — longer / more specific names first
    cov_patterns = [
        (r"cover\s*2\s*man|c2\s*man|two\s*man", "Cover 2 Man"),
        (r"cover\s*0|c0\b|zero\s*man", "Cover 0"),
        (r"cover\s*1|c1\b|man\s*free", "Cover 1"),
        (r"cover\s*3|c3\b|three\s*deep", "Cover 3"),
        (r"cover\s*4|c4\b|quarters", "Cover 4"),
        (r"cover\s*6|c6\b", "Cover 6"),
        (r"tampa\s*2|cover\s*2|c2\b|two\s*deep", "Cover 2"),
    ]
    for pat, name in cov_patterns:
        if re.search(pat, low):
            out["coverage"] = name
            break
    return out


def _ff_apply_phrase_to_keys(parsed: dict, idx: int) -> None:
    if parsed.get("def_front"):
        st.session_state[f"ff_front_{idx}"] = parsed["def_front"]
        st.session_state[f"ff_front_{idx}_custom"] = ""
    if parsed.get("coverage"):
        st.session_state[f"ff_cov_{idx}"] = parsed["coverage"]
        st.session_state[f"ff_cov_{idx}_custom"] = ""
    if parsed.get("blitz") in {"Yes", "No"}:
        st.session_state[f"ff_blitz_{idx}"] = parsed["blitz"]


def _ff_phrase_has_tags(parsed: dict) -> bool:
    return bool(
        parsed.get("def_front")
        or parsed.get("coverage")
        or parsed.get("blitz") in {"Yes", "No"}
    )


def _ql_wizard_nav(step: int, *, can_next: bool = True, next_label: str = "Next ▶") -> None:
    back, nxt = st.columns(2)
    if back.button("◀ Back", key=f"ql_back_{step}", use_container_width=True, disabled=step <= 0):
        st.session_state.ql_step = max(0, step - 1)
        st.rerun()
    if nxt.button(
        next_label,
        key=f"ql_next_{step}",
        use_container_width=True,
        type="primary",
        disabled=not can_next,
    ):
        st.session_state.ql_step = min(len(QL_STEPS) - 1, step + 1)
        st.rerun()


def _ql_progress_bar(step: int, summary: str) -> None:
    parts = []
    for i, (_, label) in enumerate(QL_STEPS):
        if i < step:
            parts.append(f"<span style='color:#4ade80'>✓ {label}</span>")
        elif i == step:
            parts.append(f"<span style='color:#fbbf24;font-weight:900'>● {label}</span>")
        else:
            parts.append(f"<span style='opacity:.45'>{label}</span>")
    st.markdown(
        f"<div class='ql-sticky' style='font-size:0.95rem'>{' → '.join(parts)}"
        f"<br/><span style='opacity:.9'>{summary}</span></div>",
        unsafe_allow_html=True,
    )


def _render_favorites_editor(
    live_logs: pd.DataFrame | None,
    opponent: str,
    *,
    form_opts: list[str] | None = None,
    play_opts: list[str] | None = None,
    motion_opts: list[str] | None = None,
    offense_df: pd.DataFrame | None = None,
) -> None:
    """Add / remove / organize booth favorites (formations, variants, motions, typed plays)."""
    favs = load_live_favorites()
    st.markdown("##### Edit favorites")
    st.caption(
        "These are your booth buttons. Formation = base (Slot Dip / East / Fox RT). "
        "Variant = alignment tweak (Bash). Plays are split into Run / Pass / RPO / Special."
    )
    with st.expander("Formation book (notes / breakdown)", expanded=False):
        st.caption(
            "East/West = trips (compass: East=right, West=left). "
            "Dip = H to 1-WR side · Trig = H to 2-WR side · Fox = H to 3-WR side · "
            "Fever = Fox with attached TE · Pack = Bunch · Cowboy = Empty Bunch · "
            "Dot = Doubles · Trix = TE on boundary + trips to field · "
            "Texas = 12 · Nasty = 6 OL + TE."
        )
        try:
            from formation_logic import formation_glossary

            gloss = formation_glossary()
            if gloss:
                import pandas as pd

                st.dataframe(
                    pd.DataFrame(gloss)[["label", "note", "personnel"]].rename(
                        columns={"label": "Call", "note": "Breakdown", "personnel": "Personnel"}
                    ),
                    hide_index=True,
                    use_container_width=True,
                    height=min(38 + 32 * len(gloss), 360),
                )
        except Exception:
            pass

    # --- Auto-import from our offense ---
    st.markdown("**Import from our offense**")
    st.caption(
        "Pulls formations (splits Bash/Stack into variants), motions from Hudl, "
        "and plays by Run/Pass. Anything unclear lands in the inbox for you to sort."
    )
    ic1, ic2, ic3 = st.columns(3)
    if ic1.button("Merge season tags → favorites", type="primary", key="fav_import_merge", use_container_width=True):
        suggested = suggest_offense_favorites(offense_df if offense_df is not None else load_plays("Offense"))
        merged = merge_offense_favorites_into(favs, suggested, replace=False)
        save_live_favorites(merged)
        st.success(
            f"Merged: {len(suggested['formations'])} forms · "
            f"{len(suggested['motions'])} motions · "
            f"{sum(len(v) for v in suggested['plays'].values())} typed plays · "
            f"{len(suggested.get('inbox_plays') or [])} inbox"
        )
        st.rerun()
    if ic2.button("Replace favorites from season", key="fav_import_replace", use_container_width=True):
        suggested = suggest_offense_favorites(offense_df if offense_df is not None else load_plays("Offense"))
        save_live_favorites(suggested)
        st.warning("Favorites replaced from season tags.")
        st.rerun()
    if ic3.button("Preview counts", key="fav_import_preview", use_container_width=True):
        suggested = suggest_offense_favorites(offense_df if offense_df is not None else load_plays("Offense"))
        st.info(
            f"Would import ~{len(suggested['formations'])} formations, "
            f"{len(suggested['variants'])} variants, {len(suggested['motions'])} motions, "
            f"run={len(suggested['plays']['run'])}, pass={len(suggested['plays']['pass'])}, "
            f"inbox={len(suggested.get('inbox_plays') or [])}"
        )

    inbox = list(favs.get("inbox_plays") or [])
    if inbox:
        st.markdown("**Inbox — sort plays**")
        st.caption("Imported plays that still need a type.")
        pick_inbox = st.multiselect("Inbox plays", inbox, key="fav_inbox_pick")
        to_type = st.radio(
            "Move inbox to",
            PLAY_TYPES,
            format_func=lambda t: PLAY_TYPE_LABELS[t],
            horizontal=True,
            key="fav_inbox_type",
        )
        if st.button("Move selected out of inbox", key="fav_inbox_move") and pick_inbox:
            bucket = list(favs["plays"].get(to_type) or [])
            for name in pick_inbox:
                bucket = _add_favorite_name(bucket, name)
                inbox = _remove_favorite_name(inbox, name)
            favs["plays"][to_type] = bucket
            favs["inbox_plays"] = inbox
            save_live_favorites(favs)
            st.rerun()

    # --- Formations ---
    st.markdown("**Formations**")
    f_add, f_btn = st.columns([3, 1])
    new_form = f_add.text_input("Add formation", key="fav_add_form", placeholder="e.g. Slot Dip")
    if f_btn.button("Add", key="fav_add_form_btn", use_container_width=True) and new_form.strip():
        favs["formations"] = _add_favorite_name(favs["formations"], new_form)
        save_live_favorites(favs)
        st.rerun()
    if favs["formations"]:
        rm_form = st.multiselect(
            "Remove formations",
            favs["formations"],
            key="fav_rm_forms",
        )
        if st.button("Remove selected formations", key="fav_rm_forms_btn") and rm_form:
            for name in rm_form:
                favs["formations"] = _remove_favorite_name(favs["formations"], name)
                favs["variants_by_formation"].pop(name, None)
            save_live_favorites(favs)
            st.rerun()
    else:
        st.caption("No formations yet.")

    # Seed from frequency / dropdowns
    with st.expander("Import suggestions", expanded=False):
        sug_forms = favorite_tags(
            live_logs, "formation", opponent, learned_kind="formation", limit=12
        )
        for o in form_opts or []:
            if o and o not in sug_forms:
                sug_forms.append(o)
        sug_forms = sug_forms[:12]
        pick_forms = st.multiselect("Suggested formations", sug_forms, key="fav_sug_forms")
        if st.button("Add suggested formations", key="fav_sug_forms_btn") and pick_forms:
            for name in pick_forms:
                favs["formations"] = _add_favorite_name(favs["formations"], name)
            save_live_favorites(favs)
            st.rerun()

        sug_plays = favorite_tags(
            live_logs, "play_call", opponent, learned_kind="play_call", limit=20
        )
        for o in play_opts or []:
            if o and o not in sug_plays:
                sug_plays.append(o)
        sug_plays = sug_plays[:20]
        c_type, c_picks = st.columns([1, 3])
        with c_type:
            import_type = st.selectbox(
                "Import as",
                PLAY_TYPES,
                format_func=lambda t: PLAY_TYPE_LABELS[t],
                key="fav_sug_play_type",
            )
        with c_picks:
            pick_plays = st.multiselect("Suggested plays", sug_plays, key="fav_sug_plays")
        if st.button("Add suggested plays", key="fav_sug_plays_btn") and pick_plays:
            bucket = list(favs["plays"].get(import_type) or [])
            for name in pick_plays:
                bucket = _add_favorite_name(bucket, name)
            favs["plays"][import_type] = bucket
            save_live_favorites(favs)
            st.rerun()

        sug_mot = favorite_tags(live_logs, "motion", opponent, learned_kind="motion", limit=12)
        for o in motion_opts or []:
            if o and o not in sug_mot:
                sug_mot.append(o)
        sug_mot = sug_mot[:12]
        pick_mot = st.multiselect("Suggested motions", sug_mot, key="fav_sug_mot")
        if st.button("Add suggested motions", key="fav_sug_mot_btn") and pick_mot:
            for name in pick_mot:
                favs["motions"] = _add_favorite_name(favs["motions"], name)
            save_live_favorites(favs)
            st.rerun()

    # --- Variants ---
    st.markdown("**Formation variants**")
    st.caption("e.g. Bash on Slot Dip — same formation, different WR splits.")
    form_for_var = st.selectbox(
        "Variants for formation",
        ["(global — any formation)"] + favs["formations"],
        key="fav_var_form",
    )
    v_add, v_btn = st.columns([3, 1])
    new_var = v_add.text_input("Add variant", key="fav_add_var", placeholder="e.g. Bash")
    if v_btn.button("Add", key="fav_add_var_btn", use_container_width=True) and new_var.strip():
        if form_for_var.startswith("(global"):
            favs["variants"] = _add_favorite_name(favs["variants"], new_var)
        else:
            cur = list(favs["variants_by_formation"].get(form_for_var) or [])
            favs["variants_by_formation"][form_for_var] = _add_favorite_name(cur, new_var)
        save_live_favorites(favs)
        st.rerun()

    if form_for_var.startswith("(global"):
        cur_vars = list(favs["variants"])
    else:
        cur_vars = list(favs["variants_by_formation"].get(form_for_var) or [])
    if cur_vars:
        rm_vars = st.multiselect("Remove variants", cur_vars, key="fav_rm_vars")
        if st.button("Remove selected variants", key="fav_rm_vars_btn") and rm_vars:
            if form_for_var.startswith("(global"):
                for name in rm_vars:
                    favs["variants"] = _remove_favorite_name(favs["variants"], name)
            else:
                bucket = list(favs["variants_by_formation"].get(form_for_var) or [])
                for name in rm_vars:
                    bucket = _remove_favorite_name(bucket, name)
                favs["variants_by_formation"][form_for_var] = bucket
            save_live_favorites(favs)
            st.rerun()
    else:
        st.caption("No variants for this scope yet.")

    # --- Motions ---
    st.markdown("**Motions**")
    m_add, m_btn = st.columns([3, 1])
    new_mot = m_add.text_input("Add motion", key="fav_add_mot", placeholder="e.g. Jet")
    if m_btn.button("Add", key="fav_add_mot_btn", use_container_width=True) and new_mot.strip():
        favs["motions"] = _add_favorite_name(favs["motions"], new_mot)
        save_live_favorites(favs)
        st.rerun()
    if favs["motions"]:
        rm_mot = st.multiselect("Remove motions", favs["motions"], key="fav_rm_mots")
        if st.button("Remove selected motions", key="fav_rm_mots_btn") and rm_mot:
            for name in rm_mot:
                favs["motions"] = _remove_favorite_name(favs["motions"], name)
            save_live_favorites(favs)
            st.rerun()
    else:
        st.caption("No motions yet.")

    # --- Plays by type ---
    st.markdown("**Plays by type**")
    ptype = st.radio(
        "Play type",
        PLAY_TYPES,
        format_func=lambda t: PLAY_TYPE_LABELS[t],
        horizontal=True,
        key="fav_edit_play_type",
    )
    p_add, p_btn = st.columns([3, 1])
    new_play = p_add.text_input(
        f"Add {PLAY_TYPE_LABELS[ptype]} play",
        key="fav_add_play",
        placeholder="e.g. Molly",
    )
    if p_btn.button("Add", key="fav_add_play_btn", use_container_width=True) and new_play.strip():
        bucket = list(favs["plays"].get(ptype) or [])
        favs["plays"][ptype] = _add_favorite_name(bucket, new_play)
        save_live_favorites(favs)
        st.rerun()
    cur_plays = list(favs["plays"].get(ptype) or [])
    if cur_plays:
        st.write(", ".join(cur_plays))
        rm_plays = st.multiselect(f"Remove {PLAY_TYPE_LABELS[ptype]} plays", cur_plays, key="fav_rm_plays")
        if st.button("Remove selected plays", key="fav_rm_plays_btn") and rm_plays:
            bucket = list(favs["plays"].get(ptype) or [])
            for name in rm_plays:
                bucket = _remove_favorite_name(bucket, name)
            favs["plays"][ptype] = bucket
            save_live_favorites(favs)
            st.rerun()
        # Move play to another type
        if cur_plays:
            mv_c1, mv_c2, mv_c3 = st.columns([2, 2, 1])
            move_name = mv_c1.selectbox("Move play", cur_plays, key="fav_mv_play")
            move_to = mv_c2.selectbox(
                "To type",
                [t for t in PLAY_TYPES if t != ptype],
                format_func=lambda t: PLAY_TYPE_LABELS[t],
                key="fav_mv_to",
            )
            if mv_c3.button("Move", key="fav_mv_btn", use_container_width=True) and move_name:
                src = _remove_favorite_name(list(favs["plays"].get(ptype) or []), move_name)
                dst = _add_favorite_name(list(favs["plays"].get(move_to) or []), move_name)
                favs["plays"][ptype] = src
                favs["plays"][move_to] = dst
                save_live_favorites(favs)
                st.rerun()
    else:
        st.caption(f"No {PLAY_TYPE_LABELS[ptype]} favorites yet.")


def _ensure_drive_for_log(opponent: str) -> int:
    """Return active drive id; auto-start if none open."""
    did = current_drive_id(opponent)
    if did is not None:
        return int(did)
    return int(start_drive(opponent))


def _commit_live_play(
    *,
    opponent: str,
    half: int,
    unit: str,
    down: int,
    distance_yards: int,
    field_zone: str,
    dist_bucket: str,
    formation: str,
    play_call: str,
    result: str,
    yards_gained: int,
    motion: str = "",
    formation_variant: str = "",
    play_type: str = "",
    run_tag: str = "",
    pass_tag: str = "",
    def_front: str = "",
    coverage: str = "",
    blitz: str = "",
    note: str = "",
    film_pending: bool = True,
    auto_first: bool = False,
    ball_yard: int | float | None = None,
    ball_player: str = "",
    touch_role: str = "",
    pass_player: str = "",
    save_new_play: bool = False,
    phrase: str = "",
) -> list[str]:
    """Validate + append one live play. Returns coercion warnings."""
    result, yards_gained, warnings = validate_live_play(result, yards_gained, distance_yards)

    run_tag = _ql_norm(run_tag)
    pass_tag = _ql_norm(pass_tag)
    ptype = str(play_type or "").strip().lower()
    if ptype not in PLAY_TYPES:
        ptype = ""

    # Fill missing tags from a compound play_call when booth only typed one field
    if (not run_tag and not pass_tag) and play_call:
        split = _split_play_tags(play_call, ptype or "run", load_live_favorites())
        run_tag = split.get("run_tag") or run_tag
        pass_tag = split.get("pass_tag") or pass_tag
        ptype = split.get("play_type") or ptype

    play_call = _display_play_call(run_tag, pass_tag, play_call)

    if not formation and not play_call and not run_tag and not pass_tag:
        warnings.append("Need formation or play call.")
        return warnings

    drive_id = _ensure_drive_for_log(opponent)
    half_i = int(half)
    try:
        from booth_snaps import (
            advance_booth_snap,
            find_snap_index,
            merge_snap_values,
            sync_booth_snap_to_drive,
        )
        from mesh_engine import load_live_log

        logs_now = load_live_log()
        snap = sync_booth_snap_to_drive(
            opponent, drive_id, half=half_i, live_logs=logs_now
        )
        play_n = int(snap.get("play_n") or 1)
    except Exception:
        play_n = 1
        try:
            from mesh_engine import load_live_log

            logs_now = load_live_log()
        except Exception:
            logs_now = None
        find_snap_index = None  # type: ignore
        merge_snap_values = None  # type: ignore
        advance_booth_snap = None  # type: ignore

    if unit == "Offense":
        mesh_call = play_call or "(none)"
    else:
        if def_front or coverage:
            mesh_call = f"{def_front or 'Unknown'}  |  {coverage or 'Unknown'}"
        else:
            mesh_call = play_call or "(none)"

    try:
        ball = (
            int(ball_yard)
            if ball_yard is not None
            else int(st.session_state.get("lt_ball_yard") or zone_default_ball_yard(field_zone))
        )
    except (TypeError, ValueError):
        ball = zone_default_ball_yard(field_zone)
    field_zone = ball_yard_to_zone(ball)

    # Prefer tagger end-yard for gain when present (Incomplete stays 0)
    end_from_tagger = None
    try:
        if find_snap_index is not None and logs_now is not None and not logs_now.empty:
            _pre_idx = find_snap_index(logs_now, drive_id, play_n)
            if _pre_idx is not None:
                _pre = logs_now.reset_index(drop=True).loc[int(_pre_idx)].to_dict()
                raw_end = _pre.get("end_ball_yard")
                if raw_end is not None and str(raw_end).strip() != "":
                    end_from_tagger = int(raw_end)
    except Exception:
        end_from_tagger = None
    result_l = str(result or "").strip().lower()
    if end_from_tagger is not None and result_l not in {
        "incomplete",
        "inc",
        "turnover",
        "int",
        "fumble",
    }:
        auto_yds = yards_from_ball_span(ball, end_from_tagger)
        if auto_yds is not None:
            yards_gained = int(auto_yds)
            warnings.append(
                f"Yards from tagger end ({format_ball_spot(end_from_tagger)}) → {yards_gained:+d}"
            )

    bp = str(ball_player or "").strip()
    # Dual-tag RPO concepts → logged type is run or pass from outcome / touch
    ptype = resolve_logged_play_type(
        run_tag=run_tag,
        pass_tag=pass_tag,
        play_type=ptype,
        result=result,
        touch_role=str(touch_role or ""),
        phrase=str(phrase or ""),
    )
    role = str(touch_role or "").strip() or infer_touch_role(
        ptype, result, bp, phrase=str(phrase or ""), touch_role=str(touch_role or "")
    )
    if run_tag and pass_tag and role in {"carry", "target"}:
        ptype = "run" if role == "carry" else "pass"

    on_now = get_on_field()
    slots_now = get_formation_slots()
    pp = resolve_pass_player(
        pass_player=str(pass_player or ""),
        play_type=ptype,
        touch_role=role,
        result=result,
        phrase=str(phrase or ""),
        slots=slots_now,
    )
    new_row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "opponent": opponent,
        "half": half_i,
        "unit": unit,
        "down": int(down),
        "distance": dist_bucket,
        "distance_yards": int(distance_yards),
        "field_zone": field_zone,
        "ball_yard": int(ball),
        "end_ball_yard": end_from_tagger if end_from_tagger is not None else "",
        "situation": situation_label(
            int(down), dist_bucket, field_zone, ball_yard=ball
        ),
        "formation": formation,
        "formation_variant": formation_variant,
        "play_call": play_call,
        "play_type": ptype,
        "run_tag": run_tag,
        "pass_tag": pass_tag,
        "motion": motion,
        "def_front": def_front,
        "coverage": coverage,
        "blitz": blitz if blitz else "",
        "call": mesh_call,
        "result": result,
        "yards_gained": int(yards_gained),
        "players_on": format_players_on(on_now),
        "lineup": format_lineup_slots(slots_now),
        "ball_player": bp,
        "touch_role": role,
        "pass_player": pp,
        "note": note,
        "film_pending": "Yes" if film_pending else "No",
        "drive_id": drive_id,
        "play_n": play_n,
    }

    # Merge onto parallel tagger stub if this drive+play already exists
    idx = None
    if find_snap_index is not None and logs_now is not None:
        try:
            idx = find_snap_index(logs_now, drive_id, play_n)
        except Exception:
            idx = None
    if (
        idx is not None
        and logs_now is not None
        and not logs_now.empty
        and merge_snap_values is not None
    ):
        existing = logs_now.reset_index(drop=True).loc[idx].to_dict()
        # Keep film tags already filled; Main fills call/result
        merged = merge_snap_values(existing, new_row)
        # Main just logged — refresh timestamp / call fields from Main
        for k in (
            "timestamp",
            "formation",
            "formation_variant",
            "play_call",
            "play_type",
            "run_tag",
            "pass_tag",
            "result",
            "yards_gained",
            "down",
            "distance",
            "distance_yards",
            "field_zone",
            "ball_yard",
            "situation",
            "ball_player",
            "touch_role",
            "pass_player",
            "players_on",
            "lineup",
            "call",
            "play_n",
        ):
            if k in new_row:
                merged[k] = new_row[k]
        # Preserve non-empty film from stub
        for k in ("def_front", "coverage", "blitz", "motion"):
            if str(existing.get(k) or "").strip() and not str(new_row.get(k) or "").strip():
                merged[k] = existing.get(k)
        front = str(merged.get("def_front") or "").strip()
        cov = str(merged.get("coverage") or "").strip()
        if front and cov:
            merged["film_pending"] = "No"
        # Keep tagger end spot if Main didn't supply one
        if str(existing.get("end_ball_yard") or "").strip() and not str(
            new_row.get("end_ball_yard") or ""
        ).strip():
            merged["end_ball_yard"] = existing.get("end_ball_yard")
        update_live_log_at(int(idx), merged)
    else:
        append_live_log(new_row)

    if advance_booth_snap is not None:
        try:
            advance_booth_snap(drive_id)
        except Exception:
            pass
    learn_live_tag("formation", formation)
    if formation_variant:
        learn_live_tag("formation_variant", formation_variant)
    learn_live_tag("play_call", play_call)
    if run_tag or pass_tag:
        learn_rpo_tags(run_tag, pass_tag)
    elif ptype and play_call:
        learn_favorite_play(play_call, ptype)
    elif save_new_play and play_call:
        learn_inbox_play(play_call)
    learn_live_tag("motion", motion)
    learn_live_tag("def_front", def_front)
    learn_live_tag("coverage", coverage)
    st.session_state.lt_tag_pending = {
        "ql_form": formation,
        "ql_variant": formation_variant,
        "ql_motion": motion,
        "ql_play": play_call,
        "ql_run_tag": run_tag,
        "ql_pass_tag": pass_tag,
        "ql_play_type": ptype
        or st.session_state.get("ql_play_type")
        or st.session_state.get("lt_play_type", "run"),
        "ql_step": 0,
        "ql_form_typed": "",
        "ql_play_typed": "",
        "ql_motion_typed": "",
        "ql_variant_typed": "",
        "ql_form_dd": "",
        "ql_play_dd": "",
        "ql_motion_dd": "",
        "lt_form": formation,
        "lt_form_custom": "",
        "lt_play": play_call,
        "lt_play_custom": "",
        "lt_motion": motion,
        "lt_motion_custom": "",
        "lt_front": def_front,
        "lt_front_custom": "",
        "lt_cov": coverage,
        "lt_cov_custom": "",
        "lt_play_type": ptype or st.session_state.get("lt_play_type", "run"),
    }
    st.session_state.lt_situation_pending = advance_live_situation(
        int(down),
        int(distance_yards),
        int(yards_gained),
        str(result),
        str(field_zone),
        auto_first=bool(auto_first),
        ball_yard=int(ball),
    )
    st.session_state.lt_blitz_reset = True
    st.session_state.lt_gain = 0
    st.session_state.lt_result = "Gain"
    st.session_state.lt_last_warnings = warnings
    return warnings


def _live_track_fill_film(
    opponent: str,
    offense_df: pd.DataFrame,
    live_logs: pd.DataFrame,
    focuses: list[str] | None = None,
) -> None:
    """Between-drive editor: add coverage / blitz / front from Sky Coach.

    focuses: optional subset (front / coverage / blitz) for split taggers.
    None = master / all film fields.
    """
    from booth_stations import (
        FILM_FOCUSES,
        FOCUS_BLITZ,
        FOCUS_COVERAGE,
        FOCUS_FRONT,
        focus_summary,
    )

    film_focus = (
        list(FILM_FOCUSES)
        if focuses is None
        else [f for f in focuses if f in FILM_FOCUSES]
    )
    if not film_focus:
        film_focus = list(FILM_FOCUSES)
    show_front = FOCUS_FRONT in film_focus
    show_cov = FOCUS_COVERAGE in film_focus
    show_blitz = FOCUS_BLITZ in film_focus
    partial = set(film_focus) != set(FILM_FOCUSES)

    st.subheader(
        "Fill Film" if not partial else f"Fill Film · {focus_summary(film_focus)}"
    )
    st.caption(
        "Tag only your assigned look, then next series."
        if partial
        else "Scoped to a drive by default — tag coverage / blitz / front from Sky Coach "
        "(phrase or dropdowns), then next series."
    )
    if live_logs is None or live_logs.empty:
        st.info("No plays logged yet.")
        return

    ensure_default_film_tags()

    full = live_logs.reset_index(drop=True)
    try:
        full = pd.read_csv(LIVE_LOG_FILE).reset_index(drop=True)
    except Exception:
        pass
    if "opponent" in full.columns:
        opp_mask = full["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()
        opp_df = full.loc[opp_mask]
    else:
        opp_df = full

    drive_ids: list[str] = []
    if "drive_id" in opp_df.columns:
        for v in opp_df["drive_id"].dropna().unique():
            try:
                drive_ids.append(str(int(float(v))))
            except (TypeError, ValueError):
                continue
        drive_ids = sorted(set(drive_ids), key=lambda x: int(x))
    dstate = load_drive_state()
    default_drive = dstate.get("last_ended_drive_id")
    if default_drive is not None:
        default_drive = str(int(default_drive))
    options = ["all"] + drive_ids
    if "ff_drive_filter" not in st.session_state:
        st.session_state.ff_drive_filter = (
            default_drive if default_drive in options else "all"
        )
    if st.session_state.ff_drive_filter not in options:
        st.session_state.ff_drive_filter = default_drive if default_drive in options else "all"
    drive_pick = st.selectbox(
        "Drive",
        options,
        format_func=lambda x: "All pending" if x == "all" else f"Drive #{x}",
        key="ff_drive_filter",
    )

    def _in_drive(row) -> bool:
        if drive_pick == "all":
            return True
        try:
            return str(int(float(row.get("drive_id")))) == drive_pick
        except (TypeError, ValueError):
            return False

    idxs = [
        int(i)
        for i in opp_df.index
        if (
            (
                play_needs_tag_focuses(full.loc[i], film_focus)
                if partial
                else play_needs_film(full.loc[i])
            )
            and _in_drive(full.loc[i])
        )
    ]

    if not idxs:
        st.success(
            "Nothing pending for this drive."
            if drive_pick != "all"
            else (
                f"No plays waiting for {focus_summary(film_focus)}."
                if partial
                else "All plays have film tags — nothing pending."
            )
        )
        _render_live_log_tail(opponent, live_logs)
        return

    front_opts = _merge_film_tag_options(
        _tag_options(
            offense_df["def_front"] if "def_front" in offense_df.columns else pd.Series(dtype=str),
        ),
        full["def_front"] if "def_front" in full.columns else pd.Series(dtype=str),
        kind="def_front",
    )
    cov_opts = _merge_film_tag_options(
        _tag_options(
            offense_df["coverage"] if "coverage" in offense_df.columns else pd.Series(dtype=str),
        ),
        full["coverage"] if "coverage" in full.columns else pd.Series(dtype=str),
        kind="coverage",
    )
    motion_opts = _merge_tag_options(
        _tag_options(
            offense_df["motion"] if "motion" in offense_df.columns else pd.Series(dtype=str),
        ),
        full["motion"] if "motion" in full.columns else pd.Series(dtype=str),
        kind="motion",
    )
    for m in _hudl_motion_options():
        if m not in motion_opts:
            motion_opts.append(m)

    def _save_film_row(
        idx: int,
        *,
        front: str | None = None,
        cov: str | None = None,
        blitz: str | None = None,
        motion: str = "",
        note: str | None = None,
        yds: int | None = None,
        result: str | None = None,
    ) -> tuple[bool, list[str]]:
        row = full.loc[idx]
        unit = str(row.get("unit") or "Offense")
        play_call = str(row.get("play_call") or "")
        to_go = int(row.get("distance_yards") or 10)
        yds_in = int(row.get("yards_gained") or 0) if yds is None else int(yds)
        result_in = str(row.get("result") or "Gain") if result is None else str(result)
        result_v, yds_v, warns = validate_live_play(result_in, yds_in, to_go)
        motion_v = motion if motion else str(row.get("motion") or "")
        note_v = str(row.get("note") or "") if note is None else str(note)

        front_v = (
            front
            if (show_front and front is not None)
            else str(row.get("def_front") or "")
        )
        cov_v = (
            cov if (show_cov and cov is not None) else str(row.get("coverage") or "")
        )
        blitz_v = (
            blitz
            if (show_blitz and blitz is not None)
            else str(row.get("blitz") or "")
        )

        if unit.lower() == "offense":
            mesh_call = play_call or str(row.get("call") or "(none)")
        else:
            mesh_call = (
                f"{front_v or 'Unknown'}  |  {cov_v or 'Unknown'}"
                if front_v or cov_v
                else str(row.get("call") or "(none)")
            )

        still_missing = set()
        if not str(front_v or "").strip():
            still_missing.add("front")
        if not str(cov_v or "").strip():
            still_missing.add("coverage")
        if str(blitz_v or "").strip().lower() not in {"yes", "no"}:
            still_missing.add("blitz")

        patch: dict = {
            "motion": motion_v,
            "note": note_v,
            "yards_gained": int(yds_v),
            "result": result_v,
            "call": mesh_call,
            "film_pending": "Yes" if still_missing else "No",
        }
        if show_front and front is not None:
            patch["def_front"] = front_v
        if show_cov and cov is not None:
            patch["coverage"] = cov_v
        if show_blitz and blitz is not None:
            patch["blitz"] = blitz_v

        ok = update_live_log_at(idx, patch)
        if ok:
            if show_front and front_v:
                learn_live_tag("def_front", front_v)
            if show_cov and cov_v:
                learn_live_tag("coverage", cov_v)
            if motion_v:
                learn_live_tag("motion", motion_v)
        return ok, warns

    # Clear phrase box after successful LOG (same pattern as Quick Log)
    if st.session_state.pop("ff_clear_phrase_pending", False):
        st.session_state.ff_phrase_global = ""

    newest = idxs[-1]
    if not partial:
        st.markdown("#### Film phrase")
        st.caption(
            'Say the look — e.g. "Even front, no blitz, cover 3" or "odd front, blitz, cover 4". '
            "Applies to the newest pending play in this drive."
        )
        st.text_input(
            "Phrase",
            key="ff_phrase_global",
            placeholder="Even front, no blitz, cover 3",
            label_visibility="collapsed",
        )
        pg1, pg2, pg3 = st.columns([2, 2, 1])
        with pg1:
            log_newest = st.button(
                "LOG film from phrase ▶",
                type="primary",
                key="ff_log_phrase_global",
                use_container_width=True,
            )
        with pg2:
            fill_newest = st.button(
                "Fill newest only",
                key="ff_fill_phrase_global",
                use_container_width=True,
            )
        with pg3:
            if st.button("Clear", key="ff_clear_phrase_global", use_container_width=True):
                st.session_state.ff_clear_phrase_pending = True
                st.rerun()

        phrase_g = str(st.session_state.get("ff_phrase_global") or "").strip()
        if log_newest or fill_newest:
            if not phrase_g:
                st.warning("Type or speak a film phrase first.")
            else:
                parsed_g = parse_film_phrase(phrase_g)
                if not _ff_phrase_has_tags(parsed_g):
                    st.warning("Could not parse front / blitz / coverage from that phrase.")
                elif fill_newest:
                    _ff_apply_phrase_to_keys(parsed_g, newest)
                    bits = [
                        parsed_g.get("def_front") or "",
                        parsed_g.get("blitz") or "",
                        parsed_g.get("coverage") or "",
                    ]
                    st.info("Filled newest → " + " · ".join(b for b in bits if b))
                    st.rerun()
                else:
                    row_n = full.loc[newest]
                    front = parsed_g.get("def_front") or str(row_n.get("def_front") or "")
                    cov = parsed_g.get("coverage") or str(row_n.get("coverage") or "")
                    blitz = parsed_g.get("blitz") or str(row_n.get("blitz") or "No") or "No"
                    ok, warns = _save_film_row(newest, front=front, cov=cov, blitz=blitz)
                    if ok:
                        st.session_state.ff_clear_phrase_pending = True
                        if warns:
                            st.warning(" · ".join(warns))
                        st.success(
                            f"Film saved on play #{newest}: "
                            f"{front or '—'} · blitz {blitz} · {cov or '—'}"
                        )
                        st.rerun()
                    else:
                        st.error("Could not save.")

    st.write(f"**{len(idxs)}** play(s) waiting — newest first.")
    for idx in reversed(idxs[-15:]):
        row = full.loc[idx]
        title = _live_log_row_label(row, idx)
        with st.expander(title, expanded=(idx == idxs[-1])):
            if not partial:
                if st.session_state.pop(f"ff_clear_phrase_{idx}", False):
                    st.session_state[f"ff_phrase_{idx}"] = ""
                st.text_input(
                    "Film phrase",
                    key=f"ff_phrase_{idx}",
                    placeholder="odd front, blitz, cover 4",
                )
                pa1, pa2 = st.columns(2)
                with pa1:
                    apply_p = st.button(
                        "Apply phrase",
                        key=f"ff_apply_{idx}",
                        use_container_width=True,
                    )
                with pa2:
                    log_p = st.button(
                        "LOG from phrase ▶",
                        key=f"ff_log_phrase_{idx}",
                        use_container_width=True,
                    )
                phrase_p = str(st.session_state.get(f"ff_phrase_{idx}") or "").strip()
                if apply_p or log_p:
                    if not phrase_p:
                        st.warning("Type a film phrase for this play.")
                    else:
                        parsed_p = parse_film_phrase(phrase_p)
                        if not _ff_phrase_has_tags(parsed_p):
                            st.warning("Could not parse front / blitz / coverage.")
                        elif apply_p:
                            _ff_apply_phrase_to_keys(parsed_p, idx)
                            st.rerun()
                        else:
                            front = parsed_p.get("def_front") or str(row.get("def_front") or "")
                            cov = parsed_p.get("coverage") or str(row.get("coverage") or "")
                            blitz = parsed_p.get("blitz") or str(row.get("blitz") or "No") or "No"
                            ok, warns = _save_film_row(idx, front=front, cov=cov, blitz=blitz)
                            if ok:
                                st.session_state[f"ff_clear_phrase_{idx}"] = True
                                if warns:
                                    st.warning(" · ".join(warns))
                                st.success(f"Updated play #{idx}.")
                                st.rerun()
                            else:
                                st.error("Could not save.")

            # Show already-tagged fields as caption for split taggers
            if partial:
                bits = []
                if str(row.get("def_front") or "").strip():
                    bits.append(f"Front {row.get('def_front')}")
                if str(row.get("coverage") or "").strip():
                    bits.append(f"Cov {row.get('coverage')}")
                bz = str(row.get("blitz") or "").strip()
                if bz.lower() in {"yes", "no"}:
                    bits.append(f"Blitz {bz}")
                if bits:
                    st.caption("Already tagged: " + " · ".join(bits))

            cols_n = sum([show_front, show_cov, show_blitz, not partial])
            cols_n = max(cols_n, 1)
            cols = st.columns(cols_n)
            ci = 0
            front = str(row.get("def_front") or "")
            cov = str(row.get("coverage") or "")
            blitz = str(row.get("blitz") or "No") or "No"
            motion = str(row.get("motion") or "")
            if show_front:
                with cols[ci]:
                    front = _select_or_type("Front", front_opts, f"ff_front_{idx}")
                ci += 1
            if show_cov:
                with cols[ci]:
                    cov = _select_or_type("Coverage", cov_opts, f"ff_cov_{idx}")
                ci += 1
            if show_blitz:
                with cols[ci]:
                    blitz = st.radio(
                        "Blitz",
                        ["No", "Yes"],
                        horizontal=True,
                        key=f"ff_blitz_{idx}",
                        index=1 if str(row.get("blitz") or "").strip().lower() == "yes" else 0,
                    )
                ci += 1
            if not partial:
                with cols[ci]:
                    motion = _select_or_type("Motion", motion_opts, f"ff_motion_{idx}")
                note = st.text_input(
                    "Note",
                    value=str(row.get("note") or ""),
                    key=f"ff_note_{idx}",
                )
                with st.expander("Fix gain / result (optional)", expanded=False):
                    yds = st.number_input(
                        "Yards",
                        value=int(row.get("yards_gained") or 0),
                        step=1,
                        key=f"ff_yds_{idx}",
                    )
                    result_opts = [
                        "Gain",
                        "No gain",
                        "Incomplete",
                        "TD",
                        "Turnover",
                        "Penalty",
                        "Sack / TFL",
                        "Punt",
                        "Other",
                    ]
                    cur_res = str(row.get("result") or "Gain")
                    result = st.selectbox(
                        "Result",
                        result_opts,
                        index=result_opts.index(cur_res) if cur_res in result_opts else 0,
                        key=f"ff_result_{idx}",
                    )
            else:
                note = None
                yds = None
                result = None

            save_kwargs = {}
            if show_front:
                save_kwargs["front"] = front
            if show_cov:
                save_kwargs["cov"] = cov
            if show_blitz:
                save_kwargs["blitz"] = blitz
            if not partial:
                save_kwargs["motion"] = motion
                save_kwargs["note"] = note
                save_kwargs["yds"] = int(yds) if yds is not None else None
                save_kwargs["result"] = result

            if st.button(
                "Save" if partial else "Save film tags",
                type="primary",
                key=f"ff_save_{idx}",
                use_container_width=True,
            ):
                ok, warns = _save_film_row(idx, **save_kwargs)
                if ok:
                    if warns:
                        st.warning(" · ".join(warns))
                    st.success(f"Updated play #{idx}.")
                    st.rerun()
                else:
                    st.error("Could not save.")

    if not partial and st.button("Mark all remaining as No blitz / skip film", key="ff_skip_all"):
        for idx in idxs:
            row = full.loc[idx]
            update_live_log_at(
                idx,
                {
                    "blitz": str(row.get("blitz") or "No") or "No",
                    "film_pending": "No",
                },
            )
        st.rerun()

    _render_live_log_tail(opponent, pd.read_csv(LIVE_LOG_FILE) if LIVE_LOG_FILE.exists() else live_logs)



def _render_live_log_tail(opponent: str, live_logs: pd.DataFrame | None) -> None:
    if live_logs is None or live_logs.empty:
        st.info("No plays logged yet tonight.")
        return
    show = live_logs.copy()
    if "opponent" in show.columns:
        filt = show[show["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()]
        if not filt.empty:
            show = filt
    cols = [
        c
        for c in [
            "timestamp",
            "drive_id",
            "play_n",
            "half",
            "down",
            "distance_yards",
            "formation",
            "formation_variant",
            "motion",
            "play_call",
            "play_type",
            "ball_player",
            "touch_role",
            "yards_gained",
            "result",
            "coverage",
            "blitz",
            "def_front",
            "film_pending",
            "players_on",
        ]
        if c in show.columns
    ]
    pending = count_film_pending(show, opponent)
    st.caption(f"{len(show)} plays · {pending} need film")
    st.dataframe(show[cols].tail(20) if cols else show.tail(20), hide_index=True, use_container_width=True)
    _render_live_log_delete_controls(opponent, key_prefix="lt")
    st.download_button(
        "Download live log (CSV)",
        show.to_csv(index=False),
        file_name="live_log.csv",
        mime="text/csv",
        key="lt_download",
    )



def _ql_phrase_play_tags(
    parsed: dict, sticky_run: str = "", sticky_pass: str = ""
) -> tuple[str, str]:
    """Run/pass tags for this phrase. Sticky fills only when no play was named."""
    parsed_run = _ql_norm(parsed.get("run_tag") or "")
    parsed_pass = _ql_norm(parsed.get("pass_tag") or "")
    named = bool(parsed_run or parsed_pass or _ql_norm(parsed.get("play_call") or ""))
    if named:
        return parsed_run, parsed_pass
    lane = str(parsed.get("outcome_lane") or "").strip().lower()
    ptype = str(parsed.get("play_type") or "").strip().lower()
    run_tag = parsed_run
    pass_tag = parsed_pass
    if not run_tag and lane != "pass" and ptype != "pass":
        run_tag = _ql_norm(sticky_run)
    if not pass_tag and lane != "run" and ptype != "run":
        pass_tag = _ql_norm(sticky_pass)
    return run_tag, pass_tag


def _ql_build_phrase_draft(phrase: str, parsed: dict, booth_favs: dict) -> dict:
    """Build an editable confirm draft from a spoken/typed snap phrase."""
    _ql_apply_phrase_parse(parsed)
    if not parsed.get("variant"):
        st.session_state.ql_variant = ""
    if not parsed.get("motion"):
        st.session_state.ql_motion = ""

    formation = _ql_resolve_piece("ql_form")
    variant = _ql_resolve_piece("ql_variant")
    if variant.lower() in {"base", "none", "(none)", "—", "no variant"}:
        variant = ""
    motion = _ql_resolve_piece("ql_motion")
    run_tag, pass_tag = _ql_phrase_play_tags(
        parsed,
        str(st.session_state.get("ql_run_tag") or ""),
        str(st.session_state.get("ql_pass_tag") or ""),
    )
    play_call = str(parsed.get("play_call") or "") or _display_play_call(
        run_tag, pass_tag, ""
    )
    play_type = parsed.get("play_type") or st.session_state.get("ql_play_type") or "run"
    if play_type not in PLAY_TYPES:
        play_type = "run"
    if (not run_tag and not pass_tag) and play_call:
        split = _split_play_tags(play_call, play_type, booth_favs)
        run_tag = split.get("run_tag") or ""
        pass_tag = split.get("pass_tag") or ""
        play_type = split.get("play_type") or play_type
        play_call = split.get("play_call") or play_call
    else:
        play_call = _display_play_call(run_tag, pass_tag, play_call)

    down = int(
        parsed["down"]
        if parsed.get("down") is not None
        else (st.session_state.get("lt_down") or 1)
    )
    distance_yards = int(
        parsed["distance_yards"]
        if parsed.get("distance_yards") is not None
        else (st.session_state.get("lt_dist_y") or 10)
    )
    if parsed.get("ball_yard") is not None:
        try:
            ball_yard = int(parsed["ball_yard"])
        except (TypeError, ValueError):
            ball_yard = int(
                st.session_state.get("lt_ball_yard")
                or zone_default_ball_yard(st.session_state.get("lt_zone"))
            )
    else:
        try:
            ball_yard = int(
                st.session_state.get("lt_ball_yard")
                or zone_default_ball_yard(
                    parsed.get("field_zone")
                    or st.session_state.get("lt_zone")
                    or "midfield"
                )
            )
        except (TypeError, ValueError):
            ball_yard = zone_default_ball_yard("midfield")
    field_zone = ball_yard_to_zone(ball_yard)

    if parsed.get("has_outcome") and parsed.get("result"):
        result = str(parsed["result"])
    else:
        result = str(st.session_state.get("lt_result") or "Gain")
    if parsed.get("yards_gained") is not None:
        yards = int(parsed["yards_gained"])
    elif parsed.get("end_ball_yard") is not None:
        try:
            yards = int(parsed["end_ball_yard"]) - int(ball_yard)
        except (TypeError, ValueError):
            yards = 0
    else:
        try:
            yards = int(st.session_state.get("lt_gain") or 0)
        except (TypeError, ValueError):
            yards = 0
    if result == "TD" and int(yards) <= 0:
        yards = max(1, distance_yards)
    if result == "Penalty" and int(yards) == 0:
        import re

        raw_p = phrase or ""
        m_gain = re.search(r"\bgain\s*(?:of\s*)?(\d{1,2})\b", raw_p, flags=re.I)
        if m_gain:
            yards = abs(int(m_gain.group(1)))
        else:
            m_plus = re.search(
                r"(?:penalty\s*)?(?:\+|plus\s+)(\d{1,2})\b", raw_p, flags=re.I
            )
            if m_plus:
                yards = abs(int(m_plus.group(1)))
            else:
                m_loss = re.search(
                    r"(?:penalty\s*)?(?:minus\s+|[-−–]\s*|loss\s*(?:of\s*)?)(\d{1,2})\b",
                    raw_p,
                    flags=re.I,
                )
                if m_loss:
                    yards = -abs(int(m_loss.group(1)))

    def_front = str(parsed.get("def_front") or "")
    coverage = str(parsed.get("coverage") or "")
    blitz = parsed.get("blitz") if parsed.get("blitz") in {"Yes", "No"} else ""
    auto_first = bool(parsed.get("auto_first")) or (
        str(result) == "Penalty" and int(yards) >= 15
    )
    film_pending = not (bool(def_front) and bool(coverage))
    ball_player = str(parsed.get("ball_player") or "")
    touch_role = str(parsed.get("touch_role") or "")
    pass_player = str(parsed.get("pass_player") or "")
    # GameCast player tap (legacy) still fills ball-to if set; Log no longer shows the field
    if not ball_player:
        ball_player = str(st.session_state.get("lt_gc_ball_player") or "")
    if ball_player and not touch_role:
        touch_role = str(st.session_state.get("lt_gc_touch_role") or "") or infer_touch_role(
            str(play_type),
            str(result),
            ball_player,
            phrase=phrase,
        )
    play_type = (
        resolve_logged_play_type(
            run_tag=run_tag,
            pass_tag=pass_tag,
            play_type=str(play_type),
            result=str(result),
            phrase=phrase,
            outcome_lane=str(parsed.get("outcome_lane") or ""),
            touch_role=touch_role,
        )
        or play_type
    )
    if play_type not in PLAY_TYPES:
        play_type = "run"
    if not pass_player:
        try:
            slots = get_formation_slots()
        except Exception:
            slots = {}
        pass_player = resolve_pass_player(
            play_type=str(play_type),
            touch_role=touch_role,
            result=str(result),
            phrase=phrase,
            outcome_lane=str(parsed.get("outcome_lane") or ""),
            slots=slots,
        )
    play_is_new = bool(parsed.get("play_is_new"))
    catalog = {p[0].lower() for p in _phrase_play_catalog(booth_favs)}
    if not play_is_new:
        known = False
        if run_tag and run_tag.lower() in catalog:
            known = True
        if pass_tag and pass_tag.lower() in catalog:
            known = True
        if play_call and play_call.lower() in catalog:
            known = True
        if (run_tag or pass_tag or play_call) and not known:
            play_is_new = True

    return {
        "phrase": phrase,
        "formation": formation,
        "variant": variant,
        "motion": motion,
        "play_call": play_call,
        "play_type": str(play_type),
        "run_tag": run_tag,
        "pass_tag": pass_tag,
        "outcome_lane": str(parsed.get("outcome_lane") or ""),
        "play_is_new": play_is_new,
        "down": down,
        "distance_yards": distance_yards,
        "ball_yard": ball_yard,
        "field_zone": field_zone,
        "result": result,
        "yards": int(yards),
        "def_front": def_front,
        "coverage": coverage,
        "blitz": str(blitz),
        "auto_first": auto_first,
        "film_pending": film_pending,
        "ball_player": ball_player,
        "touch_role": touch_role,
        "pass_player": pass_player,
        "new_play_guess": str(parsed.get("new_play_guess") or ""),
        "has_outcome": bool(parsed.get("has_outcome")),
    }


def _ql_rerun(*, full: bool = False) -> None:
    """Prefer fragment-scoped rerun on Live Track Log (faster); fall back to full."""
    if full:
        st.rerun()
        return
    try:
        st.rerun(scope="fragment")
    except TypeError:
        st.rerun()


def _ql_draft_ready_for_fast_log(draft: dict) -> tuple[bool, str]:
    """
    Whether a phrase draft can skip the confirm card (one-tap LOG).

    Known call → Fast OK (thin outcome defaults applied). New plays always confirm.
    """
    if not isinstance(draft, dict):
        return False, "Nothing to log"
    if draft.get("play_is_new"):
        return False, "New play — review the name"
    formation = _ql_norm(draft.get("formation") or "")
    run_tag = _ql_norm(draft.get("run_tag") or "")
    pass_tag = _ql_norm(draft.get("pass_tag") or "")
    play_call = _ql_norm(draft.get("play_call") or "")
    if not (formation or run_tag or pass_tag or play_call):
        return False, "Need formation or play tags"
    return True, ""


def _ql_apply_fast_outcome_defaults(draft: dict) -> dict:
    """Fill Gain / 0 when result/yards weren't spoken — keeps Fast one-tap."""
    out = dict(draft)
    if not str(out.get("result") or "").strip():
        out["result"] = "Gain"
    if out.get("yards") is None:
        out["yards"] = 0
    out["has_outcome"] = True
    return out


def _ql_commit_phrase_draft(
    draft: dict,
    *,
    opponent: str,
    half: int,
    unit: str,
    formation: str | None = None,
    variant: str | None = None,
    motion: str | None = None,
    run_tag: str | None = None,
    pass_tag: str | None = None,
    play_type: str | None = None,
    result: str | None = None,
    yards: int | float | None = None,
    ball_player: str | None = None,
    pass_player: str | None = None,
    def_front: str | None = None,
    coverage: str | None = None,
    blitz: str | None = None,
) -> list[str]:
    """Commit a phrase draft (optionally overridden by confirm widgets). Sets success message."""
    formation = _ql_norm(
        formation if formation is not None else draft.get("formation") or ""
    )
    variant = _ql_norm(variant if variant is not None else draft.get("variant") or "")
    if variant.lower() in {"base", "none", "(none)", "—", "no variant"}:
        variant = ""
    motion = _ql_norm(motion if motion is not None else draft.get("motion") or "")
    run_tag = _ql_norm(run_tag if run_tag is not None else draft.get("run_tag") or "")
    pass_tag = _ql_norm(
        pass_tag if pass_tag is not None else draft.get("pass_tag") or ""
    )
    play_call = _display_play_call(run_tag, pass_tag, str(draft.get("play_call") or ""))
    result = str(result if result is not None else draft.get("result") or "Gain")
    try:
        yards_i = int(yards if yards is not None else draft.get("yards") or 0)
    except (TypeError, ValueError):
        yards_i = 0
    ball_player = str(
        ball_player if ball_player is not None else draft.get("ball_player") or ""
    ).strip()
    pass_player = str(
        pass_player if pass_player is not None else draft.get("pass_player") or ""
    ).strip()
    def_front = _ql_norm(
        def_front if def_front is not None else draft.get("def_front") or ""
    )
    coverage = _ql_norm(
        coverage if coverage is not None else draft.get("coverage") or ""
    )
    blitz = str(blitz if blitz is not None else draft.get("blitz") or "")
    if blitz not in {"Yes", "No"}:
        blitz = ""

    if not formation and not play_call and not run_tag and not pass_tag:
        return ["Need a formation or run/pass tag."]

    touch_role = infer_touch_role(
        str(play_type if play_type is not None else draft.get("play_type") or ""),
        result,
        ball_player,
        phrase=str(draft.get("phrase") or ""),
        touch_role=str(draft.get("touch_role") or ""),
    )
    play_type_v = resolve_logged_play_type(
        run_tag=run_tag,
        pass_tag=pass_tag,
        play_type=str(
            play_type if play_type is not None else draft.get("play_type") or ""
        ),
        result=result,
        phrase=str(draft.get("phrase") or ""),
        outcome_lane=str(draft.get("outcome_lane") or ""),
        touch_role=touch_role,
    )
    ball_yard = int(draft.get("ball_yard") or 45)
    field_zone = ball_yard_to_zone(ball_yard)
    dist_bucket = _yards_to_distance_bucket(int(draft.get("distance_yards") or 10))
    film_pending = not (bool(def_front) and bool(coverage))
    play_is_new = bool(draft.get("play_is_new"))

    warns = _commit_live_play(
        opponent=opponent,
        half=int(half),
        unit=unit,
        down=int(draft.get("down") or 1),
        distance_yards=int(draft.get("distance_yards") or 10),
        field_zone=field_zone,
        dist_bucket=dist_bucket,
        formation=formation,
        formation_variant=variant,
        play_call=play_call,
        play_type=str(play_type_v),
        run_tag=run_tag,
        pass_tag=pass_tag,
        motion=motion,
        result=result,
        yards_gained=yards_i,
        def_front=def_front,
        coverage=coverage,
        blitz=blitz,
        note="",
        film_pending=film_pending,
        auto_first=bool(draft.get("auto_first")),
        ball_yard=ball_yard,
        ball_player=ball_player,
        touch_role=str(touch_role or ""),
        pass_player=pass_player,
        save_new_play=bool(play_is_new),
        phrase=str(draft.get("phrase") or ""),
    )
    learn_rpo_tags(run_tag, pass_tag)
    if play_call and str(play_type_v) == "special":
        learn_favorite_play(play_call, "special")

    st.session_state.pop("ql_confirm_draft", None)
    _clear_phrase_confirm_widgets()
    st.session_state.ql_step = 0
    st.session_state.ql_clear_phrase_pending = True
    # Sticky for "Same as last" on the next snap
    last_phrase = str(draft.get("phrase") or "").strip()
    if last_phrase:
        st.session_state.ql_last_phrase = last_phrase
    for k in ("lt_gc_ball_player", "lt_gc_touch_role", "lt_gc_touch_slot"):
        st.session_state.pop(k, None)
    next_sit = st.session_state.get("lt_situation_pending") or {}
    next_note = next_sit.get("note") or "situation advanced"
    bp_bit = f" · ball {ball_player}" if ball_player else ""
    tag_bit = play_call or "—"
    if run_tag or pass_tag:
        tag_bit = f"run {run_tag or '—'} / pass {pass_tag or '—'}"
    msg = (
        f"Logged {compose_formation_label(formation, variant)} · {motion or 'no mot'} · "
        f"{play_type_v} {tag_bit} → {result} ({yards_i:+d}){bp_bit}. {next_note}."
    )
    if play_is_new:
        msg += " New tags saved to favorites."
    st.session_state.lt_last_warnings = ([msg] + (warns or [])) if warns else [msg]
    return warns or []


def _clear_phrase_confirm_widgets() -> None:
    for k in list(st.session_state.keys()):
        if str(k).startswith("ql_cf_"):
            st.session_state.pop(k, None)


def _render_phrase_confirm_card(
    *,
    opponent: str,
    half: int,
    unit: str,
    booth_favs: dict,
    front_opts: list[str] | None = None,
    cov_opts: list[str] | None = None,
) -> bool:
    """Editable confirm before commit. Returns True if card was shown."""
    draft = st.session_state.get("ql_confirm_draft")
    if not isinstance(draft, dict):
        return False

    gen = int(draft.get("_widget_gen") or st.session_state.get("ql_cf_gen") or 0)
    front_opts = list(front_opts or DEFAULT_FILM_FRONTS)
    cov_opts = list(cov_opts or DEFAULT_FILM_COVERAGES)

    st.markdown("#### Confirm snap")
    heard = draft.get("phrase") or "—"
    call_disp = (
        _display_play_call(
            str(draft.get("run_tag") or ""),
            str(draft.get("pass_tag") or ""),
            str(draft.get("play_call") or ""),
        )
        or "—"
    )
    form_disp = " ".join(
        x
        for x in [
            str(draft.get("formation") or "").strip(),
            str(draft.get("variant") or "").strip(),
        ]
        if x and x.lower() not in {"base", "none", "(none)"}
    ) or "—"
    st.caption(
        f"*{heard}*  ·  {form_disp}  ·  {call_disp}  ·  "
        f"{draft.get('down')}&{draft.get('distance_yards')}  ·  "
        f"{format_ball_spot(int(draft.get('ball_yard') or 45))}"
    )
    if draft.get("play_is_new"):
        st.warning("New play — confirm name/type under Edit call details if needed.")

    on_names = list(get_on_field(include_ol=False).keys())
    roster = load_roster()
    roster_names = [str(p.get("name") or "").strip() for p in roster if p.get("name")]
    ball_opts = [""] + sorted(set(on_names + roster_names), key=str.upper)

    # Thin strip: result / yards / ball — what Main fixes under tempo
    result_opts = [
        "Gain",
        "No gain",
        "Incomplete",
        "TD",
        "Turnover",
        "Penalty",
        "Sack / TFL",
        "Punt",
        "Other",
    ]
    cur_res = str(draft.get("result") or "Gain")
    t1, t2, t3 = st.columns([1.2, 1, 1.4])
    with t1:
        result = st.selectbox(
            "Result",
            result_opts,
            index=result_opts.index(cur_res) if cur_res in result_opts else 0,
            key=f"ql_cf_result_{gen}",
        )
    with t2:
        yards = st.number_input(
            "Yards",
            value=int(draft.get("yards") or 0),
            step=1,
            key=f"ql_cf_yards_{gen}",
        )
    with t3:
        bp_cur = str(draft.get("ball_player") or "")
        if bp_cur and bp_cur not in ball_opts:
            ball_opts = [""] + [bp_cur] + [n for n in ball_opts if n]
        bp_idx = ball_opts.index(bp_cur) if bp_cur in ball_opts else 0
        ball_player = st.selectbox(
            "Ball to",
            ball_opts,
            index=bp_idx,
            format_func=lambda n: n or "(none)",
            key=f"ql_cf_ball_{gen}",
        )

    # Full call editor — only mount widgets when opened (Streamlit always runs expanders)
    need_edit = bool(draft.get("play_is_new"))
    edit_key = f"ql_cf_edit_open_{gen}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = need_edit
    edit_open = st.checkbox(
        "Edit call details",
        key=edit_key,
        help="Formation, tags, passer, defense — leave closed when the caption looks right.",
    )
    if edit_open:
        c1, c2 = st.columns(2)
        with c1:
            formation = st.text_input(
                "Formation", value=str(draft.get("formation") or ""), key=f"ql_cf_form_{gen}"
            )
            variant = st.text_input(
                "Variant", value=str(draft.get("variant") or ""), key=f"ql_cf_var_{gen}"
            )
            try:
                from formation_logic import formation_note as _form_note

                _bn = _form_note(formation, variant)
                if _bn:
                    st.caption(f"Breakdown: {_bn}")
            except Exception:
                pass
            motion = st.text_input(
                "Motion", value=str(draft.get("motion") or ""), key=f"ql_cf_mot_{gen}"
            )
            run_tag = st.text_input(
                "Run tag",
                value=str(draft.get("run_tag") or ""),
                key=f"ql_cf_run_{gen}",
            )
            pass_tag = st.text_input(
                "Pass tag",
                value=str(draft.get("pass_tag") or ""),
                key=f"ql_cf_pass_{gen}",
            )
            ptypes = ["run", "pass", "special"]
            if _ql_norm(str(draft.get("run_tag") or "")) and _ql_norm(
                str(draft.get("pass_tag") or "")
            ):
                ptypes = ["run", "pass"]
                suggested = resolve_logged_play_type(
                    run_tag=str(draft.get("run_tag") or ""),
                    pass_tag=str(draft.get("pass_tag") or ""),
                    play_type=str(draft.get("play_type") or ""),
                    result=str(draft.get("result") or ""),
                    phrase=str(draft.get("phrase") or ""),
                    outcome_lane=str(draft.get("outcome_lane") or ""),
                )
                cur_pt = suggested if suggested in ptypes else "pass"
            else:
                cur_pt = str(draft.get("play_type") or "run")
                if cur_pt == "rpo":
                    cur_pt = "run"
                if cur_pt not in ptypes:
                    ptypes = list(PLAY_TYPES)
            play_type = st.selectbox(
                "Play type",
                ptypes,
                index=ptypes.index(cur_pt) if cur_pt in ptypes else 0,
                format_func=lambda t: PLAY_TYPE_LABELS.get(t, t),
                key=f"ql_cf_ptype_{gen}",
            )
        with c2:
            pp_cur = str(draft.get("pass_player") or "")
            is_pass_snap = (
                str(draft.get("outcome_lane") or "") == "pass"
                or str(draft.get("play_type") or "") == "pass"
                or str(draft.get("result") or "") == "Incomplete"
                or str(draft.get("touch_role") or "") == "target"
            )
            if not pp_cur and is_pass_snap:
                pp_cur = lineup_slot_player("QB")
            if not is_pass_snap:
                pp_cur = str(draft.get("pass_player") or "")
            if pp_cur and pp_cur not in ball_opts:
                ball_opts_p = [""] + [pp_cur] + [n for n in ball_opts if n]
            else:
                ball_opts_p = list(ball_opts)
            pp_idx = ball_opts_p.index(pp_cur) if pp_cur in ball_opts_p else 0
            pass_player = st.selectbox(
                "Passer",
                ball_opts_p,
                index=pp_idx,
                format_func=lambda n: n or "(none / not a pass)",
                key=f"ql_cf_passer_{gen}",
            )
            st.caption("Defense optional — taggers usually own film")

            def _choice_opts(cur: str, options: list[str]) -> list[str]:
                out = [""] + [o for o in options if o]
                cur = str(cur or "")
                if cur and cur not in out:
                    out = [""] + [cur] + [o for o in out if o and o != cur]
                return out

            front_key = f"ql_cf_front_{gen}"
            front_ui = _choice_opts(str(draft.get("def_front") or ""), front_opts)
            if front_key not in st.session_state:
                st.session_state[front_key] = str(draft.get("def_front") or "")
            def_front = st.selectbox(
                "Front",
                front_ui,
                format_func=lambda v: v or "(skip)",
                key=front_key,
            )
            cov_key = f"ql_cf_cov_{gen}"
            cov_ui = _choice_opts(str(draft.get("coverage") or ""), cov_opts)
            if cov_key not in st.session_state:
                st.session_state[cov_key] = str(draft.get("coverage") or "")
            coverage = st.selectbox(
                "Coverage",
                cov_ui,
                format_func=lambda v: v or "(skip)",
                key=cov_key,
            )
            blitz_key = f"ql_cf_blitz_{gen}"
            blitz_ui = ["", "No", "Yes"]
            cur_blitz = str(draft.get("blitz") or "")
            if cur_blitz not in {"Yes", "No"}:
                cur_blitz = ""
            if blitz_key not in st.session_state:
                st.session_state[blitz_key] = cur_blitz
            blitz = st.selectbox(
                "Blitz",
                blitz_ui,
                format_func=lambda v: v or "(skip)",
                key=blitz_key,
            )
    else:
        formation = str(draft.get("formation") or "")
        variant = str(draft.get("variant") or "")
        motion = str(draft.get("motion") or "")
        run_tag = str(draft.get("run_tag") or "")
        pass_tag = str(draft.get("pass_tag") or "")
        play_type = str(draft.get("play_type") or "run")
        if play_type == "rpo":
            play_type = "run"
        pass_player = str(draft.get("pass_player") or "")
        def_front = str(draft.get("def_front") or "")
        coverage = str(draft.get("coverage") or "")
        blitz = str(draft.get("blitz") or "")

    b1, b2, b3 = st.columns(3)
    if b1.button(
        "Confirm LOG ▶", type="primary", use_container_width=True, key=f"ql_cf_ok_{gen}"
    ):
        warns = _ql_commit_phrase_draft(
            draft,
            opponent=opponent,
            half=int(half),
            unit=unit,
            formation=formation,
            variant=variant,
            motion=motion,
            run_tag=run_tag,
            pass_tag=pass_tag,
            play_type=str(play_type),
            result=str(result),
            yards=yards,
            ball_player=str(ball_player or ""),
            pass_player=str(pass_player or ""),
            def_front=def_front,
            coverage=coverage,
            blitz=blitz,
        )
        if warns and any("Need a formation" in w for w in warns):
            st.error("Need a formation or run/pass tag — open Edit call details.")
            return True
        _ql_rerun()
    if b2.button("Cancel", use_container_width=True, key=f"ql_cf_cancel_{gen}"):
        st.session_state.pop("ql_confirm_draft", None)
        _clear_phrase_confirm_widgets()
        _ql_rerun()
    if b3.button("Edit phrase", use_container_width=True, key=f"ql_cf_edit_{gen}"):
        st.session_state.pop("ql_confirm_draft", None)
        _clear_phrase_confirm_widgets()
        _ql_rerun()
    return True


def _render_quick_log_wizard(
    *,
    opponent: str,
    half: int,
    unit: str,
    offense_df: pd.DataFrame,
    live_logs: pd.DataFrame,
    form_opts: list[str],
    play_opts: list[str],
    motion_opts: list[str],
    front_opts: list[str],
    cov_opts: list[str],
    plan_pins: list[str],
    booth_favs: dict,
    hide_situation: bool = False,
) -> None:
    """Phrase-first booth log with confirm; optional tap steps behind a toggle."""
    if "ql_step" not in st.session_state:
        st.session_state.ql_step = 0
    if "ql_play_type" not in st.session_state:
        st.session_state.ql_play_type = "run"
    if "ql_skip_defense" not in st.session_state:
        st.session_state.ql_skip_defense = True
    if "ql_booth_tempo" not in st.session_state:
        st.session_state.ql_booth_tempo = "Fast"
    for old, new in (
        ("lt_form", "ql_form"),
        ("lt_variant", "ql_variant"),
        ("lt_motion", "ql_motion"),
        ("lt_play", "ql_play"),
    ):
        if new not in st.session_state and st.session_state.get(old):
            st.session_state[new] = st.session_state.get(old)

    sit_note = st.session_state.pop("lt_situation_note", None)
    if sit_note:
        st.success(f"Next: {sit_note}")

    # Clear phrase box BEFORE the widget is created (Streamlit forbids mutating after)
    if st.session_state.pop("ql_clear_phrase_pending", False):
        st.session_state.ql_call_phrase = ""

    # Ensure favorites exist — soft prompt once if nearly empty
    if not (booth_favs.get("formations") or booth_favs.get("plays", {}).get("run")):
        st.info(
            "Favorites look empty. Open **Database → Offense tags → Merge season tags** "
            "to auto-load formations / motions / plays."
        )

    cur_down = int(st.session_state.get("lt_down") or 1)
    cur_dist = int(st.session_state.get("lt_dist_y") or 10)
    if "lt_ball_yard" not in st.session_state:
        st.session_state.lt_ball_yard = zone_default_ball_yard(
            st.session_state.get("lt_zone") or "midfield"
        )
    cur_ball = int(st.session_state.get("lt_ball_yard") or 45)
    cur_zone = ball_yard_to_zone(cur_ball)
    st.session_state.lt_zone = cur_zone

    # Confirm card replaces the phrase box until accepted/cancelled
    if _render_phrase_confirm_card(
        opponent=opponent,
        half=half,
        unit=unit,
        booth_favs=booth_favs,
        front_opts=front_opts,
        cov_opts=cov_opts,
    ):
        return

    if not hide_situation:
        st.markdown(
            f'<p class="live-situation">'
            f"{situation_label(cur_down, _yards_to_distance_bucket(cur_dist), cur_zone, ball_yard=cur_ball)}"
            f" · to-go {cur_dist}</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="mb-console-title">Call console</div>',
            unsafe_allow_html=True,
        )
    # GameCast lives on the Halftime report (drive map) — keep Log free of Plotly
    if "ql_booth_tempo" not in st.session_state:
        st.session_state.ql_booth_tempo = "Fast"
    with st.expander("Booth options", expanded=False):
        tempo = st.radio(
            "Tempo",
            ["Fast", "Confirm"],
            horizontal=True,
            key="ql_booth_tempo",
            help=(
                "Fast: Enter / LOG commits when the call is known "
                "(defaults Gain / 0 if yards not spoken). Confirm: always review first."
            ),
        )
    tempo = str(st.session_state.get("ql_booth_tempo") or "Fast")

    # Apply pending phrase fills before the form widget exists
    if st.session_state.pop("ql_same_phrase_pending", False):
        st.session_state.ql_call_phrase = str(st.session_state.get("ql_last_phrase") or "")

    def _open_phrase_confirm(draft: dict) -> None:
        st.session_state.ql_cf_gen = int(st.session_state.get("ql_cf_gen") or 0) + 1
        draft["_widget_gen"] = st.session_state.ql_cf_gen
        _clear_phrase_confirm_widgets()
        st.session_state.ql_confirm_draft = draft

    def _build_phrase_draft_from_box(raw_phrase: str) -> dict | None:
        raw = str(raw_phrase or "").strip()
        if not raw:
            st.session_state.lt_last_warnings = ["Type or dictate a snap first."]
            return None
        parsed = parse_live_phrase(
            raw,
            booth_favs,
            start_ball_yard=st.session_state.get("lt_ball_yard"),
        )
        draft = _ql_build_phrase_draft(raw, parsed, booth_favs)
        if not draft.get("formation") and not draft.get("play_call"):
            guess = draft.get("new_play_guess") or ""
            draft = {**draft, "play_call": guess, "play_is_new": True}
            if not guess:
                st.session_state.lt_last_warnings = [
                    "Nothing matched — type the play name on the confirm card, or merge favorites."
                ]
        return draft

    last_bits = str(st.session_state.get("ql_last_phrase") or "").strip()
    if last_bits:
        if st.button(
            f"Same as last · {last_bits[:48]}{'…' if len(last_bits) > 48 else ''}",
            key="ql_same_as_last",
            use_container_width=True,
        ):
            st.session_state.ql_same_phrase_pending = True
            _ql_rerun()

    # Enter submits LOG (form). Review / Clear are secondary submit buttons.
    with st.form("ql_phrase_form", clear_on_submit=False):
        phrase = st.text_input(
            "Say / type snap",
            key="ql_call_phrase",
            placeholder="Slot Dip Bash, gain of 8  ·  Enter = LOG",
            label_visibility="collapsed",
        )
        if tempo == "Fast":
            pc1, pc2, pc3 = st.columns([2.4, 1.4, 1])
            with pc1:
                log_clicked = st.form_submit_button(
                    "LOG ▶", type="primary", use_container_width=True
                )
            with pc2:
                review_clicked = st.form_submit_button("Review", use_container_width=True)
            with pc3:
                clear_clicked = st.form_submit_button("Clear", use_container_width=True)
        else:
            log_clicked = False
            pc1, pc2 = st.columns([3, 1])
            with pc1:
                review_clicked = st.form_submit_button(
                    "Review ▶", type="primary", use_container_width=True
                )
            with pc2:
                clear_clicked = st.form_submit_button("Clear", use_container_width=True)

    if log_clicked:
        draft = _build_phrase_draft_from_box(phrase)
        if draft is None:
            _ql_rerun()
        ok, reason = _ql_draft_ready_for_fast_log(draft)
        if ok:
            _ql_commit_phrase_draft(
                _ql_apply_fast_outcome_defaults(draft),
                opponent=opponent,
                half=int(half),
                unit=unit,
            )
            _ql_rerun()
        _open_phrase_confirm(draft)
        st.session_state.lt_last_warnings = [
            f"Opened review — {reason}." if reason else "Opened review."
        ]
        _ql_rerun()

    if review_clicked:
        draft = _build_phrase_draft_from_box(phrase)
        if draft is None:
            _ql_rerun()
        _open_phrase_confirm(draft)
        _ql_rerun()

    if clear_clicked:
        st.session_state.ql_clear_phrase_pending = True
        st.session_state.pop("ql_confirm_draft", None)
        _clear_phrase_confirm_widgets()
        _ql_rerun()

    with st.expander("Tap steps (optional)", expanded=False):
        show_steps = st.checkbox(
            "Show tap-through steps",
            value=False,
            key="ql_show_steps",
        )
    if not show_steps:
        return

    # Tap-through steps (optional path)
    if show_steps:
        step = int(st.session_state.get("ql_step") or 0)
        step = max(0, min(step, len(QL_STEPS) - 1))
        st.session_state.ql_step = step
        step_key = QL_STEPS[step][0]

        # Resolve current sticky call
        formation = _ql_resolve_piece("ql_form", typed_key="ql_form_typed", dd_key="ql_form_dd")
        variant = _ql_resolve_piece("ql_variant", typed_key="ql_variant_typed")
        if variant.lower() in {"base", "none", "(none)", "—", "no variant"}:
            variant = ""
        motion = _ql_resolve_piece("ql_motion", typed_key="ql_motion_typed", dd_key="ql_motion_dd")
        play_call = _ql_resolve_piece("ql_play", typed_key="ql_play_typed", dd_key="ql_play_dd")
        play_type = st.session_state.get("ql_play_type") or "run"
        if play_type not in PLAY_TYPES:
            play_type = "run"

        down = int(st.session_state.get("lt_down") or 1)
        distance_yards = int(st.session_state.get("lt_dist_y") or 10)
        field_zone = str(st.session_state.get("lt_zone") or "midfield")
        dist_bucket = _yards_to_distance_bucket(distance_yards)
        form_label = compose_formation_label(formation, variant)
        summary = (
            f"{situation_label(down, dist_bucket, field_zone)} · "
            f"{form_label or '—'} · {motion or 'no mot'} · {play_call or '—'}"
        )
        _ql_progress_bar(step, summary)

        form_list = list(booth_favs.get("formations") or [])
        if not form_list:
            form_list = favorite_tags(live_logs, "formation", opponent, learned_kind="formation", limit=8)
        var_list = variants_for_formation(booth_favs, formation)
        mot_list = list(booth_favs.get("motions") or [])
        if not mot_list:
            mot_list = favorite_tags(live_logs, "motion", opponent, learned_kind="motion", limit=8)

        # Jump links to any prior step
        jump_cols = st.columns(len(QL_STEPS))
        for i, (_, label) in enumerate(QL_STEPS):
            if jump_cols[i].button(label, key=f"ql_jump_{i}", use_container_width=True, disabled=(i == step)):
                st.session_state.ql_step = i
                st.rerun()

        if step_key == "situation":
            st.markdown("### 1 · Down / distance")
            if "lt_ball_yard" not in st.session_state:
                st.session_state.lt_ball_yard = zone_default_ball_yard(
                    st.session_state.get("lt_zone") or "midfield"
                )
            r1 = st.columns([1, 1, 1.4, 1])
            r1[0].selectbox("Down", [1, 2, 3, 4], key="lt_down")
            r1[1].number_input("To go", min_value=1, max_value=99, value=10, step=1, key="lt_dist_y")
            # Ball spot is source of truth; zone follows it after each play
            r1[2].number_input(
                "Ball (yards from own GL)",
                min_value=1,
                max_value=99,
                step=1,
                key="lt_ball_yard",
                help="Own 10 = 10 · Midfield = 50 · Opp 25 = 75. Zone updates from this.",
            )
            if r1[3].button("1st & 10", key="lt_reset_1st10", use_container_width=True):
                st.session_state.lt_situation_pending = {
                    "down": 1,
                    "distance_yards": 10,
                    "field_zone": ball_yard_to_zone(st.session_state.get("lt_ball_yard")),
                    "ball_yard": st.session_state.get("lt_ball_yard"),
                    "note": "Manual reset → 1st & 10",
                }
                st.rerun()
            down = int(st.session_state.get("lt_down") or 1)
            distance_yards = int(st.session_state.get("lt_dist_y") or 10)
            ball_yard = int(st.session_state.get("lt_ball_yard") or 45)
            field_zone = ball_yard_to_zone(ball_yard)
            st.session_state.lt_zone = field_zone
            dist_bucket = _yards_to_distance_bucket(distance_yards)
            st.markdown(
                f'<p class="live-situation">{unit} · '
                f'{situation_label(down, dist_bucket, field_zone, ball_yard=ball_yard)} '
                f'· to-go {distance_yards}</p>',
                unsafe_allow_html=True,
            )
            st.caption(
                f"Ball at **{format_ball_spot(ball_yard)}** → {ZONE_LABELS.get(field_zone, field_zone)}"
            )
            _ql_wizard_nav(step, next_label="Formation ▶")

        elif step_key == "formation":
            st.markdown("### 2 · Formation")
            st.caption("Tap a formation — advances automatically.")
            _favorite_chip_picker(
                "Formation",
                form_list,
                "ql_form",
                columns=3,
                clear_keys=["ql_form_typed", "ql_form_dd", "ql_form_dd_custom"],
                advance_step=_ql_step_index("variant"),
                key_prefix="wiz_",
            )
            with st.expander("Other formation", expanded=False):
                _select_or_type("Formation", form_opts, "ql_form_dd")
                typed = _ql_norm(st.session_state.get("ql_form_dd_custom"))
                if typed:
                    st.session_state.ql_form_typed = typed
            _ql_wizard_nav(step, can_next=bool(_ql_resolve_piece("ql_form", typed_key="ql_form_typed", dd_key="ql_form_dd")), next_label="Variant ▶")

        elif step_key == "variant":
            st.markdown("### 3 · Formation variant")
            st.caption("Base / no variant is standard. Only tap a variant when splits change (e.g. Bash).")
            _favorite_chip_picker(
                "Variant",
                var_list,
                "ql_variant",
                columns=3,
                allow_none=True,
                none_label="No variant",
                clear_keys=["ql_variant_typed"],
                advance_step=_ql_step_index("motion"),
                key_prefix="wiz_",
            )
            with st.expander("Other variant", expanded=False):
                st.text_input("Variant", key="ql_variant_typed", placeholder="e.g. Bash")
            _ql_wizard_nav(step, next_label="Motion ▶")

        elif step_key == "motion":
            st.markdown("### 4 · Motion")
            st.caption("None = no motion. Tap a motion when they move (e.g. Sooner).")
            _favorite_chip_picker(
                "Motion",
                mot_list,
                "ql_motion",
                columns=3,
                allow_none=True,
                none_label="No motion",
                clear_keys=["ql_motion_typed", "ql_motion_dd", "ql_motion_dd_custom"],
                advance_step=_ql_step_index("play"),
                key_prefix="wiz_",
            )
            with st.expander("Other motion", expanded=False):
                _select_or_type("Motion", motion_opts, "ql_motion_dd")
                typed = _ql_norm(st.session_state.get("ql_motion_dd_custom"))
                if typed:
                    st.session_state.ql_motion_typed = typed
            _ql_wizard_nav(step, next_label="Play ▶")

        elif step_key == "play":
            st.markdown("### 5 · Play call")
            play_type = st.radio(
                "Play type",
                PLAY_TYPES,
                format_func=lambda t: PLAY_TYPE_LABELS[t],
                horizontal=True,
                key="ql_play_type",
            )
            typed_plays = list((booth_favs.get("plays") or {}).get(play_type) or [])
            if not typed_plays and play_type == "run":
                typed_plays = favorite_tags(
                    live_logs, "play_call", opponent, pins=plan_pins, learned_kind="play_call", limit=10
                )
            _favorite_chip_picker(
                f"{PLAY_TYPE_LABELS[play_type]} plays",
                typed_plays,
                "ql_play",
                columns=3,
                clear_keys=["ql_play_typed", "ql_play_dd", "ql_play_dd_custom"],
                advance_step=_ql_step_index("result"),
                key_prefix="wiz_",
            )
            with st.expander("Other play", expanded=False):
                _select_or_type("Play call", play_opts, "ql_play_dd")
                typed = _ql_norm(st.session_state.get("ql_play_dd_custom"))
                if typed:
                    st.session_state.ql_play_typed = typed
            _ql_wizard_nav(
                step,
                can_next=bool(_ql_resolve_piece("ql_play", typed_key="ql_play_typed", dd_key="ql_play_dd")),
                next_label="Result ▶",
            )

        elif step_key == "result":
            st.markdown("### 6 · Result")
            formation = _ql_resolve_piece("ql_form", typed_key="ql_form_typed", dd_key="ql_form_dd")
            variant = _ql_resolve_piece("ql_variant", typed_key="ql_variant_typed")
            if variant.lower() in {"base", "none", "(none)", "—", "no variant"}:
                variant = ""
            motion = _ql_resolve_piece("ql_motion", typed_key="ql_motion_typed", dd_key="ql_motion_dd")
            play_call = _ql_resolve_piece("ql_play", typed_key="ql_play_typed", dd_key="ql_play_dd")
            play_type = st.session_state.get("ql_play_type") or "run"
            down = int(st.session_state.get("lt_down") or 1)
            distance_yards = int(st.session_state.get("lt_dist_y") or 10)
            field_zone = str(st.session_state.get("lt_zone") or "midfield")
            dist_bucket = _yards_to_distance_bucket(distance_yards)

            st.markdown(
                f"**Call:** {compose_formation_label(formation, variant) or '—'} · "
                f"{motion or 'no motion'} · {play_call or '—'}"
            )
            outcomes = [
                ("Inc", 0, "Incomplete"),
                ("0", 0, "No gain"),
                ("+1", 1, "Gain"),
                ("+2", 2, "Gain"),
                ("+3", 3, "Gain"),
                ("+4", 4, "Gain"),
                ("+5", 5, "Gain"),
                ("+7", 7, "Gain"),
                ("+10", 10, "Gain"),
                ("+15", 15, "Gain"),
                ("-1", -1, "Sack / TFL"),
                ("-3", -3, "Sack / TFL"),
                ("-5", -5, "Sack / TFL"),
                ("TD", max(1, int(distance_yards)), "TD"),
                ("TO", 0, "Turnover"),
                ("Pen+", 5, "Penalty"),
                ("Pen-", -5, "Penalty"),
            ]
            if "lt_gain" not in st.session_state:
                st.session_state.lt_gain = 0
            if "lt_result" not in st.session_state:
                st.session_state.lt_result = "Gain"

            ocols = st.columns(6)
            for i, (label, yds, res) in enumerate(outcomes):
                with ocols[i % 6]:
                    if st.button(label, key=f"wiz_out_{label}", use_container_width=True):
                        st.session_state.lt_gain = int(yds)
                        st.session_state.lt_result = res
                        st.session_state.ql_step = _ql_step_index("defense")
                        st.rerun()

            st.number_input("Yards (fine-tune)", step=1, key="lt_gain")
            st.selectbox(
                "Result (fine-tune)",
                ["Gain", "Incomplete", "No gain", "TD", "Turnover", "Penalty", "Sack / TFL", "Punt", "Other"],
                key="lt_result",
            )
            note = st.text_input("Note (optional)", key="lt_note_quick", placeholder="skip unless needed")
            st.session_state.ql_note = note

            b1, b2, b3 = st.columns(3)
            if b1.button("◀ Back", key="ql_res_back", use_container_width=True):
                st.session_state.ql_step = _ql_step_index("play")
                st.rerun()
            if b2.button("Skip defense → Log", key="ql_skip_def_log", use_container_width=True):
                if not formation and not play_call:
                    st.error("Need formation or play first.")
                else:
                    _commit_live_play(
                        opponent=opponent,
                        half=int(half),
                        unit=unit,
                        down=int(down),
                        distance_yards=int(distance_yards),
                        field_zone=field_zone,
                        dist_bucket=dist_bucket,
                        formation=formation,
                        formation_variant=variant,
                        play_call=play_call,
                        play_type=str(play_type),
                        motion=motion,
                        result=str(st.session_state.get("lt_result") or "Gain"),
                        yards_gained=int(st.session_state.get("lt_gain") or 0),
                        note=str(st.session_state.get("ql_note") or note or ""),
                        film_pending=True,
                    )
                    st.session_state.ql_step = 0
                    st.rerun()
            if b3.button("Defense ▶", type="primary", key="ql_to_def", use_container_width=True):
                st.session_state.ql_step = _ql_step_index("defense")
                st.rerun()

        elif step_key == "defense":
            st.markdown("### 7 · Defense tags")
            st.caption("Optional live — or skip and fill from Sky Coach later (Fill Film).")
            formation = _ql_resolve_piece("ql_form", typed_key="ql_form_typed", dd_key="ql_form_dd")
            variant = _ql_resolve_piece("ql_variant", typed_key="ql_variant_typed")
            if variant.lower() in {"base", "none", "(none)", "—", "no variant"}:
                variant = ""
            motion = _ql_resolve_piece("ql_motion", typed_key="ql_motion_typed", dd_key="ql_motion_dd")
            play_call = _ql_resolve_piece("ql_play", typed_key="ql_play_typed", dd_key="ql_play_dd")
            play_type = st.session_state.get("ql_play_type") or "run"
            down = int(st.session_state.get("lt_down") or 1)
            distance_yards = int(st.session_state.get("lt_dist_y") or 10)
            field_zone = str(st.session_state.get("lt_zone") or "midfield")
            dist_bucket = _yards_to_distance_bucket(distance_yards)
            result = str(st.session_state.get("lt_result") or "Gain")
            yards_gained = int(st.session_state.get("lt_gain") or 0)
            note = str(st.session_state.get("ql_note") or st.session_state.get("lt_note_quick") or "")

            st.markdown(
                f"**{compose_formation_label(formation, variant) or '—'} · {motion or 'no motion'} · "
                f"{play_call or '—'}** → {result} ({yards_gained:+d})"
            )

            d1, d2, d3 = st.columns(3)
            with d1:
                def_front = _select_or_type("Front", front_opts, "ql_front")
            with d2:
                coverage = _select_or_type("Coverage", cov_opts, "ql_cov")
            with d3:
                if "ql_blitz" not in st.session_state:
                    st.session_state.ql_blitz = "No"
                blitz = st.radio("Blitz", ["No", "Yes"], horizontal=True, key="ql_blitz")

            film_pending = not (def_front or coverage or str(blitz).lower() in {"yes", "no"})
            # blitz always yes/no from radio — film pending if front+cov empty
            film_pending = not (bool(def_front) and bool(coverage))

            b1, b2 = st.columns(2)
            if b1.button("◀ Result", key="ql_def_back", use_container_width=True):
                st.session_state.ql_step = _ql_step_index("result")
                st.rerun()
            if b2.button("LOG PLAY ▶", type="primary", key="ql_def_log", use_container_width=True):
                if not formation and not play_call:
                    st.error("Need formation or play first.")
                else:
                    _commit_live_play(
                        opponent=opponent,
                        half=int(half),
                        unit=unit,
                        down=int(down),
                        distance_yards=int(distance_yards),
                        field_zone=field_zone,
                        dist_bucket=dist_bucket,
                        formation=formation,
                        formation_variant=variant,
                        play_call=play_call,
                        play_type=str(play_type),
                        motion=motion,
                        def_front=def_front,
                        coverage=coverage,
                        blitz=blitz,
                        result=result,
                        yards_gained=yards_gained,
                        note=note,
                        film_pending=film_pending,
                    )
                    st.session_state.ql_step = 0
                    st.session_state.ql_front = ""
                    st.session_state.ql_cov = ""
                    st.session_state.ql_blitz = "No"
                    st.rerun()
            if st.button("Skip defense → Log (film later)", key="ql_def_skip", use_container_width=True):
                _commit_live_play(
                    opponent=opponent,
                    half=int(half),
                    unit=unit,
                    down=int(down),
                    distance_yards=int(distance_yards),
                    field_zone=field_zone,
                    dist_bucket=dist_bucket,
                    formation=formation,
                    formation_variant=variant,
                    play_call=play_call,
                    play_type=str(play_type),
                    motion=motion,
                    result=result,
                    yards_gained=yards_gained,
                    note=note,
                    film_pending=True,
                )
                st.session_state.ql_step = 0
                st.rerun()

def _inject_main_booth_css() -> None:
    """Professional Main booth chrome — dual-pane console look."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600;700&display=swap');

        /* —— Main booth shell —— */
        html, body, [data-testid="stAppViewContainer"],
        [data-testid="stMain"], .stApp {
            font-family: "IBM Plex Sans", "Segoe UI", sans-serif !important;
        }
        [data-testid="stHeader"] {
            background: transparent !important;
        }
        [data-testid="stToolbar"] {
            right: 0.75rem !important;
            top: 0.35rem !important;
        }
        [data-testid="stMainBlockContainer"] {
            padding-top: 0.35rem !important;
            padding-bottom: 1.25rem !important;
            max-width: 1240px !important;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {
            gap: 0.45rem !important;
        }
        [data-testid="stHorizontalBlock"] {
            gap: 0.85rem !important;
            align-items: flex-start !important;
        }
        div[data-testid="stCaptionContainer"] p {
            color: #5a6b62 !important;
            font-size: 0.82rem !important;
        }

        /* App bar */
        .mb-appbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            padding: 0.7rem 1rem;
            margin: 0 0 0.65rem 0;
            background: #0F2419;
            color: #F2F7F4;
            border-radius: 12px;
            border: 1px solid #1B4332;
        }
        .mb-appbar-brand {
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            min-width: 0;
        }
        .mb-appbar-brand .mb-name {
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #95D5B2;
        }
        .mb-appbar-brand .mb-match {
            font-size: 1.15rem;
            font-weight: 700;
            letter-spacing: -0.01em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .mb-appbar-meta {
            display: flex;
            align-items: center;
            gap: 0.45rem;
            flex-shrink: 0;
        }
        .mb-pill {
            display: inline-flex;
            align-items: center;
            padding: 0.28rem 0.65rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            background: #1B4332;
            color: #D8F3DC;
            border: 1px solid #2D6A4F;
        }
        .mb-pill.warn {
            background: #3D2E0F;
            color: #FFE8A3;
            border-color: #C9A227;
        }
        .mb-pill.ok {
            background: #143528;
            color: #95D5B2;
            border-color: #40916C;
        }

        /* Panels */
        .mb-panel {
            background: #FFFFFF;
            border: 1px solid #D5E0D9;
            border-radius: 12px;
            padding: 0.85rem 0.95rem 0.95rem;
            margin: 0 0 0.55rem 0;
        }
        .mb-panel-label, .mb-panel-label {
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #6B7C72;
            margin: 0 0 0.55rem 0;
        }
        .mb-console-title {
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #6B7C72;
            margin: 0 0 0.35rem 0;
        }
        /* Dual-pane columns look like app panels */
        div[data-testid="stHorizontalBlock"]:has(.mb-console-title) > div[data-testid="stColumn"] {
            background: #FFFFFF;
            border: 1px solid #D5E0D9;
            border-radius: 14px;
            padding: 0.85rem 0.95rem 1rem;
        }
        div[data-testid="stHorizontalBlock"]:has(.mb-board) > div[data-testid="stColumn"] {
            background: #FFFFFF;
            border: 1px solid #D5E0D9;
            border-radius: 14px;
            padding: 0.85rem 0.95rem 1rem;
        }
        /* LOG form primary = big commit */
        div[data-testid="stForm"] div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stForm"] button[data-testid="baseButton-primaryFormSubmit"] {
            min-height: 3.25rem !important;
            font-size: 1.1rem !important;
            font-weight: 800 !important;
            letter-spacing: 0.06em !important;
            text-transform: uppercase !important;
            background: #1B4332 !important;
            border-color: #1B4332 !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        div[data-testid="stForm"] div[data-testid="stButton"] > button[kind="primary"] *,
        div[data-testid="stForm"] button[data-testid="baseButton-primaryFormSubmit"] * {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        /* Soft page wash */
        [data-testid="stAppViewContainer"] > .main {
            background: #F3F6F4;
        }
        [data-testid="stMainBlockContainer"] {
            background: transparent;
        }

        /* Situation board */
        .mb-board {
            background: #0F2419 !important;
            border: 1px solid #1B4332;
            border-radius: 12px;
            padding: 0.85rem 0.9rem 0.95rem;
            margin: 0 0 0.55rem 0;
            color: #F2F7F4 !important;
        }
        .mb-board,
        .mb-board p,
        .mb-board span,
        .mb-board div {
            color: #F2F7F4 !important;
            -webkit-text-fill-color: #F2F7F4 !important;
        }
        .mb-board-label {
            font-size: 0.68rem;
            font-weight: 700;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: #95D5B2 !important;
            -webkit-text-fill-color: #95D5B2 !important;
            margin: 0 0 0.35rem 0;
        }
        .mb-board-sit {
            font-family: "IBM Plex Mono", ui-monospace, monospace;
            font-size: 1.55rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            line-height: 1.2;
            margin: 0;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        .mb-board-sub {
            margin: 0.35rem 0 0 0;
            font-size: 0.88rem;
            color: #C5D5CC !important;
            -webkit-text-fill-color: #C5D5CC !important;
            font-weight: 500;
        }
        /* Beat stMarkdownContainer p { dark } when board is embedded in markdown */
        [data-testid="stMarkdownContainer"] .mb-board p.mb-board-sit,
        [data-testid="stMarkdownContainer"] p.mb-board-sit {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        [data-testid="stMarkdownContainer"] .mb-board p.mb-board-sub,
        [data-testid="stMarkdownContainer"] p.mb-board-sub {
            color: #C5D5CC !important;
            -webkit-text-fill-color: #C5D5CC !important;
        }
        [data-testid="stMarkdownContainer"] .mb-board .mb-board-label {
            color: #95D5B2 !important;
            -webkit-text-fill-color: #95D5B2 !important;
        }

        /* Drive chip */
        .mb-drive {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            padding: 0.55rem 0.7rem;
            margin: 0 0 0.45rem 0;
            background: #F3F7F4;
            border: 1px solid #D5E0D9;
            border-radius: 10px;
            font-weight: 700;
            font-size: 0.95rem;
            color: #1B4332;
        }
        .mb-drive.open {
            border-color: #40916C;
            background: #E7F5EC;
        }
        .mb-drive .mb-drive-state {
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #6B7C72;
        }
        .mb-drive.open .mb-drive-state { color: #2D6A4F; }

        /* Last play card */
        .mb-last {
            background: #F7FAF8;
            border: 1px solid #D5E0D9;
            border-radius: 10px;
            padding: 0.65rem 0.75rem;
            margin: 0.15rem 0 0.35rem 0;
        }
        .mb-last-call {
            font-size: 1.05rem;
            font-weight: 700;
            color: #14201a;
            margin: 0 0 0.2rem 0;
        }
        .mb-last-meta, .mb-last-meta {
            font-family: "IBM Plex Mono", ui-monospace, monospace;
            font-size: 0.88rem;
            font-weight: 600;
            color: #2D6A4F;
            margin: 0;
        }
        .mb-last-phrase {
            margin: 0.35rem 0 0 0;
            font-size: 0.8rem;
            color: #6B7C72;
        }
        .mb-empty {
            color: #8A9A91;
            font-size: 0.88rem;
            margin: 0.25rem 0;
        }

        /* Controls */
        div[data-testid="stButton"] > button {
            min-height: 2.55rem !important;
            font-size: 0.95rem !important;
            font-weight: 650 !important;
            border-radius: 10px !important;
            border: 1px solid #C9D6CE !important;
            letter-spacing: 0.01em;
        }
        div[data-testid="stButton"] > button[kind="primary"],
        div[data-testid="stButton"] > button[data-testid="baseButton-primary"] {
            background: #1B4332 !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
            border-color: #1B4332 !important;
            min-height: 3.1rem !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            letter-spacing: 0.04em;
        }
        div[data-testid="stButton"] > button[kind="primary"] *,
        div[data-testid="stButton"] > button[data-testid="baseButton-primary"] * {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        div[data-testid="stButton"] > button[kind="primary"]:hover,
        div[data-testid="stButton"] > button[data-testid="baseButton-primary"]:hover {
            background: #2D6A4F !important;
            border-color: #2D6A4F !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        div[data-testid="stButton"] > button[kind="primary"]:hover *,
        div[data-testid="stButton"] > button[data-testid="baseButton-primary"]:hover * {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        div[data-testid="stTextInput"] input {
            min-height: 3.15rem !important;
            font-size: 1.12rem !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            border: 1.5px solid #B7C9BE !important;
            background: #FFFFFF !important;
        }
        div[data-testid="stTextInput"] input:focus {
            border-color: #1B4332 !important;
            box-shadow: 0 0 0 2px rgba(27, 67, 50, 0.18) !important;
        }
        div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        div[data-testid="stNumberInput"] input {
            min-height: 2.45rem !important;
            font-size: 0.95rem !important;
            border-radius: 8px !important;
        }
        div[data-testid="stExpander"] {
            background: #F7FAF8 !important;
            border: 1px solid #D5E0D9 !important;
            border-radius: 10px !important;
        }
        div[data-testid="stExpander"] details summary p {
            font-weight: 600 !important;
            color: #1B4332 !important;
        }
        .main-dual-rail {
            border-left: none !important;
            padding-left: 0 !important;
        }
        /* Soften default Live Track title when app bar present */
        .live-title { display: none !important; }
        hr { border: none !important; border-top: 1px solid #E2EBE5 !important; margin: 0.55rem 0 !important; }

        /* LAST — white text on green primary controls (booth CSS loads after inject_styles) */
        button[kind="primary"],
        button[kind="primary"] *,
        button[data-testid*="primary"],
        button[data-testid*="primary"] *,
        button[data-testid*="Primary"],
        button[data-testid*="Primary"] *,
        [data-testid="stDownloadButton"] button,
        [data-testid="stDownloadButton"] button *,
        [data-testid="stFormSubmitButton"] button,
        [data-testid="stFormSubmitButton"] button *,
        [data-testid="baseButton-primary"],
        [data-testid="baseButton-primary"] *,
        [data-testid="baseButton-primaryFormSubmit"],
        [data-testid="baseButton-primaryFormSubmit"] *,
        .stTabs [aria-selected="true"],
        .stTabs [aria-selected="true"] * {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        /* Situation board on dark green — light text wins over markdown p dark */
        .mb-board,
        .mb-board *,
        [data-testid="stMarkdownContainer"] .mb-board,
        [data-testid="stMarkdownContainer"] .mb-board * {
            color: #F2F7F4 !important;
            -webkit-text-fill-color: #F2F7F4 !important;
        }
        .mb-board-label,
        [data-testid="stMarkdownContainer"] .mb-board-label {
            color: #95D5B2 !important;
            -webkit-text-fill-color: #95D5B2 !important;
        }
        p.mb-board-sit,
        .mb-board-sit,
        [data-testid="stMarkdownContainer"] p.mb-board-sit {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }
        p.mb-board-sub,
        .mb-board-sub,
        [data-testid="stMarkdownContainer"] p.mb-board-sub {
            color: #C5D5CC !important;
            -webkit-text-fill-color: #C5D5CC !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_main_app_bar(
    opponent: str,
    *,
    half: int = 1,
    pending_n: int = 0,
    drive_id: int | None = None,
    play_n: int | None = None,
) -> None:
    """Top chrome for Main booth — match context at a glance."""
    half_lbl = f"H{int(half)}"
    drive_bits = []
    if drive_id is not None:
        drive_bits.append(f"D{int(drive_id)}")
    if play_n is not None:
        drive_bits.append(f"P{int(play_n)}")
    drive_pill = " · ".join(drive_bits) if drive_bits else "READY"
    film_cls = "mb-pill warn" if pending_n else "mb-pill ok"
    film_txt = f"FILM {pending_n}" if pending_n else "FILM OK"
    st.markdown(
        f"""
        <div class="mb-appbar">
          <div class="mb-appbar-brand">
            <div class="mb-name">Live Track · Main</div>
            <div class="mb-match">vs {opponent}</div>
          </div>
          <div class="mb-appbar-meta">
            <span class="mb-pill">{half_lbl}</span>
            <span class="mb-pill">{drive_pill}</span>
            <span class="{film_cls}">{film_txt}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_main_dual_rail(
    opponent: str,
    live_logs: pd.DataFrame | None,
    *,
    pending_n: int = 0,
    can_control_snap: bool = True,
) -> None:
    """Main layout C — right pane: scoreboard situation, drive, last play."""
    if "lt_ball_yard" not in st.session_state:
        st.session_state.lt_ball_yard = zone_default_ball_yard(
            st.session_state.get("lt_zone") or "midfield"
        )

    # Scoreboard first (session values), then edit controls
    ball_yard = int(st.session_state.get("lt_ball_yard") or 45)
    field_zone = ball_yard_to_zone(ball_yard)
    st.session_state.lt_zone = field_zone
    down = int(st.session_state.get("lt_down") or 1)
    distance_yards = int(st.session_state.get("lt_dist_y") or 10)
    dist_bucket = _yards_to_distance_bucket(distance_yards)
    sit = situation_label(down, dist_bucket, field_zone, ball_yard=ball_yard)
    spot = format_ball_spot(ball_yard)
    zone_lbl = ZONE_LABELS.get(field_zone, field_zone)

    st.markdown(
        f"""
        <div class="mb-board" style="color:#F2F7F4 !important;-webkit-text-fill-color:#F2F7F4 !important;">
          <div class="mb-board-label" style="color:#95D5B2 !important;-webkit-text-fill-color:#95D5B2 !important;">On the field</div>
          <p class="mb-board-sit" style="color:#FFFFFF !important;-webkit-text-fill-color:#FFFFFF !important;">{sit}</p>
          <p class="mb-board-sub" style="color:#C5D5CC !important;-webkit-text-fill-color:#C5D5CC !important;">{spot} · {zone_lbl} · to-go {distance_yards}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="mb-panel-label">Adjust</div>', unsafe_allow_html=True)
    s1, s2 = st.columns(2)
    with s1:
        st.selectbox("Down", [1, 2, 3, 4], key="lt_down")
    with s2:
        st.number_input(
            "To go",
            min_value=1,
            max_value=99,
            step=1,
            key="lt_dist_y",
        )
    st.number_input(
        "Ball (from own GL)",
        min_value=1,
        max_value=99,
        step=1,
        key="lt_ball_yard",
        help="Own 10 = 10 · Midfield = 50 · Opp 25 = 75",
    )
    if st.button("Reset · 1st & 10", key="lt_rail_1st10", use_container_width=True):
        by = int(st.session_state.get("lt_ball_yard") or ball_yard)
        st.session_state.lt_situation_pending = {
            "down": 1,
            "distance_yards": 10,
            "field_zone": ball_yard_to_zone(by),
            "ball_yard": by,
            "note": "Manual reset → 1st & 10",
        }
        st.rerun()

    dstate = load_drive_state()
    active_did = current_drive_id(opponent)
    can_undo = bool(dstate.get("undo_stack"))
    play_n = None
    try:
        from booth_snaps import load_booth_snap

        snap = load_booth_snap()
        if active_did is not None and snap.get("drive_id") == int(active_did):
            play_n = int(snap.get("play_n") or 1)
    except Exception:
        pass

    if active_did is not None:
        drive_main = f"Drive #{active_did}" + (f" · Play #{play_n}" if play_n else "")
        drive_state = "LIVE"
        drive_cls = "mb-drive open"
    else:
        drive_main = "No drive open"
        drive_state = "LOG STARTS ONE"
        drive_cls = "mb-drive"
    st.markdown(
        f'<div class="{drive_cls}"><span>{drive_main}</span>'
        f'<span class="mb-drive-state">{drive_state}</span></div>',
        unsafe_allow_html=True,
    )
    b1, b2, b3 = st.columns(3)
    if b1.button(
        "Start",
        use_container_width=True,
        key="lt_start_drive",
        disabled=active_did is not None,
        help="Optional — first LOG also starts a drive.",
    ):
        st.success(f"Drive #{start_drive(opponent)} started.")
        st.rerun()
    if b2.button(
        "End",
        use_container_width=True,
        key="lt_end_fill",
        disabled=active_did is None,
        help="Ends the drive. Taggers keep filming.",
    ):
        ended = end_drive()
        if ended is not None:
            st.session_state.ff_drive_filter = str(ended)
            st.session_state["lt_end_drive_note"] = (
                f"Drive #{ended} ended · taggers keep filming"
            )
        st.rerun()
    if b3.button(
        "Undo",
        use_container_width=True,
        key="lt_undo_drive",
        disabled=not can_undo,
    ):
        entry = undo_drive_action()
        if entry:
            st.success(f"Undid {entry.get('action')}.")
        st.rerun()
    end_note = st.session_state.pop("lt_end_drive_note", None)
    if end_note:
        st.caption(end_note)

    if pending_n:
        st.markdown(
            f'<span class="mb-pill warn">Film pending · {pending_n}</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="mb-pill ok">Film clear</span>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<div class="mb-panel-label" style="margin-top:0.75rem">Last play</div>',
        unsafe_allow_html=True,
    )
    last_phrase = str(st.session_state.get("ql_last_phrase") or "").strip()
    last_row = None
    if live_logs is not None and not live_logs.empty:
        try:
            sub = live_logs.copy()
            if "opponent" in sub.columns:
                sub = sub[
                    sub["opponent"].astype(str).str.strip().str.lower()
                    == str(opponent).strip().lower()
                ]
            if not sub.empty:
                last_row = sub.reset_index(drop=True).iloc[-1]
        except Exception:
            last_row = None
    if last_row is not None:
        call = str(
            last_row.get("play_call")
            or last_row.get("play_call")
            or last_row.get("call")
            or "—"
        )
        yds = last_row.get("yards_gained")
        if yds is None or (isinstance(yds, float) and pd.isna(yds)):
            yds = last_row.get("yards_gained")
        try:
            yds_s = f"{int(yds):+d}" if yds is not None and str(yds).strip() != "" else "—"
        except (TypeError, ValueError):
            yds_s = "—"
        front = str(last_row.get("def_front") or "").strip()
        cov = str(last_row.get("coverage") or "").strip()
        look = f"{front} / {cov}" if front or cov else "—"
        phrase_html = (
            f'<p class="mb-last-phrase">{last_phrase[:90]}</p>' if last_phrase else ""
        )
        st.markdown(
            f"""
            <div class="mb-last">
              <p class="mb-last-call">{call}</p>
              <p class="mb-last-meta">{yds_s} yd · {look}</p>
              {phrase_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif last_phrase:
        st.markdown(
            f'<div class="mb-last"><p class="mb-last-phrase">{last_phrase[:90]}</p></div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<p class="mb-empty">No plays logged yet</p>', unsafe_allow_html=True)

    if can_control_snap and active_did is not None:
        with st.expander("Catch-up / shared Play #", expanded=False):
            _render_shared_snap_bar(opponent, can_control=True, key_prefix="main")


def _live_track_log_screen(
    opponent: str,
    offense_df: pd.DataFrame,
    defense_df: pd.DataFrame,
    live_logs: pd.DataFrame,
    *,
    quick: bool = True,
    dual_pane: bool = False,
) -> None:
    """Booth logger — one-handed Quick Log (pace) or Full tags.

    dual_pane=True (layout C): phrase/confirm only — situation lives on the right rail.
    """
    from mesh_engine import load_game_plan, pin_names

    _apply_pending_live_tags()
    warns = st.session_state.pop("lt_last_warnings", None)
    if warns:
        st.success(" · ".join(warns))

    on_field = get_on_field()
    if not on_field:
        st.caption("No lineup — open **Lineup** → Load starters.")

    half = int(st.session_state.get("lt_half") or 1)
    unit = "Offense"
    st.session_state.lt_unit = "Offense"

    live_form = live_logs["formation"] if live_logs is not None and "formation" in getattr(live_logs, "columns", []) else pd.Series(dtype=str)
    live_play = live_logs["play_call"] if live_logs is not None and "play_call" in getattr(live_logs, "columns", []) else pd.Series(dtype=str)
    live_motion = live_logs["motion"] if live_logs is not None and "motion" in getattr(live_logs, "columns", []) else pd.Series(dtype=str)
    live_front = live_logs["def_front"] if live_logs is not None and "def_front" in getattr(live_logs, "columns", []) else pd.Series(dtype=str)
    live_cov = live_logs["coverage"] if live_logs is not None and "coverage" in getattr(live_logs, "columns", []) else pd.Series(dtype=str)

    # Season uniques cached by DB mtime; live-log merge stays cheap
    form_opts = _merge_tag_options(
        _season_tag_opts("formation"),
        live_form,
        kind="formation",
    )
    play_opts = _merge_tag_options(
        _season_tag_opts("play_call"),
        live_play,
        kind="play_call",
    )
    motion_opts = _merge_tag_options(
        _season_tag_opts("motion"),
        live_motion,
        kind="motion",
    )
    for m in _hudl_motion_options():
        if m not in motion_opts:
            motion_opts.append(m)
    motion_opts.sort(key=str.upper)
    front_opts = _merge_film_tag_options(
        _season_tag_opts("def_front"),
        live_front,
        kind="def_front",
    )
    cov_opts = _merge_film_tag_options(
        _season_tag_opts("coverage"),
        live_cov,
        kind="coverage",
    )

    plan = load_game_plan(opponent)
    plan_pins = pin_names(plan, "offense" if unit == "Offense" else "defense")
    booth_favs = load_live_favorites()

    if quick:
        _render_quick_log_wizard(
            opponent=opponent,
            half=int(half) if half is not None else 1,
            unit=unit,
            offense_df=offense_df,
            live_logs=live_logs,
            form_opts=form_opts,
            play_opts=play_opts,
            motion_opts=motion_opts,
            front_opts=front_opts,
            cov_opts=cov_opts,
            plan_pins=plan_pins,
            booth_favs=booth_favs,
            hide_situation=bool(dual_pane),
        )
        if not dual_pane:
            with st.expander("Tonight’s log", expanded=False):
                _render_live_log_tail(opponent, live_logs)
        return

    sit_note = st.session_state.pop("lt_situation_note", None)
    if sit_note:
        st.success(f"Next: {sit_note}")

    if "lt_ball_yard" not in st.session_state:
        st.session_state.lt_ball_yard = zone_default_ball_yard(
            st.session_state.get("lt_zone") or "midfield"
        )
    r1 = st.columns([1, 1, 1.4, 1])
    down = r1[0].selectbox("Down", [1, 2, 3, 4], key="lt_down")
    distance_yards = r1[1].number_input(
        "To go",
        min_value=1,
        max_value=99,
        value=10,
        step=1,
        key="lt_dist_y",
    )
    r1[2].number_input(
        "Ball (from own GL)",
        min_value=1,
        max_value=99,
        step=1,
        key="lt_ball_yard",
        help="Own 10 = 10 · Midfield = 50 · Opp 25 = 75",
    )
    ball_yard = int(st.session_state.get("lt_ball_yard") or 45)
    field_zone = ball_yard_to_zone(ball_yard)
    st.session_state.lt_zone = field_zone
    if r1[3].button("1st & 10", key="lt_reset_1st10", use_container_width=True):
        st.session_state.lt_situation_pending = {
            "down": 1,
            "distance_yards": 10,
            "field_zone": field_zone,
            "ball_yard": ball_yard,
            "note": "Manual reset → 1st & 10",
        }
        st.rerun()

    dist_bucket = _yards_to_distance_bucket(distance_yards)
    st.markdown(
        f'<p class="live-situation">{unit} · '
        f'{situation_label(int(down), dist_bucket, field_zone, ball_yard=ball_yard)} '
        f'· to-go {int(distance_yards)}</p>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Ball **{format_ball_spot(ball_yard)}** → {ZONE_LABELS.get(field_zone, field_zone)}"
    )

    variant = ""
    play_type = ""
    c_form, c_play = st.columns(2)
    with c_form:
        formation = _select_or_type("Formation", form_opts, "lt_form")
    with c_play:
        play_call = _select_or_type("Play call", play_opts, "lt_play")

    if "lt_gain" not in st.session_state:
        st.session_state.lt_gain = 0
    if "lt_result" not in st.session_state:
        st.session_state.lt_result = "Gain"
    st.caption("Gain (yards)")
    gain_presets = [-10, -5, -3, -1, 0, 1, 2, 3, 4, 5, 7, 10, 15, 20]
    gcols = st.columns(len(gain_presets))
    for i, g in enumerate(gain_presets):
        label = f"{g:+d}" if g != 0 else "0"
        if gcols[i].button(label, key=f"lt_gain_chip_{g}", use_container_width=True):
            st.session_state.lt_gain = int(g)
            if g > 0 and st.session_state.get("lt_result") in {
                "No gain",
                "Incomplete",
                "Sack / TFL",
            }:
                st.session_state.lt_result = "Gain"
            elif g < 0 and st.session_state.get("lt_result") == "Gain":
                st.session_state.lt_result = "Sack / TFL"
            st.rerun()
    yards_gained = st.number_input(
        "Gain (yards)",
        step=1,
        key="lt_gain",
        label_visibility="collapsed",
        help="Negatives = loss / penalty yards.",
    )
    result = _quick_chip_row(
        "Result",
        [
            "Gain",
            "Incomplete",
            "No gain",
            "TD",
            "Turnover",
            "Penalty",
            "Sack / TFL",
            "Punt",
        ],
        "lt_result",
        columns=4,
    )
    st.markdown("##### Film tags (optional live)")
    r2 = st.columns(2)
    with r2[0]:
        motion = _select_or_type("Motion", motion_opts, "lt_motion")
        def_front = _select_or_type("Front", front_opts, "lt_front")
    with r2[1]:
        coverage = _select_or_type("Coverage", cov_opts, "lt_cov")
        if "lt_blitz" not in st.session_state:
            st.session_state.lt_blitz = "No"
        blitz = st.radio("Blitz", ["No", "Yes"], horizontal=True, key="lt_blitz")
    note = st.text_input("Note (optional)", key="lt_note")

    if st.button("Log play (full tags)", type="primary", use_container_width=True, key="lt_submit"):
        if not formation and not play_call:
            st.error("Set formation or play call first.")
        else:
            _commit_live_play(
                opponent=opponent,
                half=int(half),
                unit=unit,
                down=int(down),
                distance_yards=int(distance_yards),
                field_zone=field_zone,
                dist_bucket=dist_bucket,
                formation=formation,
                formation_variant="",
                play_call=play_call,
                play_type="",
                result=str(result),
                yards_gained=int(yards_gained),
                motion=motion,
                def_front=def_front,
                coverage=coverage,
                blitz=blitz,
                note=note,
                film_pending=False,
            )
            st.rerun()

    _render_live_log_tail(opponent, live_logs)


def _live_track_field_screen(opponent: str, live_logs: pd.DataFrame) -> None:
    """Offense lineup sheet — load starters, verbal subs, depth chart."""
    st.caption(
        "Load starters once, then sub by voice or dropdown. "
        "OL is saved for grading but hidden here and on GameCast. "
        "Roster / starters: **Database**."
    )

    roster = load_roster()
    if not roster:
        st.info("No players yet — add them under **Database → Players**.")
        return

    # --- Verbal sub (one row) ---
    if st.session_state.pop("lt_clear_sub", False):
        st.session_state.lt_sub_phrase = ""
    sc1, sc2 = st.columns([3.4, 1])
    sub_phrase = sc1.text_input(
        "Sub phrase",
        key="lt_sub_phrase",
        placeholder='sub Cheatham for Tyse at WR',
        label_visibility="collapsed",
    )
    if sc2.button("SUB ▶", type="primary", use_container_width=True, key="lt_sub_btn"):
        result = apply_sub_phrase(sub_phrase)
        if result.get("ok"):
            st.session_state.lt_clear_sub = True
            st.success(result.get("message"))
            st.rerun()
        else:
            st.error(result.get("error") or "Could not sub.")

    slots = get_formation_slots()
    with st.expander("Package extras (WR/RB/TE)", expanded=False):
        p1, p2, p3 = st.columns(3)
        p1.selectbox(
            "Extra WRs",
            [0, 1, 2],
            format_func=lambda n: {0: "0 (3 total)", 1: "+1 (4)", 2: "+2 (5)"}[n],
            key="lt_extra_wr",
        )
        p2.selectbox(
            "Extra RBs",
            [0, 1, 2],
            format_func=lambda n: {0: "0 (1 total)", 1: "+1 (2)", 2: "+2 (3)"}[n],
            key="lt_extra_rb",
        )
        p3.selectbox(
            "Extra TEs",
            [0, 1, 2],
            format_func=lambda n: {0: "0 (1 total)", 1: "+1 (2)", 2: "+2 (3)"}[n],
            key="lt_extra_te",
        )
        # Keep 6th OL off the main package UI; optional via OL expander
        if "lt_extra_ol" not in st.session_state:
            st.session_state.lt_extra_ol = 0
    pruned = _prune_slots_to_active(slots)
    if pruned != slots:
        set_formation_slots(pruned)
        _bump_slot_widgets()
        st.rerun()
    slots = pruned

    side = "Offense"
    b1, b2, b3 = st.columns(3)
    if b1.button("Load starters", type="primary", use_container_width=True, key="lt_starters_field"):
        set_formation_slots(_starters_for_side(roster, side))
        _bump_slot_widgets()
        st.rerun()
    if b2.button("Save starters", use_container_width=True, key="lt_save_starters"):
        save_starters({"offense": get_formation_slots()})
        st.success("Starters saved.")
        st.rerun()
    if b3.button("Clear", use_container_width=True, key="lt_clear_field"):
        set_formation_slots({})
        _bump_slot_widgets()
        st.rerun()

    active_on = get_on_field(include_ol=False)
    st.markdown(
        f'<div class="dc-field"><div class="dc-header">Offense · '
        f'{len(active_on)} skill on</div>',
        unsafe_allow_html=True,
    )

    skill_cols = st.columns(len(FORMATION_OFFENSE_SKILL))
    for col, slot in zip(skill_cols, FORMATION_OFFENSE_SKILL):
        with col:
            _render_formation_slot(slot, roster, slots, side)
    st.markdown('<div class="dc-yardline"></div>', unsafe_allow_html=True)
    _, mid, _ = st.columns([2.5, 3, 2.5])
    with mid:
        qb_col, rb_col = st.columns(2)
        with qb_col:
            _render_formation_slot(FORMATION_OFFENSE_BACK[0], roster, slots, side)
        with rb_col:
            _render_formation_slot(FORMATION_OFFENSE_BACK[1], roster, slots, side)

    extras = [s for s in _offense_extra_slots() if not _is_ol_slot(s["id"])]
    if extras:
        st.markdown('<div class="dc-yardline"></div>', unsafe_allow_html=True)
        cols = st.columns(len(extras))
        for col, slot in zip(cols, extras):
            with col:
                _render_formation_slot(slot, roster, slots, side)

    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("OL depth (saved · graded · off GameCast)", expanded=False):
        st.caption(
            "Stays on each logged snap for overall OL grade "
            "(chunk runs +, sacks −). Not shown on GameCast."
        )
        ol_cols = st.columns(len(FORMATION_OFFENSE_OL))
        for col, slot in zip(ol_cols, FORMATION_OFFENSE_OL):
            with col:
                _render_formation_slot(slot, roster, slots, side)
        st.selectbox(
            "6th OL",
            [0, 1],
            format_func=lambda n: {0: "No", 1: "Yes"}[n],
            key="lt_extra_ol",
        )
        for slot in _offense_extra_slots():
            if _is_ol_slot(slot["id"]):
                _render_formation_slot(slot, roster, slots, side)

    with st.expander("On-field +/- · Skill stats · OL grade", expanded=False):
        t_pm, t_touch, t_ol = st.tabs(["On-field +/-", "Skill stats", "OL grade"])
        with t_pm:
            board = player_plus_minus_table(live_logs, opponent, by_position=True)
            if board.empty:
                st.caption("No +/- yet — log plays with a lineup set.")
            else:
                # Skill-focused board; OL has its own tab
                skill_board = board[~board["active_pos"].isin(OL_LOG_POSITIONS)].copy()
                show = (skill_board if not skill_board.empty else board).rename(
                    columns={
                        "player": "Player",
                        "active_pos": "At",
                        "snaps": "Snaps",
                        "plus_minus": "+/-",
                        "net_yards": "Net yds",
                        "good": "Good",
                        "bad": "Bad",
                    }
                )
                st.dataframe(show, hide_index=True, use_container_width=True, height=min(38 + 32 * len(show), 280))
        with t_touch:
            touches = player_skill_stats_table(live_logs, opponent)
            if touches.empty:
                st.caption(
                    "No skill stats yet — set the QB in lineup, say “complete to luke for 10” "
                    "or “luke carry for 10”, or pick Ball to / Passer on confirm."
                )
            else:
                show_t = touches.rename(
                    columns={
                        "player": "Player",
                        "cmp": "Cmp",
                        "att": "Att",
                        "pass_yds": "Pass",
                        "pass_td": "P TD",
                        "ints": "INT",
                        "sacks": "Sk",
                        "carries": "Rush",
                        "rush_yds": "Ru Yds",
                        "rush_td": "Ru TD",
                        "targets": "Tgt",
                        "receptions": "Rec",
                        "rec_yds": "Rec Yds",
                        "rec_td": "Rec TD",
                        "touches": "Tch",
                        "yards": "Yds",
                        "tds": "TD",
                        "avg_value": "Avg val",
                        "total_value": "Total val",
                    }
                )
                st.dataframe(show_t, hide_index=True, use_container_width=True, height=min(38 + 32 * len(show_t), 320))
                st.caption(
                    "Pass from on-field QB (or “Garrett to Luke”). Rush/Rec from ball-to phrases. "
                    "Value ≈ live EPA proxy — for per-player formula work."
                )
        with t_ol:
            ol_board = ol_grade_table(live_logs, opponent)
            if ol_board.empty:
                st.caption(
                    "No OL grade yet — Load starters (with OL filled) so the line is logged on snaps."
                )
            else:
                show_ol = ol_board.rename(
                    columns={
                        "player": "Player",
                        "pos": "Pos",
                        "snaps": "Snaps",
                        "grade": "Grade",
                        "avg": "Avg",
                        "big_runs": "10+ runs",
                        "sacks_tfl": "Sack/TFL",
                        "tds": "TD",
                    }
                )
                st.dataframe(
                    show_ol,
                    hide_index=True,
                    use_container_width=True,
                    height=min(38 + 32 * len(show_ol), 280),
                )
                st.caption(
                    "Overall line grade: + for 5/10/20+ yard runs & TD · − for sack/TFL. "
                    "Same grade applied to each OL on that snap."
                )


def _ht_call_card(row: dict, kind: str) -> str:
    """Compact HTML card for a call row (working / not working / adj)."""
    call = str(row.get("call", ""))
    plays = row.get("plays", "")
    good = row.get("good", "")
    bad = row.get("bad", "")
    score = row.get("score", None)
    tag = {"hot": "HOT", "cold": "COLD", "kill": "KILL", "lean": "LEAN", "test": "TEST"}.get(kind, kind.upper())
    meta_bits = []
    if plays != "":
        meta_bits.append(f"n={plays}")
    if good != "" or bad != "":
        meta_bits.append(f"{good}↑ {bad}↓")
    if score is not None and score != "":
        try:
            meta_bits.append(f"{float(score):+.2f}")
        except (TypeError, ValueError):
            pass
    meta = " · ".join(meta_bits)
    return (
        f'<div class="ht-card ht-{kind}">'
        f'<span class="tag">{tag}</span>'
        f'<span class="call">{call}</span>'
        f'{f"<div class=\"meta\">{meta}</div>" if meta else ""}'
        f"</div>"
    )


def _parse_adjustment_cards(adjustments: list[str]) -> list[tuple[str, str]]:
    """Turn long adjustment strings into (kind, short_label) cards."""
    out: list[tuple[str, str]] = []
    for a in adjustments or []:
        s = str(a)
        low = s.lower()
        # Prefer backticked call names
        call = ""
        if "`" in s:
            parts = s.split("`")
            if len(parts) >= 2:
                call = parts[1]
        if low.startswith("kill"):
            out.append(("kill", call or s.replace("KILL", "").strip(" :()-")))
        elif low.startswith("lean"):
            out.append(("lean", call or s.replace("LEAN", "").strip(" :()-")))
        elif low.startswith("test"):
            out.append(("test", call or s.replace("TEST", "").strip(" :()-")))
        elif low.startswith("formation"):
            kind = "cold" if "cold" in low else "lean"
            out.append((kind, f"FORM {call}" if call else s[:60]))
        elif low.startswith("coverage"):
            kind = "cold" if "cold" in low else ("lean" if "lean" in low else "test")
            out.append((kind, f"COV {call}" if call else s[:60]))
        elif low.startswith("situation"):
            kind = "cold" if "cold" in low else "hot"
            out.append((kind, f"SIT {call}" if call else s[:60]))
        elif low.startswith("blitz"):
            out.append(("test", call or s.replace("BLITZ", "").strip(" :()-")[:60] or "Blitz"))
        elif "hot:" in low or " hot:" in low:
            unit = "O" if "offense" in low else ("D" if "defense" in low else "")
            label = f"{unit} {call}".strip() if call else s
            out.append(("hot", label))
        elif "cold:" in low or " cold:" in low:
            unit = "O" if "offense" in low else ("D" if "defense" in low else "")
            label = f"{unit} {call}".strip() if call else s
            out.append(("cold", label))
        else:
            out.append(("test", call or s[:60]))
    # Deduplicate by label
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for kind, label in out:
        key = f"{kind}:{label}".lower()
        if key in seen or not str(label).strip():
            continue
        seen.add(key)
        uniq.append((kind, str(label).strip()))
    return uniq[:16]


# Halftime color language: green = good for us, red = bad for us (always)
HT_GOOD = "#4ade80"
HT_BAD = "#f87171"
HT_NEUTRAL = "#94a3b8"
HT_ACCENT = "#38bdf8"


def _ht_score_color(val) -> str:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return HT_NEUTRAL
    if v > 0.02:
        return HT_GOOD
    if v < -0.02:
        return HT_BAD
    return HT_NEUTRAL


def _ht_plotly_layout(fig: go.Figure, height: int = 280) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#F8FAF9",
        font=dict(color="#14201a", size=13),
        margin=dict(l=40, r=16, t=40, b=40),
        height=height,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def _ht_rows_to_frame(rows: list[dict] | None, *, season: bool = False) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).copy()
    if df.empty:
        return df
    rename = {
        "label": "Call",
        "formation": "Formation",
        "look": "Vs",
        "plays": "n",
        "good": "Good",
        "bad": "Bad",
        "score": "Score",
        "avg_yards": "Yds/play",
        "success_rate": "Succ%",
        "avg_epa": "EPA",
    }
    keep = [c for c in rename if c in df.columns]
    out = df[keep].rename(columns=rename)
    if "Succ%" in out.columns:
        out["Succ%"] = out["Succ%"].apply(
            lambda v: f"{float(v) * 100:.0f}%" if pd.notna(v) and v != "" else "—"
        )
    if "Score" in out.columns:
        out["Score"] = out["Score"].apply(lambda v: f"{float(v):+.2f}" if pd.notna(v) else "—")
    if "EPA" in out.columns:
        out["EPA"] = out["EPA"].apply(lambda v: f"{float(v):+.2f}" if pd.notna(v) else "—")
    if "Yds/play" in out.columns:
        out["Yds/play"] = out["Yds/play"].apply(
            lambda v: f"{float(v):.1f}" if pd.notna(v) and v != "" else "—"
        )
    return out


def _ht_show_board(rows: list[dict] | None, *, season: bool = False, empty: str = "No sample yet.") -> None:
    frame = _ht_rows_to_frame(rows, season=season)
    if frame.empty:
        st.caption(empty)
        return
    st.dataframe(frame, hide_index=True, use_container_width=True)


def _ht_board_with_chart(
    rows: list[dict] | None,
    title: str,
    *,
    key: str,
    season: bool = False,
    empty: str = "No sample yet.",
    limit: int = 6,
    chart_first: bool = True,
) -> None:
    """Coach-friendly: chart for quick read + table for the numbers."""
    fig = _ht_lollipop_scores(rows, title, limit=limit)
    if chart_first:
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key=key)
        _ht_show_board(rows, season=season, empty=empty)
    else:
        _ht_show_board(rows, season=season, empty=empty)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key=key)


def _ht_overall_line(block: dict) -> str:
    """One-line overall tonight + year EPA for a situation slice."""
    overall = block.get("overall") or {}
    ton = overall.get("tonight") or {}
    sea = overall.get("season") or {}
    bits: list[str] = []
    if ton.get("plays") and ton.get("avg_epa") is not None:
        bits.append(f"tonight EPA {float(ton['avg_epa']):+.2f} (n={ton['plays']})")
    if sea.get("plays") and sea.get("avg_epa") is not None:
        bits.append(f"year EPA {float(sea['avg_epa']):+.2f} (n={sea['plays']})")
    if ton.get("avg_yards") is not None and ton.get("plays"):
        bits.append(f"avg {float(ton['avg_yards']):+.1f} yds")
    return " · ".join(bits)


def _ht_render_situation_slice(
    block: dict,
    *,
    key_prefix: str,
    show_distance: bool = False,
) -> None:
    """Tonight vs year formations/plays for one down (optional short/med/long)."""
    ov = _ht_overall_line(block)
    if ov:
        st.markdown(
            f'<div class="ht-blurb"><b>Overall</b> · {ov}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption(f"Tonight n={block.get('tonight_n', 0)}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Tonight — formations**")
        _ht_board_with_chart(
            block.get("formations") or [],
            "Tonight formations",
            key=f"{key_prefix}_tf",
            empty="No snaps in this situation tonight.",
        )
        st.markdown("**Tonight — play calls**")
        _ht_board_with_chart(
            block.get("plays") or [],
            "Tonight plays",
            key=f"{key_prefix}_tp",
            empty="—",
        )
    with c2:
        st.markdown("**Year — formations**")
        _ht_board_with_chart(
            block.get("season_formations") or [],
            "Year formations (EPA)",
            key=f"{key_prefix}_yf",
            season=True,
            empty="Not enough season sample.",
        )
        st.markdown("**Year — play calls**")
        _ht_board_with_chart(
            block.get("season_plays") or [],
            "Year plays (EPA)",
            key=f"{key_prefix}_yp",
            season=True,
            empty="—",
        )

    if show_distance and block.get("by_distance"):
        st.markdown("##### By distance")
        dist_tabs = st.tabs(["Short", "Medium", "Long"])
        for tab, bucket in zip(dist_tabs, ("short", "medium", "long")):
            with tab:
                sub = (block.get("by_distance") or {}).get(bucket) or {}
                st.caption(sub.get("label") or f"& {bucket}")
                _ht_render_situation_slice(
                    sub,
                    key_prefix=f"{key_prefix}_{bucket}",
                    show_distance=False,
                )


def _ht_lollipop_scores(
    rows: list[dict] | None,
    title: str,
    *,
    limit: int = 8,
    key: str | None = None,
) -> go.Figure | None:
    """Diverging lollipop — green positive / red negative (mixes up the bar-chart diet)."""
    if not rows:
        return None
    df = pd.DataFrame(rows).copy()
    if df.empty or "label" not in df.columns:
        return None
    df["score"] = pd.to_numeric(df.get("score"), errors="coerce").fillna(0.0)
    df = df.sort_values("score", ascending=False).head(limit)
    df = df.sort_values("score")  # bottom→top for plot
    df["short"] = df["label"].astype(str).str.slice(0, 34)
    colors = [_ht_score_color(v) for v in df["score"]]
    fig = go.Figure()
    for _, r in df.iterrows():
        fig.add_shape(
            type="line",
            x0=0,
            x1=float(r["score"]),
            y0=r["short"],
            y1=r["short"],
            line=dict(color=_ht_score_color(r["score"]), width=3),
        )
    fig.add_trace(
        go.Scatter(
            x=df["score"],
            y=df["short"],
            mode="markers",
            marker=dict(size=13, color=colors, line=dict(width=0)),
            customdata=list(zip(df.get("plays", pd.Series([0] * len(df))), df["score"])),
            hovertemplate="%{y}<br>score %{x:.2f} · n=%{customdata[0]}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Score (green = working)",
        yaxis_title="",
        xaxis=dict(gridcolor="#374151", zerolinecolor="#e5e7eb", zerolinewidth=1),
        showlegend=False,
    )
    return _ht_plotly_layout(fig, height=max(240, 32 * len(df) + 70))


def _ht_call_score_chart(report: dict) -> go.Figure | None:
    rows = []
    for unit in ("offense", "defense"):
        for r in (report.get("working", {}) or {}).get(unit, []):
            rows.append({**r, "unit": unit.title(), "bucket": "Working"})
        for r in (report.get("not_working", {}) or {}).get(unit, []):
            rows.append({**r, "unit": unit.title(), "bucket": "Cold"})
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values("score")
    df["label"] = df["call"].astype(str).str.slice(0, 28)
    colors = [_ht_score_color(s) for s in df["score"]]
    fig = go.Figure(
        go.Bar(
            x=df["score"],
            y=df["label"],
            orientation="h",
            marker_color=colors,
            customdata=list(zip(df["unit"], df["plays"])),
            hovertemplate="%{y}<br>%{customdata[0]} · n=%{customdata[1]}<br>score %{x:.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Call scores (1st half)",
        xaxis_title="Score",
        yaxis_title="",
        xaxis=dict(gridcolor="#374151", zerolinecolor="#6b7280"),
        yaxis=dict(gridcolor="#374151"),
    )
    return _ht_plotly_layout(fig, height=max(260, 36 * len(df) + 80))


def _ht_player_pm_chart(players: list[dict]) -> go.Figure | None:
    if not players:
        return None
    df = pd.DataFrame(players)
    if df.empty or "plus_minus" not in df.columns:
        return None
    df = df.copy()
    pos = df["active_pos"] if "active_pos" in df.columns else pd.Series(["—"] * len(df), index=df.index)
    df["label"] = df["player"].astype(str) + " @" + pos.astype(str)
    df = df.drop_duplicates(subset=["label"]).sort_values("plus_minus")
    df = pd.concat([df.head(6), df.tail(6)]).drop_duplicates(subset=["label"])
    if df.empty:
        return None
    colors = [_ht_score_color(v) for v in df["plus_minus"]]
    fig = go.Figure(
        go.Bar(
            x=df["plus_minus"],
            y=df["label"],
            orientation="h",
            marker_color=colors,
            hovertemplate="%{y}<br>+/- %{x:.2f}<extra></extra>",
        )
    )
    fig.update_layout(title="Player +/- (1st half)", xaxis_title="+/-", yaxis_title="")
    return _ht_plotly_layout(fig, height=max(260, 32 * len(df) + 80))


def _ht_filter_half_logs(live_logs: pd.DataFrame | None, opponent: str) -> pd.DataFrame:
    if live_logs is None or live_logs.empty:
        return pd.DataFrame()
    logs = live_logs.copy()
    if opponent and "opponent" in logs.columns:
        filt = logs[logs["opponent"].astype(str).str.strip().str.lower() == opponent.strip().lower()]
        if not filt.empty:
            logs = filt
    if "half" in logs.columns:
        h1 = logs[logs["half"].astype(str) == "1"]
        if not h1.empty:
            logs = h1
    return logs


def _ht_results_chart(live_logs: pd.DataFrame | None, opponent: str) -> go.Figure | None:
    logs = _ht_filter_half_logs(live_logs, opponent)
    if logs.empty or "result" not in logs.columns:
        return None
    counts = logs["result"].astype(str).value_counts().reset_index()
    counts.columns = ["result", "plays"]
    fig = px.bar(
        counts,
        x="result",
        y="plays",
        title="Results mix (1st half)",
        color="plays",
        color_continuous_scale="Tealgrn",
    )
    fig.update_layout(xaxis_title="", yaxis_title="Plays", coloraxis_showscale=False)
    return _ht_plotly_layout(fig, height=300)


def _ht_unit_donut(report: dict) -> go.Figure | None:
    s = report.get("summary") or {}
    off = int(s.get("offense_plays") or 0)
    deff = int(s.get("defense_plays") or 0)
    if off + deff <= 0:
        return None
    fig = go.Figure(
        go.Pie(
            labels=["Offense", "Defense"],
            values=[off, deff],
            hole=0.55,
            marker_colors=["#3b82f6", "#f59e0b"],
            textinfo="label+value",
            textfont=dict(color="#f9fafb", size=13),
        )
    )
    fig.update_layout(title="Snaps by unit")
    return _ht_plotly_layout(fig, height=300)


def _ht_good_bad_chart(report: dict) -> go.Figure | None:
    rows = []
    for unit in ("offense", "defense"):
        for bucket, key in (("Working", "working"), ("Cold", "not_working")):
            for r in (report.get(key, {}) or {}).get(unit, []):
                rows.append(
                    {
                        "call": str(r.get("call", ""))[:24],
                        "unit": unit.title(),
                        "good": int(r.get("good") or 0),
                        "bad": int(r.get("bad") or 0),
                        "bucket": bucket,
                    }
                )
    if not rows:
        return None
    df = pd.DataFrame(rows).drop_duplicates(subset=["call", "unit"]).head(10)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Good",
            x=df["call"],
            y=df["good"],
            marker_color="#4ade80",
            hovertemplate="%{x}<br>good %{y}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Bad",
            x=df["call"],
            y=df["bad"],
            marker_color="#f87171",
            hovertemplate="%{x}<br>bad %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        barmode="group",
        title="Good vs bad by call",
        xaxis_title="",
        yaxis_title="Plays",
    )
    return _ht_plotly_layout(fig, height=320)


def _ht_pins_chart(report: dict) -> go.Figure | None:
    status = {}
    for unit in ("offense", "defense"):
        for call, tag in (report.get("plan_status", {}) or {}).get(unit, {}).items():
            status[f"{unit[:1].upper()}: {call}"] = str(tag).lower()
    if not status:
        return None
    labels = list(status.keys())
    vals = list(status.values())
    color_map = {"confirmed": "#059669", "kill": "#dc2626", "unproven": "#6b7280"}
    colors = [color_map.get(v, "#6b7280") for v in vals]
    fig = go.Figure(
        go.Bar(
            x=[v.upper() for v in vals],
            y=labels,
            orientation="h",
            marker_color=colors,
            text=[v.upper() for v in vals],
            textposition="inside",
            textfont=dict(color="#ffffff", size=12),
        )
    )
    fig.update_layout(title="Plan pin status", xaxis_title="", yaxis_title="")
    return _ht_plotly_layout(fig, height=max(240, 34 * len(labels) + 70))


def _ht_dim_score_chart(
    rows: list[dict] | None,
    title: str,
    *,
    limit: int = 10,
) -> go.Figure | None:
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if df.empty or "label" not in df.columns:
        return None
    df = df.copy().sort_values("score").tail(limit)
    df["short"] = df["label"].astype(str).str.slice(0, 36)
    colors = [_ht_score_color(s) for s in df["score"]]
    fig = go.Figure(
        go.Bar(
            x=df["score"],
            y=df["short"],
            orientation="h",
            marker_color=colors,
            customdata=list(zip(df["plays"], df.get("avg_yards", pd.Series([None] * len(df))))),
            hovertemplate=(
                "%{y}<br>score %{x:.2f}<br>n=%{customdata[0]}"
                "<br>yds/play %{customdata[1]}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Score",
        yaxis_title="",
        xaxis=dict(gridcolor="#374151", zerolinecolor="#6b7280"),
    )
    return _ht_plotly_layout(fig, height=max(260, 34 * len(df) + 80))


def _ht_blitz_charts(report: dict) -> tuple[go.Figure | None, go.Figure | None]:
    """Return (blitz% by situation, blitz vs no-blitz performance)."""
    blitz = ((report.get("blitz") or {}).get("offense") or {})
    if not blitz.get("plays"):
        blitz = (report.get("blitz") or {}).get("overall") or {}
    if not blitz.get("plays"):
        return None, None

    sit_fig = None
    sit_rows = blitz.get("by_down_distance") or []
    if not sit_rows:
        sit_rows = [
            {
                "down_distance": r.get("situation", ""),
                "blitz_pct": r.get("blitz_pct", 0),
                "plays": r.get("plays", 0),
                "blitz_plays": r.get("blitz_plays", 0),
            }
            for r in (blitz.get("by_situation") or [])
        ]
    if sit_rows:
        sdf = pd.DataFrame(sit_rows).copy()
        label_col = "down_distance" if "down_distance" in sdf.columns else "situation"
        sdf = sdf.sort_values("blitz_pct", ascending=True).tail(6)
        fig = go.Figure(
            go.Bar(
                x=sdf["blitz_pct"],
                y=sdf[label_col].astype(str).str.slice(0, 32),
                orientation="h",
                marker_color="#fbbf24",
                customdata=list(
                    zip(
                        sdf.get("blitz_plays", pd.Series([0] * len(sdf))),
                        sdf["plays"],
                    )
                ),
                hovertemplate="%{y}<br>%{x:.0f}% (%{customdata[0]}/%{customdata[1]})<extra></extra>",
            )
        )
        fig.update_layout(
            title=f"Blitz situations · {blitz.get('blitz_pct', 0)}% overall",
            xaxis_title="Blitz %",
            yaxis_title="",
            xaxis=dict(range=[0, 100], gridcolor="#374151"),
        )
        sit_fig = _ht_plotly_layout(fig, height=260)

    perf_fig = None
    labels, scores, plays, colors = [], [], [], []
    for name, key in (("Blitz", "when_blitz"), ("No blitz", "when_no_blitz")):
        m = blitz.get(key) or {}
        if not m:
            continue
        sc = float(m.get("score") or 0)
        labels.append(name)
        scores.append(sc)
        plays.append(int(m.get("plays") or 0))
        colors.append(_ht_score_color(sc))  # green/red by OUR result, not by blitz label
    if labels:
        fig = go.Figure(
            go.Bar(
                x=labels,
                y=scores,
                marker_color=colors,
                text=[f"n={n}" for n in plays],
                textposition="outside",
                hovertemplate="%{x}<br>score %{y:.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            title="Our results vs pressure (green = we good)",
            yaxis_title="Score",
            xaxis_title="",
            yaxis=dict(gridcolor="#374151", zerolinecolor="#6b7280"),
        )
        perf_fig = _ht_plotly_layout(fig, height=260)

    return sit_fig, perf_fig


def _ht_rate_bar(
    rows: list[dict] | None,
    label_key: str,
    title: str,
    *,
    value_key: str = "blitz_pct",
    count_key: str = "blitz_plays",
    plays_key: str = "plays",
    limit: int = 6,
    color: str = "#fbbf24",
) -> go.Figure | None:
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if df.empty or label_key not in df.columns or value_key not in df.columns:
        return None
    df = df.copy().sort_values(value_key, ascending=True).tail(limit)
    fig = go.Figure(
        go.Bar(
            x=df[value_key],
            y=df[label_key].astype(str).str.slice(0, 28),
            orientation="h",
            marker_color=color,
            customdata=list(
                zip(
                    df[count_key] if count_key in df.columns else [0] * len(df),
                    df[plays_key] if plays_key in df.columns else [0] * len(df),
                )
            ),
            hovertemplate="%{y}<br>%{x:.0f}% (%{customdata[0]}/%{customdata[1]})<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="%",
        yaxis_title="",
        xaxis=dict(range=[0, max(100, float(df[value_key].max()) + 5)], gridcolor="#374151"),
    )
    return _ht_plotly_layout(fig, height=240)


def _ht_coverage_top_by_dim(
    rows: list[dict] | None,
    dim_key: str,
    title: str,
    *,
    limit: int = 6,
) -> go.Figure | None:
    """One bar per dimension value = top coverage % in that bucket."""
    if not rows:
        return None
    best: dict[str, dict] = {}
    for r in rows:
        dim = str(r.get(dim_key, "")).strip()
        if not dim:
            continue
        if dim not in best or float(r.get("pct") or 0) > float(best[dim].get("pct") or 0):
            best[dim] = r
    if not best:
        return None
    ordered = sorted(best.values(), key=lambda r: float(r.get("group_plays") or 0))[-limit:]
    labels = [
        f"{r.get(dim_key)} → {r.get('coverage')}" for r in ordered
    ]
    fig = go.Figure(
        go.Bar(
            x=[float(r.get("pct") or 0) for r in ordered],
            y=[str(l)[:34] for l in labels],
            orientation="h",
            marker_color="#60a5fa",
            customdata=[int(r.get("group_plays") or 0) for r in ordered],
            hovertemplate="%{y}<br>%{x:.0f}% of n=%{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Coverage %",
        yaxis_title="",
        xaxis=dict(range=[0, 100], gridcolor="#374151"),
    )
    return _ht_plotly_layout(fig, height=240)


def _ht_xp_strip_html(report: dict) -> str:
    xp = (report.get("xp") or {}).get("offense") or {}
    if not xp.get("plays"):
        return ""
    actual = xp.get("actual_points", 0)
    xpoints = xp.get("xpoints", 0)
    luck = float(xp.get("luck") or 0)
    if luck > 0.5:
        band, cls = "OVER performing", "up"
    elif luck < -0.5:
        band, cls = "UNDER performing", "down"
    else:
        band, cls = "ON process", ""
    return (
        f'<div class="ht-sec">xP · 1st half (offense)</div>'
        f'<div class="ht-strip">'
        f'<div class="ht-stat"><div class="n">{actual}</div><div class="l">Actual pts</div></div>'
        f'<div class="ht-stat"><div class="n">{xpoints}</div><div class="l">xPoints</div></div>'
        f'<div class="ht-stat"><div class="n">{luck:+.1f}</div><div class="l">Luck</div></div>'
        f'<div class="ht-stat"><div class="n">{xp.get("total_epa", 0)}</div><div class="l">EPA</div></div>'
        f"</div>"
        f'<div class="ht-blurb {cls}">{band} vs season pace '
        f'(TD pts vs expected from process)</div>'
    )


def _ht_top_bottom(rows: list[dict] | None, n: int = 2) -> tuple[list[dict], list[dict]]:
    if not rows:
        return [], []
    ordered = sorted(rows, key=lambda r: float(r.get("score") or 0), reverse=True)
    tops = [r for r in ordered if float(r.get("score") or 0) >= 0][:n]
    bots = [r for r in reversed(ordered) if float(r.get("score") or 0) < 0][:n]
    if not tops and ordered:
        tops = ordered[:1]
    return tops, bots


def _ht_chips(rows: list[dict], band: str) -> str:
    if not rows:
        return ""
    bits = []
    for r in rows:
        label = str(r.get("label") or r.get("call") or "")[:28]
        n = r.get("plays", "")
        score = r.get("score", None)
        score_bit = f"{float(score):+.2f}" if score is not None and score != "" else ""
        bits.append(
            f'<span class="ht-chip {band}"><span>{label}</span>'
            f'<span class="n">{score_bit} · n={n}</span></span>'
        )
    return f'<div class="ht-chip-row">{"".join(bits)}</div>'


def _ht_blitz_blurb(report: dict) -> str:
    blitz = ((report.get("blitz") or {}).get("offense") or {})
    if not blitz.get("plays"):
        blitz = (report.get("blitz") or {}).get("overall") or {}
    if not blitz.get("plays"):
        return ""
    wb = blitz.get("when_blitz") or {}
    wn = blitz.get("when_no_blitz") or {}
    rate = blitz.get("blitz_pct", 0)
    parts = [f"Blitz <b>{rate}%</b> ({blitz.get('blitz_plays', 0)}/{blitz.get('plays', 0)})"]
    if wb and wn and wb.get("plays") and wn.get("plays"):
        bs, ns = float(wb.get("score") or 0), float(wn.get("score") or 0)
        if bs < ns - 0.05:
            parts.append(f"struggle vs pressure ({bs:+.2f} vs {ns:+.2f})")
        elif bs > ns + 0.05:
            parts.append(f"handle pressure ({bs:+.2f} vs {ns:+.2f})")
        else:
            parts.append(f"even vs pressure ({bs:+.2f} / {ns:+.2f})")
    by_cov = blitz.get("by_coverage") or []
    if by_cov:
        top = max(by_cov, key=lambda r: (r.get("blitz_pct", 0), r.get("plays", 0)))
        if top.get("blitz_pct", 0) >= 30:
            parts.append(f"most from Cover {top.get('coverage')} ({top.get('blitz_pct')}%)")
    return " · ".join(parts)


def _ht_priority_actions(report: dict, limit: int = 6) -> tuple[list[str], list[str]]:
    """Pick a short Feature / Shelve list from adjustments + boards."""
    feature: list[str] = []
    shelve: list[str] = []
    for a in report.get("adjustments") or []:
        low = str(a).lower()
        call = ""
        if "`" in str(a):
            parts = str(a).split("`")
            if len(parts) >= 2:
                call = parts[1]
        label = call or str(a)[:40]
        if any(k in low for k in ("kill", "cold", "shelve", "avoid", "down:")):
            if label not in shelve and not low.startswith("blitz"):
                shelve.append(label)
        elif any(k in low for k in ("lean", "hot", "feature", "confirmed", "up:")):
            if label not in feature and not low.startswith("blitz"):
                feature.append(label)
        if len(feature) >= limit and len(shelve) >= limit:
            break
    # Fill from boards if thin
    for key in ("formation_play", "formations"):
        rows = (report.get(key) or {}).get("offense") or []
        tops, bots = _ht_top_bottom(rows, 2)
        for r in tops:
            lab = str(r.get("label", ""))
            if lab and lab not in feature:
                feature.append(lab)
        for r in bots:
            lab = str(r.get("label", ""))
            if lab and lab not in shelve:
                shelve.append(lab)
    play_calls = report.get("play_calls") or {}
    for bucket in ("by_mode", "overall"):
        rows = (play_calls.get(bucket) or {}).get("offense") or []
        tops, bots = _ht_top_bottom(rows, 2)
        for r in tops:
            lab = str(r.get("label", ""))
            if lab and lab not in feature:
                feature.append(lab)
        for r in bots:
            lab = str(r.get("label", ""))
            if lab and lab not in shelve:
                shelve.append(lab)
    return feature[:limit], shelve[:limit]


def _ht_tendency_dim_table(
    rows: list[dict],
    *,
    dim_key: str,
    dim_label: str,
    value_key: str = "blitz_pct",
    value_label: str = "Blitz %",
    extra_cols: tuple[str, ...] = ("blitz_plays", "plays"),
    rename_extra: dict | None = None,
    min_plays: int = 1,
    limit: int = 8,
) -> pd.DataFrame | None:
    """Compact situation table for blitz / coverage maps (locker-room readable)."""
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if dim_key not in df.columns:
        return None
    if "plays" in df.columns:
        df = df[pd.to_numeric(df["plays"], errors="coerce").fillna(0) >= min_plays]
    if df.empty:
        return None
    sort_col = value_key if value_key in df.columns else "plays"
    df = df.sort_values(sort_col, ascending=False).head(limit)
    cols = [dim_key, value_key] + [c for c in extra_cols if c in df.columns]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    ren = {dim_key: dim_label, value_key: value_label}
    if rename_extra:
        ren.update(rename_extra)
    else:
        ren.update({"blitz_plays": "Blitz n", "plays": "n", "pct": "%", "coverage": "Cover", "group_plays": "Snaps"})
    return out.rename(columns=ren)


def _ht_coverage_top_by_dim(rows: list[dict], dim_key: str, limit: int = 6) -> pd.DataFrame | None:
    """One row per situation → most common coverage."""
    if not rows:
        return None
    best: dict[str, dict] = {}
    for r in rows:
        dim = str(r.get(dim_key, "") or "").strip()
        if not dim:
            continue
        if dim not in best or float(r.get("pct") or 0) > float(best[dim].get("pct") or 0):
            best[dim] = r
    ordered = sorted(best.values(), key=lambda r: -int(r.get("group_plays") or r.get("plays") or 0))
    if not ordered:
        return None
    df = pd.DataFrame(ordered[:limit])
    cols = [c for c in (dim_key, "coverage", "pct", "group_plays", "plays") if c in df.columns]
    out = df[cols].rename(
        columns={
            dim_key: "When",
            "coverage": "They play",
            "pct": "%",
            "group_plays": "Snaps",
            "plays": "n",
        }
    )
    return out


def _render_halftime_report_body(
    report: dict,
    markdown: str,
    key_prefix: str = "ht",
    live_logs: pd.DataFrame | None = None,
) -> None:
    """Locker-room first: plan + their looks, then our calls / situations / players."""
    s = report.get("summary", {})
    opp = report.get("opponent", "")
    blitz_pct = s.get("blitz_pct", 0)
    st.markdown(
        f'<div class="ht-wrap"><div class="ht-title">Halftime · vs {opp}</div>'
        f'<div class="ht-strip">'
        f'<div class="ht-stat"><div class="n">{s.get("plays", 0)}</div><div class="l">Plays</div></div>'
        f'<div class="ht-stat"><div class="n">{s.get("offense_plays", 0)}/{s.get("defense_plays", 0)}</div>'
        f'<div class="l">O / D</div></div>'
        f'<div class="ht-stat"><div class="n">{blitz_pct}%</div><div class="l">Blitz</div></div>'
        f'<div class="ht-stat"><div class="n">{s.get("turnovers", 0)}/{s.get("sacks_tfl", 0)}</div>'
        f'<div class="l">TO / Sack</div></div>'
        f"</div></div>",
        unsafe_allow_html=True,
    )
    if s.get("scope") == "all_logged_tonight":
        st.caption("Using all tonight’s snaps (no half=1 tags).")

    form_rows = (report.get("formations") or {}).get("offense") or []
    combo_rows = (report.get("formation_play") or {}).get("offense") or []
    play_calls = report.get("play_calls") or {}
    play_overall = (play_calls.get("overall") or {}).get("offense") or []
    play_mode = (play_calls.get("by_mode") or {}).get("offense") or []
    vs_look = report.get("formation_vs_look") or {}
    scenarios = report.get("scenarios") or {}
    standouts = report.get("standout_looks") or []
    players = report.get("players") or []
    blitz = ((report.get("blitz") or {}).get("offense") or {})
    cov = ((report.get("coverage_tendencies") or {}).get("offense") or {})
    cov_dom = (cov.get("dominance") or {}) if isinstance(cov, dict) else {}
    feature, shelve = _ht_priority_actions(report, limit=4)

    # Always-visible 2nd-half cue strip
    if feature or shelve or standouts:
        st.markdown('<div class="ht-sec">2nd half cues</div>', unsafe_allow_html=True)
        cue_cols = st.columns(2)
        with cue_cols[0]:
            st.markdown("**Feature**")
            st.markdown(
                "".join(_ht_call_card({"call": c}, "lean") for c in feature)
                or "<span class='ht-blurb'>Need a few more tagged snaps.</span>",
                unsafe_allow_html=True,
            )
        with cue_cols[1]:
            st.markdown("**Shelve**")
            st.markdown(
                "".join(_ht_call_card({"call": c}, "kill") for c in shelve)
                or "<span class='ht-blurb'>Nothing cold enough yet.</span>",
                unsafe_allow_html=True,
            )
        if standouts:
            for row in standouts[:3]:
                st.markdown(
                    f'<div class="ht-blurb">{row.get("message", "")}</div>',
                    unsafe_allow_html=True,
                )

    tab_plan, tab_looks, tab_form, tab_scen, tab_plyr, tab_drive, tab_print = st.tabs(
        ["2nd half plan", "Their looks", "Our calls", "Situations", "Players", "Drive map", "Print"]
    )

    with tab_plan:
        xp_html = _ht_xp_strip_html(report)
        if xp_html:
            st.markdown(xp_html, unsafe_allow_html=True)
        st.caption("What to run / what to kill — derived from tonight’s snaps.")
        left, right = st.columns(2)
        with left:
            st.markdown("##### Do this")
            st.markdown(
                "".join(_ht_call_card({"call": c}, "lean") for c in feature)
                or "<span class='ht-blurb'>No clear features yet.</span>",
                unsafe_allow_html=True,
            )
            form_up, _ = _ht_top_bottom(form_rows, 3)
            if form_up:
                st.markdown("**Hot formations**")
                st.markdown(_ht_chips(form_up, "up"), unsafe_allow_html=True)
            play_up, _ = _ht_top_bottom(play_overall, 3)
            if play_up:
                st.markdown("**Hot plays**")
                st.markdown(_ht_chips(play_up, "up"), unsafe_allow_html=True)
        with right:
            st.markdown("##### Avoid this")
            st.markdown(
                "".join(_ht_call_card({"call": c}, "kill") for c in shelve)
                or "<span class='ht-blurb'>Nothing to shelve yet.</span>",
                unsafe_allow_html=True,
            )
            _, form_dn = _ht_top_bottom(form_rows, 3)
            if form_dn:
                st.markdown("**Cold formations**")
                st.markdown(_ht_chips(form_dn, "down"), unsafe_allow_html=True)
            _, play_dn = _ht_top_bottom(play_overall, 3)
            if play_dn:
                st.markdown("**Cold plays**")
                st.markdown(_ht_chips(play_dn, "down"), unsafe_allow_html=True)

        if standouts:
            st.markdown("##### Standout looks")
            for row in standouts:
                st.markdown(f"- {row.get('message', '')}")

        st.info(
            "2nd half: feature the hot formations/plays above · "
            "expect their blitz/coverage in the spots on **Their looks**."
        )

    with tab_looks:
        st.caption("Defense tells from Fill Film tags — the old Notes gold, on the board.")
        st.markdown("##### Coverage")
        mix = cov.get("mix") or []
        if mix:
            summary = cov_dom.get("summary") or " · ".join(
                f"{r.get('coverage')} {r.get('pct')}%" for r in mix[:4]
            )
            st.markdown(f'<div class="ht-blurb">Mix: {summary}</div>', unsafe_allow_html=True)
            st.dataframe(
                pd.DataFrame(mix)[["coverage", "plays", "pct"]].rename(
                    columns={"coverage": "Coverage", "plays": "n", "pct": "%"}
                ),
                hide_index=True,
                use_container_width=True,
            )
            if cov_dom.get("skip_breakdowns"):
                st.caption("Coverage is concentrated — situation splits would all look the same.")
            else:
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown("**By formation**")
                    cdf = _ht_coverage_top_by_dim(cov.get("by_formation") or [], "formation")
                    if cdf is not None:
                        st.dataframe(cdf, hide_index=True, use_container_width=True)
                    else:
                        st.caption("—")
                with c2:
                    st.markdown("**By field**")
                    cdf = _ht_coverage_top_by_dim(cov.get("by_field_zone") or [], "field_zone")
                    if cdf is not None:
                        st.dataframe(cdf, hide_index=True, use_container_width=True)
                    else:
                        st.caption("—")
                with c3:
                    st.markdown("**By D&D**")
                    cdf = _ht_coverage_top_by_dim(cov.get("by_down_distance") or [], "down_distance")
                    if cdf is not None:
                        st.dataframe(cdf, hide_index=True, use_container_width=True)
                    else:
                        st.caption("—")
        else:
            st.caption("No coverage tags yet — Fill Film between drives.")

        st.markdown("##### Pressure / blitz")
        if blitz.get("plays"):
            st.markdown(
                f'<div class="ht-blurb">Blitz <b>{blitz.get("blitz_pct", 0)}%</b> '
                f'({blitz.get("blitz_plays", 0)}/{blitz.get("plays", 0)})</div>',
                unsafe_allow_html=True,
            )
            blurb = _ht_blitz_blurb(report)
            if blurb:
                st.caption(blurb)
            b1, b2, b3 = st.columns(3)
            with b1:
                st.markdown("**By formation**")
                bdf = _ht_tendency_dim_table(
                    blitz.get("by_formation") or [],
                    dim_key="formation",
                    dim_label="Formation",
                )
                if bdf is not None:
                    st.dataframe(bdf, hide_index=True, use_container_width=True)
                else:
                    st.caption("—")
            with b2:
                st.markdown("**By field**")
                bdf = _ht_tendency_dim_table(
                    blitz.get("by_field_zone") or [],
                    dim_key="field_zone",
                    dim_label="Zone",
                )
                if bdf is not None:
                    st.dataframe(bdf, hide_index=True, use_container_width=True)
                else:
                    st.caption("—")
            with b3:
                st.markdown("**By D&D**")
                bdf = _ht_tendency_dim_table(
                    blitz.get("by_down_distance") or [],
                    dim_key="down_distance",
                    dim_label="Situation",
                )
                if bdf is not None:
                    st.dataframe(bdf, hide_index=True, use_container_width=True)
                else:
                    st.caption("—")
            _, perf = _ht_blitz_charts(report)
            if perf is not None:
                st.plotly_chart(perf, use_container_width=True, key=f"{key_prefix}_blitz_perf")
        else:
            st.caption("No blitz tags yet.")

    with tab_form:
        st.caption("Green = working for us · Red = cold.")
        st.markdown("##### Formations overall (tonight)")
        _ht_board_with_chart(
            form_rows,
            "Formation scores",
            key=f"{key_prefix}_form_lolli",
            empty="Need formation tags on ≥3 snaps.",
            limit=8,
        )
        form_up, form_dn = _ht_top_bottom(form_rows, 2)
        st.markdown(
            _ht_chips(form_up, "up") + _ht_chips(form_dn, "down"),
            unsafe_allow_html=True,
        )

        st.markdown("##### Working against what")
        v1, v2 = st.columns(2)
        with v1:
            st.markdown("**Formation vs coverage**")
            _ht_board_with_chart(
                vs_look.get("vs_coverage") or [],
                "Formation vs coverage",
                key=f"{key_prefix}_vs_cov",
                empty="Tag coverage in Fill Film to unlock this board.",
            )
        with v2:
            st.markdown("**Formation vs front**")
            _ht_board_with_chart(
                vs_look.get("vs_front") or [],
                "Formation vs front",
                key=f"{key_prefix}_vs_front",
                empty="Tag fronts in Fill Film to unlock this board.",
            )

        st.markdown("##### Formation | play combos")
        c1, c2 = st.columns(2)
        with c1:
            _ht_board_with_chart(
                combo_rows,
                "Combo scores",
                key=f"{key_prefix}_combo",
                empty="No formation|play combos yet.",
            )
        with c2:
            st.markdown("**Combo vs coverage**")
            _ht_board_with_chart(
                vs_look.get("combo_vs_coverage") or [],
                "Combo vs coverage",
                key=f"{key_prefix}_combo_cov",
                empty="Need film tags + repeated combos.",
            )

        st.markdown("##### Play calls")
        st.caption(
            "Overall = the call as dialed (e.g. Army Bear). "
            "Run vs pass = same dual-tag concept by outcome lane."
        )
        p1, p2 = st.columns(2)
        with p1:
            st.markdown("**Overall**")
            _ht_board_with_chart(
                play_overall,
                "Play call scores",
                key=f"{key_prefix}_play_overall",
                empty="Need play tags on ≥2 snaps.",
            )
            pu, pdn = _ht_top_bottom(play_overall, 2)
            st.markdown(
                _ht_chips(pu, "up") + _ht_chips(pdn, "down"),
                unsafe_allow_html=True,
            )
        with p2:
            st.markdown("**Run vs pass (dual-tag)**")
            _ht_board_with_chart(
                play_mode,
                "Play · run / pass",
                key=f"{key_prefix}_play_mode",
                empty="Log dual-tag RPOs with run or pass outcomes to unlock.",
            )
            mu, mdn = _ht_top_bottom(play_mode, 2)
            st.markdown(
                _ht_chips(mu, "up") + _ht_chips(mdn, "down"),
                unsafe_allow_html=True,
            )

    with tab_scen:
        by_down = scenarios.get("by_down") or {}
        openers = scenarios.get("drive_start") or {}
        conv = scenarios.get("convert") or {}

        d_tabs = st.tabs(["1st", "2nd", "3rd", "4th", "Openers", "3rd/4th all"])
        for d_tab, d_key in zip(d_tabs[:4], ("1", "2", "3", "4")):
            with d_tab:
                block = by_down.get(d_key) or {}
                st.markdown(f"##### {block.get('label', f'{d_key} down')}")
                _ht_render_situation_slice(
                    block,
                    key_prefix=f"{key_prefix}_d{d_key}",
                    show_distance=True,
                )

        with d_tabs[4]:
            st.markdown(
                f"##### {openers.get('label', 'Drive starters')} · "
                f"n={openers.get('tonight_n', 0)} tonight"
            )
            if openers.get("season_note"):
                st.caption(str(openers.get("season_note")))
            _ht_render_situation_slice(
                openers,
                key_prefix=f"{key_prefix}_open",
                show_distance=False,
            )
            if openers.get("combos"):
                st.markdown("**Tonight — opener combos**")
                _ht_board_with_chart(
                    openers.get("combos") or [],
                    "Opener combos",
                    key=f"{key_prefix}_open_combo",
                )

        with d_tabs[5]:
            st.markdown(
                f"##### {conv.get('label', '3rd / 4th overall')} · "
                f"n={conv.get('tonight_n', 0)} tonight"
            )
            st.caption("Pooled convert downs — use 3rd/4th tabs above for short/medium/long.")
            a1, a2 = st.columns(2)
            with a1:
                _ht_board_with_chart(
                    conv.get("formations") or [],
                    "Tonight convert formations",
                    key=f"{key_prefix}_conv_tf",
                    empty="No 3rd/4th sample tonight yet.",
                )
                _ht_board_with_chart(
                    conv.get("plays") or [],
                    "Tonight convert plays",
                    key=f"{key_prefix}_conv_tp",
                    empty="—",
                )
            with a2:
                _ht_board_with_chart(
                    conv.get("season_formations") or [],
                    "Year convert formations",
                    key=f"{key_prefix}_conv_yf",
                    season=True,
                    empty="Not enough season convert snaps.",
                )
                _ht_board_with_chart(
                    conv.get("season_plays") or [],
                    "Year convert plays",
                    key=f"{key_prefix}_conv_yp",
                    season=True,
                    empty="—",
                )

    with tab_plyr:
        pm_fig = _ht_player_pm_chart(players)
        p1, p2 = st.columns([1.2, 1])
        with p1:
            if pm_fig is not None:
                st.plotly_chart(pm_fig, use_container_width=True, key=f"{key_prefix}_chart_pm")
            else:
                st.caption("Need players_on on logged snaps.")
        with p2:
            ups = [p for p in players if p.get("band") == "up"]
            downs = [p for p in players if p.get("band") == "down"]
            if ups:
                st.markdown(
                    "".join(
                        f'<div class="ht-player"><span>{p.get("player")} '
                        f'<small>@{p.get("active_pos", "")}</small></span>'
                        f'<span class="pm-up">{float(p.get("plus_minus", 0)):+.1f}</span></div>'
                        for p in ups
                    ),
                    unsafe_allow_html=True,
                )
            if downs:
                st.markdown(
                    "".join(
                        f'<div class="ht-player"><span>{p.get("player")} '
                        f'<small>@{p.get("active_pos", "")}</small></span>'
                        f'<span class="pm-down">{float(p.get("plus_minus", 0)):+.1f}</span></div>'
                        for p in downs
                    ),
                    unsafe_allow_html=True,
                )
            if not ups and not downs:
                st.caption("No standouts yet.")
        if live_logs is not None:
            touches = player_skill_stats_table(live_logs, opp)
            if not touches.empty:
                st.markdown('<div class="ht-sec">Skill stats (1st half)</div>', unsafe_allow_html=True)
                st.dataframe(
                    touches.rename(
                        columns={
                            "player": "Player",
                            "cmp": "Cmp",
                            "att": "Att",
                            "pass_yds": "Pass",
                            "pass_td": "P TD",
                            "ints": "INT",
                            "sacks": "Sk",
                            "carries": "Rush",
                            "rush_yds": "Ru Yds",
                            "rush_td": "Ru TD",
                            "targets": "Tgt",
                            "receptions": "Rec",
                            "rec_yds": "Rec Yds",
                            "rec_td": "Rec TD",
                            "touches": "Tch",
                            "yards": "Yds",
                            "tds": "TD",
                            "avg_value": "Avg val",
                            "total_value": "Total val",
                        }
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

    with tab_drive:
        _render_halftime_drive_map(
            str(opp or ""),
            live_logs,
            key_prefix=f"{key_prefix}_drive",
        )

    with tab_print:
        st.caption("Printable one-pager — same data as the boards above.")
        st.download_button(
            "Download printable (.md)",
            data=markdown,
            file_name=f"halftime_vs_{report.get('opponent', 'opp')}.md",
            mime="text/markdown",
            use_container_width=True,
            key=f"{key_prefix}_dl_md",
        )
        st.markdown(markdown)



def _end_first_half_action(opponent: str, live_logs: pd.DataFrame, key_prefix: str = "ht") -> None:
    """Primary control: close 1st half and generate the adjustment report."""
    from mesh_engine import (
        end_first_half,
        filter_live_logs,
        load_game_plan,
        load_game_state,
        save_game_state,
    )

    state = load_game_state()
    same_opp = (
        state.get("opponent")
        and str(state.get("opponent")).strip().lower() == opponent.strip().lower()
    )
    phase = state.get("phase") if same_opp else "1st"

    half1 = filter_live_logs(live_logs, opponent=opponent, half=1)
    n_half1 = len(half1)
    n_all = len(filter_live_logs(live_logs, opponent=opponent, half=None))

    if phase in {"halftime", "2nd"}:
        st.success(
            f"1st half closed vs {state.get('opponent')} at {state.get('halftime_at')}. "
            f"Report is below — expand **Halftime / end 1st half** on Live Track, or regenerate."
        )
    else:
        st.warning(
            f"1st-half log: **{n_half1}** plays tagged half=1"
            + (f" ({n_all} total tonight)" if n_all != n_half1 else "")
            + ". End the half when you’re ready for adjustments."
        )

    b1, b2 = st.columns([2, 1])
    gen = b1.button(
        "End 1st Half → Generate Halftime Report",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_btn_end_first_half",
    )
    if b2.button("Reset to 1st half", use_container_width=True, key=f"{key_prefix}_btn_reset_first_half"):
        save_game_state(
            {"opponent": opponent, "phase": "1st", "halftime_at": None, "report_path": None}
        )
        # Pending — applied before lt_half radio on next run
        st.session_state.lt_half_pending = 1
        st.session_state.pop("lt_half_auto_done", None)
        st.session_state.ig_mode = "1st Half"
        st.rerun()

    if gen:
        plan = load_game_plan(opponent)
        board_logs = half1 if not half1.empty else filter_live_logs(live_logs, opponent=opponent)
        board = player_plus_minus_table(board_logs, opponent, by_position=True)
        result = end_first_half(opponent, live_logs, plan, player_board=board)
        st.session_state.lt_half_pending = 2
        st.session_state.ig_mode = "Halftime"
        st.session_state.ht_last_report = result["report"]
        st.session_state.ht_last_md = result["markdown"]
        st.success(
            "1st half ended — halftime report ready. "
            "Expand **Halftime / end 1st half** below or refresh the report there."
        )
        st.rerun()

    # Show latest report when half is closed (handy from Live Track)
    if phase in {"halftime", "2nd"}:
        md = st.session_state.get("ht_last_md")
        if not md:
            md_path = state.get("report_md")
            if md_path:
                try:
                    p = Path(str(md_path))
                    if not p.is_absolute():
                        p = PROJECT_DIR / p
                    if p.exists():
                        md = p.read_text()
                        st.session_state.ht_last_md = md
                except Exception:
                    md = None
        if md:
            with st.expander("Halftime report", expanded=(key_prefix == "lt")):
                report = st.session_state.get("ht_last_report")
                stale = (
                    not isinstance(report, dict)
                    or int(report.get("version") or 0) < 8
                    or any(
                        k not in report
                        for k in (
                            "formations",
                            "formation_play",
                            "formation_vs_look",
                            "scenarios",
                            "blitz",
                            "coverage_tendencies",
                            "xp",
                        )
                    )
                )
                if stale:
                    try:
                        plan = load_game_plan(opponent)
                        half1 = filter_live_logs(live_logs, opponent=opponent, half=1)
                        board_logs = (
                            half1 if not half1.empty else filter_live_logs(live_logs, opponent=opponent)
                        )
                        board = player_plus_minus_table(board_logs, opponent, by_position=True)
                        from mesh_engine import build_halftime_report, format_halftime_report_markdown

                        report = build_halftime_report(
                            opponent, live_logs, plan, player_board=board
                        )
                        md = format_halftime_report_markdown(report)
                        st.session_state.ht_last_report = report
                        st.session_state.ht_last_md = md
                    except Exception:
                        report = st.session_state.get("ht_last_report")
                if isinstance(report, dict) and report.get("opponent"):
                    _render_halftime_report_body(
                        report,
                        md,
                        key_prefix=f"{key_prefix}_viz",
                        live_logs=live_logs,
                    )
                else:
                    st.markdown(md)
                    st.download_button(
                        "Download report (.md)",
                        data=md,
                        file_name=f"halftime_vs_{opponent}.md",
                        mime="text/markdown",
                        key=f"{key_prefix}_dl_quick",
                    )

def _halftime_panel(
    opponent: str,
    plan: dict,
    live_logs: pd.DataFrame,
    offense_df: pd.DataFrame,
    defense_df: pd.DataFrame,
) -> None:
    from mesh_engine import (
        broaden_situation,
        build_halftime_report,
        defense_scout_tendencies,
        filter_live_logs,
        format_halftime_report_markdown,
        live_log_adjustments,
        load_game_state,
        load_scout,
        mesh_rankings,
        offense_scout_tendencies,
        pin_names,
        plan_pin_status,
        save_game_state,
        score_live_calls,
    )

    st.subheader("Halftime — tonight over the plan")
    st.caption("Live evidence wins. Plan items are Confirmed, Unproven, or Kill.")

    _end_first_half_action(opponent, live_logs, key_prefix="igh")

    state = load_game_state()
    report = st.session_state.get("ht_last_report")
    markdown = st.session_state.get("ht_last_md")
    needs_rebuild = (
        report is None
        or str(report.get("opponent", "")).lower() != opponent.strip().lower()
        or int((report or {}).get("version") or 0) < 8
        or "formation_play" not in (report or {})
        or "formation_vs_look" not in (report or {})
        or "scenarios" not in (report or {})
        or "coverage_tendencies" not in (report or {})
        or "xp" not in (report or {})
        or "formations" not in (report or {})
        or "blitz" not in (report or {})
    )
    if needs_rebuild:
        # Rebuild from current logs (includes formation / blitz / coverage / situation)
        half1 = filter_live_logs(live_logs, opponent=opponent, half=1)
        board_logs = half1 if not half1.empty else filter_live_logs(live_logs, opponent=opponent)
        board = player_plus_minus_table(board_logs, opponent, by_position=True)
        report = build_halftime_report(opponent, live_logs, plan, player_board=board)
        markdown = format_halftime_report_markdown(report)
        st.session_state.ht_last_report = report
        st.session_state.ht_last_md = markdown

    _render_halftime_report_body(
        report,
        markdown or format_halftime_report_markdown(report),
        key_prefix="igh",
        live_logs=live_logs,
    )

    if st.button("Start 2nd Half", type="primary", use_container_width=True, key="btn_start_2nd"):
        save_game_state(
            {
                **state,
                "opponent": opponent,
                "phase": "2nd",
            }
        )
        st.session_state.lt_half_pending = 2
        st.success("2nd half started — Live Track defaults to half 2.")
        st.rerun()

    with st.expander("2nd-half mesh + quick log", expanded=False):
        off_scores = score_live_calls(live_logs, "Offense", opponent, half=1)
        def_scores = score_live_calls(live_logs, "Defense", opponent, half=1)
        if off_scores.empty and def_scores.empty:
            off_scores = score_live_calls(live_logs, "Offense", opponent)
            def_scores = score_live_calls(live_logs, "Defense", opponent)
        off_status = plan_pin_status(plan, "offense", off_scores)
        def_status = plan_pin_status(plan, "defense", def_scores)

        down, dist, zone, min_plays = 1, "long", "midfield", 3
        scout_d = load_scout("opponent_defense", opponent)
        scout_o = load_scout("opponent_offense", opponent)
        if scout_d.empty and scout_o.empty:
            scout_d = load_scout("opponent_defense", None)
            scout_o = load_scout("opponent_offense", None)
        off_tend = offense_scout_tendencies(scout_d, down, dist, zone)
        def_tend = defense_scout_tendencies(scout_o, down, dist, zone)
        off_live = live_log_adjustments(
            live_logs, "Offense", down, dist, zone, opponent=opponent, half=None, weight=1.6
        )
        def_live = live_log_adjustments(
            live_logs, "Defense", down, dist, zone, opponent=opponent, half=None, weight=1.6
        )
        vf = 12
        off_matched, _ = broaden_situation(
            offense_df, down, dist, zone, exact_min=vf, down_dist_min=vf, down_min=3
        )
        def_matched, _ = broaden_situation(
            defense_df, down, dist, zone, exact_min=vf, down_dist_min=vf, down_min=3
        )
        off_cfg, def_cfg = UNITS["Offense"], UNITS["Defense"]
        off_base = avg_epa_table(off_matched, off_cfg["secondary_group"], min_plays)
        def_base = avg_epa_table(def_matched, def_cfg["combo_col"], min_plays)
        off_calls = mesh_rankings(
            off_base, off_cfg["secondary_group"], off_tend, off_live, "offense", top_n=3,
            plan_pins=pin_names(plan, "offense"), plan_status=off_status,
            plan_weight=0.08, live_weight=1.8, scout_weight=0.75, season_weight=0.4,
        )
        def_calls = mesh_rankings(
            def_base, def_cfg["combo_col"], def_tend, def_live, "defense", top_n=3,
            plan_pins=pin_names(plan, "defense"), plan_status=def_status,
            plan_weight=0.08, live_weight=1.8, scout_weight=0.75, season_weight=0.4,
        )
        left, right = st.columns(2)
        with left:
            _render_live_recs(
                off_calls, "OFFENSE", "Need more data.", call_col=off_cfg["secondary_group"]
            )
        with right:
            _render_live_recs(
                def_calls, "DEFENSE", "Need more data.", call_col=def_cfg["combo_col"]
            )

        log_unit = st.radio("Unit", ["Offense", "Defense"], horizontal=True, key="ht_log_unit")
        recs = off_calls if log_unit == "Offense" else def_calls
        call_col = off_cfg["secondary_group"] if log_unit == "Offense" else def_cfg["combo_col"]
        rec_options = (
            [getattr(r, call_col) for r in recs.itertuples(index=False)]
            if not recs.empty and call_col in recs.columns
            else []
        )
        h1, h2, h3 = st.columns(3)
        recommended = h1.selectbox(
            "Call", rec_options if rec_options else ["(none)"], key="ht_log_call"
        )
        result = h2.selectbox(
            "Result",
            ["Gain", "No gain", "Incomplete", "TD", "Turnover", "Penalty", "Sack / TFL", "Punt", "Other"],
            key="ht_log_result",
        )
        note = h3.text_input("Note", key="ht_log_note")
        if st.button("Log 2nd-half play", type="primary", use_container_width=True):
            append_live_log(
                {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "opponent": opponent,
                    "half": 2,
                    "unit": log_unit,
                    "down": down,
                    "distance": dist,
                    "field_zone": zone,
                    "situation": situation_label(down, dist, zone),
                    "call": recommended,
                    "result": result,
                    "yards_gained": "",
                    "note": note,
                }
            )
            st.success("Logged.")
            st.rerun()



def _render_create_roster_panel() -> None:
    """Database → Players: roll a new season roster with optional carry-over."""
    _sc = _season_api()
    cur_id = _sc.current_season_id()
    cur_label = _sc.current_season_label()

    with st.expander("Create roster for a new season", expanded=False):
        st.markdown(
            "Archives the current roster under its season, then starts a fresh active list. "
            "Unselected players stay in the archive (past logs / boards still resolve their names) "
            "but won’t show in lineup or ball-carrier picks."
        )
        seasons = list_roster_seasons()
        src_opts = []
        for row in seasons:
            tag = " (active)" if row.get("active") else ""
            src_opts.append(f"{row['id']} — {row['label']} · {row['players']} players{tag}")
        if not src_opts:
            src_opts = [f"{cur_id} — {cur_label} · {len(load_roster())} players (active)"]

        c1, c2 = st.columns(2)
        new_id = c1.text_input(
            "New season id",
            value="",
            placeholder="26-27",
            key="db_create_roster_id",
            help="Short stamp stored on roster / config (e.g. 26-27).",
        ).strip()
        new_label = c2.text_input(
            "New season label",
            value="",
            placeholder="2026-27",
            key="db_create_roster_label",
            help="Shown in the UI (e.g. 2026-27).",
        ).strip()

        src_pick = st.selectbox(
            "Carry players from",
            src_opts,
            index=0,
            key="db_create_roster_src",
        )
        src_id = str(src_pick).split(" — ", 1)[0].strip()
        source_players = load_roster_for_season(src_id)
        if not source_players and src_id == cur_id:
            source_players = load_roster()

        names = [str(p.get("name") or "").strip() for p in source_players if str(p.get("name") or "").strip()]
        b_all, b_none, _ = st.columns([1, 1, 4])
        if b_all.button("Select all", key="db_create_roster_all"):
            st.session_state.db_create_roster_carry = list(names)
            st.rerun()
        if b_none.button("Select none", key="db_create_roster_none"):
            st.session_state.db_create_roster_carry = []
            st.rerun()

        if "db_create_roster_carry" not in st.session_state:
            st.session_state.db_create_roster_carry = list(names)
        else:
            # Drop names that aren't in the current source list
            st.session_state.db_create_roster_carry = [
                n for n in st.session_state.db_create_roster_carry if n in names
            ]

        carry = st.multiselect(
            "Players to keep on the new roster",
            options=names,
            key="db_create_roster_carry",
            help="Leave grads / transfers unchecked — they stay archived under the old season.",
        )
        left = [n for n in names if n not in carry]
        if left:
            st.caption(
                f"**{len(carry)}** carry over · **{len(left)}** stay archived only: "
                + ", ".join(left[:12])
                + ("…" if len(left) > 12 else "")
            )
        else:
            st.caption(f"**{len(carry)}** carry over · nobody left behind.")

        confirm = st.checkbox(
            f"I understand this makes **{new_id or '…'}** the active season "
            f"(current **{cur_label}** roster is archived).",
            key="db_create_roster_confirm",
        )
        if st.button(
            "Create roster",
            type="primary",
            key="db_create_roster_go",
            disabled=not (new_id and confirm),
            use_container_width=True,
        ):
            try:
                result = create_season_roster(
                    new_season_id=new_id,
                    new_season_label=new_label or new_id,
                    carry_names=carry,
                    source_season_id=src_id,
                )
                for k in (
                    "db_create_roster_carry",
                    "db_create_roster_confirm",
                    "db_create_roster_id",
                    "db_create_roster_label",
                    "db_starter_slots",
                ):
                    st.session_state.pop(k, None)
                st.success(
                    f"Roster ready for **{result['new_label']}**. "
                    f"Carried {result['carried']} · left archived {result['left_behind']} "
                    f"(from {result['old_season']})."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_archived_rosters_panel() -> None:
    """Read-only look at prior-season rosters (grads still searchable in history)."""
    _sc = _season_api()
    cur_id = _sc.current_season_id()
    seasons = [r for r in list_roster_seasons() if not r.get("active") and r.get("id") != cur_id]
    if not seasons:
        return
    with st.expander("Archived season rosters", expanded=False):
        st.caption(
            "Prior-year players stay here for history. They do not appear in Live Track lineup picks."
        )
        labels = [f"{r['id']} — {r['label']} ({r['players']})" for r in seasons]
        pick = st.selectbox("Season", labels, key="db_archive_roster_pick")
        sid = str(pick).split(" — ", 1)[0].strip()
        players = load_roster_for_season(sid)
        if not players:
            st.write("No players stored for that season.")
            return
        for p in players:
            pos = ", ".join(p.get("positions") or [])
            st.write(f"- **{p.get('name')}** · {pos}")


def _render_schedule_tab(offense_df: pd.DataFrame) -> None:
    """Database → Schedule: edit opponents, map Hudl games, add playoff teams."""
    from schedule import (
        add_schedule_game,
        apply_schedule_to_db,
        detected_hudl_games,
        ensure_prior_schedule_archived,
        list_schedule_season_ids,
        load_schedule,
        save_schedule,
        start_new_season_schedule,
    )

    tc = _season_api()
    cur = tc.current_season_id()
    label = tc.current_season_label()

    # Preserve prior schedule file once when rolling years
    try:
        archived = ensure_prior_schedule_archived()
        if archived:
            st.caption(f"Prior schedule kept at `{archived.name}`.")
    except Exception:
        pass

    st.subheader(f"Schedule · {label}")
    st.caption(
        "Hudl assigns **game 1, 2, 3…** in film order (PLAY # drops). "
        "This table says which opponent each game_id is. "
        "Add playoff teams as new rows when the bracket opens."
    )

    season_ids = list_schedule_season_ids()
    if cur not in season_ids:
        season_ids = [cur] + season_ids
    edit_season = st.selectbox(
        "Edit schedule for",
        season_ids,
        index=season_ids.index(cur) if cur in season_ids else 0,
        key="db_sched_season",
    )
    is_active = edit_season == cur or tc.is_current_season_value(edit_season)
    if not is_active:
        st.info(
            f"Editing archived **{edit_season}**. Live Track still uses the active "
            f"**{label}** schedule (`opponents.csv`)."
        )

    sched = load_schedule(edit_season if not is_active else None)
    editor_height = min(42 + 36 * max(len(sched), 1), 480)
    edited = st.data_editor(
        sched if not sched.empty else pd.DataFrame(
            [{"game_id": 1, "opponent": "", "notes": ""}]
        ),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        height=editor_height,
        column_config={
            "game_id": st.column_config.NumberColumn(
                "Game #",
                help="Must match Hudl game order (1 = first game in season.xlsx).",
                min_value=1,
                step=1,
                width="small",
            ),
            "opponent": st.column_config.TextColumn("Opponent", width="medium"),
            "notes": st.column_config.TextColumn(
                "Notes",
                help='e.g. "Playoffs", "Home", week label',
                width="medium",
            ),
        },
        key=f"db_sched_editor_{edit_season}",
    )

    b1, b2, b3 = st.columns(3)
    if b1.button("Save schedule", type="primary", key="db_sched_save"):
        path = save_schedule(edited, None if is_active else edit_season)
        st.success(f"Saved {path.name}")
        st.rerun()
    if b2.button("Apply labels to film DB", key="db_sched_apply"):
        # Save first so disk + DB stay aligned
        save_schedule(edited, None if is_active else edit_season)
        n = apply_schedule_to_db(edited, None if is_active else edit_season)
        st.success(f"Updated {n:,} play rows with opponent labels.")
        st.cache_data.clear()
        st.rerun()
    if b3.button("Load from 25-26 archive", key="db_sched_load_prior") and is_active:
        prior = load_schedule("25-26")
        if prior.empty:
            # try config prior_id
            pid = str(tc.season_block().get("prior_id") or "").strip()
            prior = load_schedule(pid) if pid else prior
        if prior.empty:
            st.warning("No archived schedule found.")
        else:
            save_schedule(prior, None)
            st.success(f"Loaded {len(prior)} games from archive into active schedule.")
            st.rerun()
    st.caption("Apply patches Game Review labels without re-importing Hudl.")

    st.markdown("##### Add a game (playoffs / makeup)")
    with st.form("db_sched_add_game", clear_on_submit=True):
        f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
        opp = f1.text_input("Opponent", placeholder="Playoff opponent")
        notes = f2.text_input("Notes", value="Playoffs")
        playoff = f3.checkbox("Playoff", value=True)
        added = f4.form_submit_button("Add", type="primary", use_container_width=True)
        if added:
            try:
                base = load_schedule(edit_season if not is_active else None)
                updated = add_schedule_game(base, opp, notes=notes, playoff=playoff)
                save_schedule(updated, None if is_active else edit_season)
                st.success(f"Added {opp.strip()} as game {int(updated['game_id'].max())}.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.markdown("##### Hudl games → schedule")
    st.caption(
        "After `refresh_all.py`, each film block is a game_id. "
        "Assign the right opponent here (or edit the table above), then **Apply labels**."
    )
    detected = detected_hudl_games(edit_season if not is_active else None)
    if detected.empty:
        st.write("No Hudl games in the DB for this season yet.")
    else:
        # Merge schedule names for convenience
        sched_now = load_schedule(edit_season if not is_active else None)
        name_by_id = {
            int(r.game_id): str(r.opponent)
            for r in sched_now.itertuples(index=False)
        } if not sched_now.empty else {}
        show = detected.copy()
        show["schedule_opponent"] = show["game_id"].map(
            lambda g: name_by_id.get(int(g), "")
        )
        st.dataframe(
            show.rename(
                columns={
                    "game_id": "Game #",
                    "plays": "Plays",
                    "opponent": "DB label",
                    "game_notes": "DB notes",
                    "schedule_opponent": "Schedule",
                }
            ),
            use_container_width=True,
            hide_index=True,
            height=min(42 + 32 * len(show), 360),
        )
        mismatch = show[
            show["schedule_opponent"].astype(str).str.strip().ne("")
            & show["opponent"].astype(str).str.strip().ne("")
            & (
                show["schedule_opponent"].astype(str).str.strip().str.lower()
                != show["opponent"].astype(str).str.strip().str.lower()
            )
        ]
        if not mismatch.empty:
            st.warning(
                f"{len(mismatch)} game(s) have schedule ≠ DB label — hit **Apply labels to film DB**."
            )

    with st.expander("Fix: film stuck on wrong season", expanded=False):
        st.caption(
            "If last year’s Hudl was imported as season.xlsx while the active year "
            "already rolled forward, those snaps are stamped `current` and show under "
            f"**{label}**. This moves `current` → prior season "
            f"**{tc.season_block().get('prior_id') or 'prior'}**."
        )
        if st.button("Move 'current' film to prior season", key="db_sched_migrate_current"):
            try:
                from schedule import migrate_legacy_current_to_prior

                result = migrate_legacy_current_to_prior()
                st.cache_data.clear()
                st.success(
                    f"Restamped {result['updated']:,} rows → {result['prior_id']} "
                    f"(relabeled {result['labeled']:,})."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with st.expander("Start a new season schedule", expanded=False):
        st.markdown(
            "Archives the current `opponents.csv` under the old season id, "
            "advances the active season in team config, and opens a fresh schedule "
            "(blank or copy)."
        )
        n1, n2 = st.columns(2)
        new_id = n1.text_input("New season id", placeholder="27-28", key="db_sched_new_id")
        new_lab = n2.text_input(
            "Label", placeholder="2027-28", key="db_sched_new_label"
        )
        mode = st.radio(
            "New schedule",
            ["Blank (add teams as you go)", "Copy current schedule"],
            horizontal=True,
            key="db_sched_new_mode",
        )
        confirm = st.checkbox(
            f"Make **{new_id or '…'}** the active season and archive **{cur}** schedule.",
            key="db_sched_new_confirm",
        )
        if st.button(
            "Create season schedule",
            type="primary",
            disabled=not (new_id.strip() and confirm),
            key="db_sched_new_go",
        ):
            try:
                result = start_new_season_schedule(
                    new_season_id=new_id.strip(),
                    new_season_label=new_lab.strip() or new_id.strip(),
                    blank=mode.startswith("Blank"),
                )
                try:
                    _is_current_season_mask.clear()
                except Exception:
                    pass
                st.success(
                    f"Active season is now **{result['new_season']}** "
                    f"({result['games']} games on the new schedule). "
                    f"Prior schedule archived as opponents_{result['old_season']}.csv."
                )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def database_page(offense_df: pd.DataFrame) -> None:
    """Edit roster, starters, and offense/film tags away from Live Track."""
    from mesh_engine import load_live_log
    current_season_label = _season_api().current_season_label

    st.header("Database")
    st.caption(
        f"Build the booth dictionary here — Live Track stays simple for game night. "
        f"Roster & starters are scoped to **{current_season_label()}**."
    )
    live_logs = load_live_log()
    tab_players, tab_starters, tab_schedule, tab_offense, tab_film = st.tabs(
        ["Players", "Starters", "Schedule", "Offense tags", "Film tags"]
    )

    with tab_players:
        st.subheader(f"Roster · {current_season_label()}")
        st.caption(
            "Active roster drives lineup / ball-carrier picks. "
            "Edit the table below, then **Save roster**. "
            "Delete a row to drop someone from this season only."
        )
        roster = load_roster()

        with st.form("db_roster_add_form", clear_on_submit=True):
            a1, a2, a3, a4 = st.columns([2.2, 2.2, 1, 1.1])
            new_name = a1.text_input("Add player", placeholder="Name")
            new_positions = a2.multiselect(
                "Positions",
                ROSTER_POSITIONS,
                default=["WR"],
            )
            is_starter = a3.checkbox("Starter", value=False)
            add_clicked = a4.form_submit_button("Add", type="primary", use_container_width=True)
            if add_clicked and new_name.strip():
                name = new_name.strip()
                positions = new_positions or ["Other"]
                updated = False
                for p in roster:
                    if p.get("name", "").lower() == name.lower():
                        p["name"] = name
                        p["positions"] = list(dict.fromkeys(positions))
                        p["starter"] = bool(is_starter)
                        updated = True
                        break
                if not updated:
                    roster.append(
                        {
                            "name": name,
                            "positions": positions,
                            "starter": bool(is_starter),
                        }
                    )
                save_roster(roster)
                st.rerun()

        if not roster:
            st.info("No players yet — add one above.")
        else:
            rows = [
                {
                    "Name": str(p.get("name") or ""),
                    "Positions": ", ".join(p.get("positions") or ["Other"]),
                    "Starter": bool(p.get("starter")),
                }
                for p in roster
            ]
            editor_height = min(38 + 35 * max(len(rows), 1), 420)
            edited = st.data_editor(
                pd.DataFrame(rows),
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                height=editor_height,
                column_config={
                    "Name": st.column_config.TextColumn("Name", width="medium", required=True),
                    "Positions": st.column_config.TextColumn(
                        "Positions",
                        width="large",
                        help="Comma-separated (WR, RB, TE, …)",
                    ),
                    "Starter": st.column_config.CheckboxColumn("Starter", width="small"),
                },
                key="db_roster_editor",
            )
            s1, s2 = st.columns([1, 3])
            if s1.button("Save roster", type="primary", key="db_roster_save_table"):
                cleaned: list[dict] = []
                seen: set[str] = set()
                for row in edited.to_dict(orient="records"):
                    name = str(row.get("Name") or "").strip()
                    if not name:
                        continue
                    key = name.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    raw_pos = str(row.get("Positions") or "").strip()
                    parts = [x.strip().upper() for x in raw_pos.replace(";", ",").split(",") if x.strip()]
                    positions = [p for p in parts if p in ROSTER_POSITIONS] or ["Other"]
                    cleaned.append(
                        {
                            "name": name,
                            "positions": list(dict.fromkeys(positions)),
                            "starter": bool(row.get("Starter")),
                        }
                    )
                save_roster(cleaned)
                st.success(f"Saved {len(cleaned)} players.")
                st.rerun()
            s2.caption(f"{len(roster)} players · positions as comma-separated tags")

        _render_create_roster_panel()
        _render_archived_rosters_panel()

    with tab_schedule:
        _render_schedule_tab(offense_df)

    with tab_starters:
        st.subheader(f"Starting lineup · {current_season_label()}")
        st.caption(
            "Assign starters to each spot, then use **Load starters** on Live Track → Lineup. "
            "Saved under the current season so next year’s starters stay separate."
        )
        roster = load_roster()
        if not roster:
            st.info("Add players first.")
        else:
            saved = load_starters().get("offense") or {}
            # Editable copy in session
            if "db_starter_slots" not in st.session_state:
                st.session_state.db_starter_slots = dict(saved)
            slots = dict(st.session_state.db_starter_slots)
            slot_list = (
                list(FORMATION_OFFENSE_LINE)
                + list(FORMATION_OFFENSE_BACK)
            )
            for slot in slot_list:
                eligible = [p["name"] for p in roster_eligible(roster, slot["eligible"])]
                opts = [""] + eligible
                cur = slots.get(slot["id"], "")
                if cur and cur not in opts:
                    opts.insert(1, cur)
                pick = st.selectbox(
                    f"{slot['label']} ({slot['id']})",
                    opts,
                    index=opts.index(cur) if cur in opts else 0,
                    key=f"db_start_{slot['id']}",
                )
                if pick:
                    slots[slot["id"]] = pick
                elif slot["id"] in slots:
                    slots.pop(slot["id"], None)
            st.session_state.db_starter_slots = slots
            b1, b2 = st.columns(2)
            if b1.button("Save starters", type="primary", use_container_width=True, key="db_save_starters"):
                save_starters({"offense": slots})
                # Mirror starter flags on roster
                starter_names = set(slots.values())
                for p in roster:
                    p["starter"] = p.get("name") in starter_names
                save_roster(roster)
                st.success("Starters saved.")
                st.rerun()
            if b2.button("Load from Live Track lineup", use_container_width=True, key="db_from_live"):
                st.session_state.db_starter_slots = dict(get_formation_slots())
                st.rerun()

    with tab_offense:
        st.subheader("Formations · variants · motions · plays")
        booth = load_live_favorites()
        _render_favorites_editor(
            live_logs if live_logs is not None else pd.DataFrame(),
            opponent=st.session_state.get("lt_page_opponent") or "Unknown",
            form_opts=list(booth.get("formations") or []),
            play_opts=[
                p
                for t in PLAY_TYPES
                for p in (booth.get("plays") or {}).get(t) or []
            ],
            motion_opts=list(booth.get("motions") or []),
            offense_df=offense_df,
        )

    with tab_film:
        st.subheader("Fronts & coverages")
        ensure_default_film_tags()
        tags = _load_learned_tags()
        f1, f2 = st.columns(2)
        with f1:
            st.markdown("**Fronts**")
            fronts = list(tags.get("def_front") or [])
            new_f = st.text_input("Add front", key="db_add_front")
            if st.button("Add front", key="db_btn_front") and new_f.strip():
                learn_live_tag("def_front", new_f.strip())
                st.rerun()
            for i, name in enumerate(fronts):
                st.write(f"· {name}")
        with f2:
            st.markdown("**Coverages**")
            covs = list(tags.get("coverage") or [])
            new_c = st.text_input("Add coverage", key="db_add_cov")
            if st.button("Add coverage", key="db_btn_cov") and new_c.strip():
                learn_live_tag("coverage", new_c.strip())
                st.rerun()
            for name in covs:
                st.write(f"· {name}")


def _shared_mode_enabled() -> bool:
    """Booth PIN + multi-device mode (LAN shared flag or Streamlit Community Cloud)."""
    import os

    flag = os.environ.get("FOOTBALL_EPA_SHARED", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    # Streamlit Community Cloud
    if os.environ.get("STREAMLIT_RUNTIME_ENV", "").strip().lower() == "cloud":
        return True
    try:
        secret = st.secrets.get("FOOTBALL_EPA_SHARED", "")
        if str(secret).strip().lower() in {"1", "true", "yes"}:
            return True
    except Exception:
        pass
    return False


def _require_booth_pin() -> bool:
    """Gate shared LAN sessions. Returns True if unlocked."""
    if not _shared_mode_enabled():
        return True
    if st.session_state.get("booth_unlocked"):
        return True
    from team_config import booth_pin, load_team_config

    pin = booth_pin()
    if not pin:
        return True
    st.title("Football EPA — Booth unlock")
    st.caption(
        f"Shared booth for {load_team_config().get('team_name', 'Home')} "
        "(laptop + iPad on one link, or same Wi‑Fi). "
        "Enter the booth PIN (change in data/team_config.json)."
    )
    entered = st.text_input("Booth PIN", type="password", key="booth_pin_input")
    if st.button("Unlock booth", type="primary") and entered == pin:
        st.session_state.booth_unlocked = True
        st.rerun()
    if entered and entered != pin:
        st.error("Incorrect PIN")
    st.stop()
    return False


def _render_tagger_waiting_for_main() -> None:
    """Taggers never upload the DB — Main does it once on the shared server."""
    st.markdown('<p class="live-title">Booth not ready yet</p>', unsafe_allow_html=True)
    st.info(
        "The **Main** device still needs to upload the season database once. "
        "You don’t need to upload anything on this phone."
    )
    st.caption(
        "On Main: Home (or Setup) → upload `football.db` → Save. "
        "Then tap Check again here."
    )
    if st.button("Check again", type="primary", key="tagger_wait_refresh"):
        st.cache_data.clear()
        st.rerun()


def _epa_db_ready(offense_df, defense_df) -> bool:
    return not (
        (offense_df is None or getattr(offense_df, "empty", True))
        and (defense_df is None or getattr(defense_df, "empty", True))
    )


def _render_first_run_wizard() -> None:
    """CP5 first-run / empty-data onboarding (Main only — works on Streamlit Cloud via uploads)."""
    st.title("Football EPA — Setup")
    st.markdown(
        """
**Main device only** — upload the season database once.  
Taggers never do this; they join with the invite link after Main is ready.

**Fastest (Streamlit Cloud)**  
Upload your local `data/football.db` below.

**Or** upload Hudl `season.xlsx` / `season_25-26.xlsx` and refresh.
"""
    )

    db_path = PROJECT_DIR / "data" / "football.db"
    exports = PROJECT_DIR / "data" / "hudl_exports"
    exports.mkdir(parents=True, exist_ok=True)
    season = exports / "season.xlsx"

    st.subheader("1 · Upload database (fast)")
    st.caption(
        "On your Mac this file is usually at: "
        "`…/football-epa/data/football.db`"
    )
    db_up = st.file_uploader(
        "football.db",
        type=["db", "sqlite", "sqlite3"],
        key="setup_upload_db",
        help="Finder → football-epa → data → football.db",
    )
    if db_up is not None and st.button("Save database", type="primary", key="setup_save_db"):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(db_up.getvalue())
        st.success(f"Saved {db_path.name} ({len(db_up.getvalue()):,} bytes).")
        st.cache_data.clear()
        st.rerun()

    st.subheader("2 · Or upload Hudl season film")
    xlsx_up = st.file_uploader(
        "season.xlsx / season_YY-YY.xlsx",
        type=["xlsx"],
        key="setup_upload_xlsx",
        accept_multiple_files=True,
    )
    if xlsx_up:
        for f in xlsx_up:
            name = str(f.name or "season.xlsx")
            dest = exports / name
            dest.write_bytes(f.getvalue())
            st.write(f"Saved `{dest.name}`")
        if not season.exists():
            candidates = sorted(
                (
                    p
                    for p in exports.glob("season*.xlsx")
                    if not p.name.startswith("~$")
                ),
                key=lambda p: p.stat().st_mtime,
            )
            if candidates:
                season.write_bytes(candidates[-1].read_bytes())
                st.caption(f"Also copied → season.xlsx from {candidates[-1].name}")

    st.write("season.xlsx:", "✅ found" if season.exists() else "❌ missing")
    st.write("football.db:", "✅ found" if db_path.exists() else "❌ missing")
    st.caption(
        "Note: Streamlit Cloud storage is temporary — re-upload after a full redeploy, "
        "or keep a local copy of football.db."
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Refresh database from Hudl", key="setup_refresh"):
            if not season.exists() and not list(exports.glob("season*.xlsx")):
                st.error("Upload a season.xlsx (or season_*.xlsx) first.")
            else:
                try:
                    from refresh_all import run_refresh

                    if not season.exists():
                        alts = sorted(
                            p
                            for p in exports.glob("season*.xlsx")
                            if not p.name.startswith("~$")
                        )
                        if alts:
                            season.write_bytes(alts[-1].read_bytes())
                    with st.spinner("Running refresh_all (may take a minute)…"):
                        run_refresh()
                    st.success("Refresh complete.")
                    st.cache_data.clear()
                    st.rerun()
                except SystemExit as exc:
                    st.error(f"Refresh stopped: {exc}")
                except Exception as exc:
                    st.error(f"Refresh failed: {exc}")
    with c2:
        if st.button("I added files — try loading again", type="primary", key="setup_reload"):
            st.cache_data.clear()
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="Football EPA", page_icon="🏈", layout="wide")
    inject_styles()
    _require_booth_pin()

    from booth_stations import (
        focus_summary,
        is_tagger_station,
        resolve_booth_station,
        resolve_tag_focuses,
    )

    # First question: Main or Tagger (bookmarks skip this)
    _render_booth_role_gate()

    booth_station = resolve_booth_station(st.session_state, st.query_params)
    tagger = str(st.session_state.get("booth_role") or "").lower() == "tagger" or (
        is_tagger_station(booth_station) and bool(st.session_state.get("booth_station_locked"))
    )
    focuses = resolve_tag_focuses(st.session_state, st.query_params, booth_station)

    if not tagger:
        _booth_switch_role_control()

    if tagger:
        # Sidebar hidden via CSS on Live Track — no page nav
        page = "Live Track"
    else:
        pages = [
            "Home",
            "Live Track",
            "Game Review",
            "Database",
            "Game Plan",
            "Opponent Scout",
        ]
        # Deep-link from Home → Live Track; default Main into Live Track for booth speed
        pending = st.session_state.pop("lt_nav_page", None)
        if pending in pages:
            st.session_state.main_page_radio = pending
        if "main_page_radio" not in st.session_state:
            st.session_state.main_page_radio = "Live Track"
        page = st.sidebar.radio(
            "Page",
            pages,
            key="main_page_radio",
        )
        if _shared_mode_enabled():
            import os

            public = str(os.environ.get("BOOTH_PUBLIC_URL") or "").strip()
            st.sidebar.caption("Main · full booth")
            if public:
                st.sidebar.caption(f"Link: {public}")

    offense_df = load_plays("Offense")
    # Live Track (and taggers) only need offense EPA — skip Defense SQLite load
    if tagger or page == "Live Track":
        defense_df = pd.DataFrame()
    else:
        defense_df = load_plays("Defense")
    db_ready = _epa_db_ready(offense_df, defense_df)

    # Taggers never upload — wait for Main's shared database
    if tagger and not db_ready:
        _render_tagger_waiting_for_main()
        return

    # First-run setup is Main-only (Home / Database also allow setup)
    if (not tagger) and (not db_ready) and page not in {"Database", "Home"}:
        _render_first_run_wizard()
        return

    if page == "Home":
        _render_home_page()
        return

    if page == "Live Track":
        if not tagger:
            st.title("Football EPA")
        if offense_df.empty:
            if tagger:
                _render_tagger_waiting_for_main()
            else:
                st.error("No offense EPA data found. Upload the database on **Home**.")
            return
        if not tagger:
            st.sidebar.markdown("---")
            st.sidebar.markdown(f"**{len(offense_df):,}** offense plays")
            if "game_id" in offense_df.columns:
                st.sidebar.markdown(f"**{offense_df['game_id'].nunique()}** games")
        live_track_page(offense_df, defense_df)
        return

    if page == "Game Review":
        st.title("Football EPA")
        if offense_df.empty:
            st.error("No offense EPA data found. Run `python refresh_all.py` first.")
            return
        game_review_page(offense_df, UNITS["Offense"])
        return

    if page == "Database":
        st.title("Football EPA")
        if offense_df.empty and defense_df.empty:
            _render_first_run_wizard()
            st.markdown("---")
        database_page(offense_df if not offense_df.empty else pd.DataFrame())
        return

    if page == "Game Plan":
        st.title("Football EPA")
        if offense_df.empty and defense_df.empty:
            st.error("No EPA data found. Run `python refresh_all.py` first.")
            return
        # Offense-primary plan board (defense pins hidden for now)
        if "gp_unit" not in st.session_state:
            st.session_state.gp_unit = "Offense"
        game_plan_page(offense_df, defense_df)
        return

    if page == "Opponent Scout":
        st.title("Football EPA")
        scout_tendencies_page()
        return


if __name__ == "__main__":
    main()

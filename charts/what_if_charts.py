"""Plotly charts for the What-If Simulator.

DataFrames in, Figures out (no Streamlit). The delta charts colour bars by
direction via the semantic constants in ``config`` so the green/red meaning
lives in one place.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from config import COLOR_NEGATIVE, COLOR_NEUTRAL, COLOR_POSITIVE, PLOTLY_TEMPLATE


def standings_comparison_bar(
    original: pd.DataFrame,
    modified: pd.DataFrame,
    top_n: int = 10,
) -> go.Figure:
    """Grouped Original-vs-What-If points bars for the top ``top_n`` drivers.

    Each driver's pair is coloured by whether their total rose, fell, or held.
    """
    fig = go.Figure()
    for driver in original.head(top_n)["driver_name"].tolist():
        orig_val = original.loc[original["driver_name"] == driver, "total_points"].values
        mod_val = modified.loc[modified["driver_name"] == driver, "total_points"].values
        o = orig_val[0] if len(orig_val) else 0
        m = mod_val[0] if len(mod_val) else 0
        color = COLOR_POSITIVE if m > o else COLOR_NEGATIVE if m < o else COLOR_NEUTRAL
        fig.add_trace(go.Bar(name=driver, x=["Original", "What-If"], y=[o, m], marker_color=color))
    fig.update_layout(template=PLOTLY_TEMPLATE, barmode="group", height=450, yaxis_title="Points")
    return fig


def position_change_bar(
    change_df: pd.DataFrame,
    xaxis_title: str,
    height: int = 500,
) -> go.Figure:
    """Horizontal bar of position changes (positive = moved up, green).

    Expects columns ``Driver`` and ``Change`` (signed int).
    """
    fig = go.Figure(go.Bar(
        x=change_df["Change"],
        y=change_df["Driver"],
        orientation="h",
        marker_color=[COLOR_POSITIVE if c > 0 else COLOR_NEGATIVE for c in change_df["Change"]],
        text=change_df["Change"].apply(lambda x: f"+{x}" if x > 0 else str(x)),
        textposition="auto",
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        yaxis=dict(autorange="reversed"),
        xaxis_title=xaxis_title,
        height=height,
    )
    return fig

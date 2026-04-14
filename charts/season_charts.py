"""Plotly charts for the Season Tracker page."""

import plotly.graph_objects as go
import pandas as pd

from config import PLOTLY_TEMPLATE, TEAM_COLORS

# Fallback colors for teams not in the config
_FALLBACK_COLORS = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
    "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
]


def _build_color_map(df: pd.DataFrame) -> dict[str, str]:
    """Map each driver label to their team color."""
    color_map = {}
    fallback_idx = 0
    # Get unique driver/constructor pairs (use last known constructor per driver)
    for driver in df["driver"].unique():
        driver_rows = df[df["driver"] == driver]
        constructor_id = driver_rows.iloc[-1].get("constructor_id", "")
        if constructor_id and constructor_id in TEAM_COLORS:
            color_map[driver] = TEAM_COLORS[constructor_id]
        else:
            color_map[driver] = _FALLBACK_COLORS[fallback_idx % len(_FALLBACK_COLORS)]
            fallback_idx += 1
    return color_map


def position_progression_chart(df: pd.DataFrame) -> go.Figure:
    """Line chart showing championship position across rounds (P1 at top)."""
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    color_map = _build_color_map(df)

    fig = go.Figure()
    for driver in df["driver"].unique():
        ddf = df[df["driver"] == driver].sort_values("round")
        fig.add_trace(go.Scatter(
            x=ddf["round"],
            y=ddf["position"],
            name=driver,
            mode="lines+markers",
            line=dict(color=color_map.get(driver, "#AAAAAA"), width=2),
            marker=dict(size=6),
        ))

    fig.update_yaxes(autorange="reversed", dtick=1)
    fig.update_xaxes(dtick=1)
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Round",
        yaxis_title="Championship Position",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=-0.3),
        hovermode="x unified",
    )
    return fig


def points_accumulation_chart(df: pd.DataFrame) -> go.Figure:
    """Area chart showing cumulative points across rounds."""
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    color_map = _build_color_map(df)

    df = df.sort_values(["driver", "round"])
    df["cum_points"] = df.groupby("driver")["points"].cumsum()

    fig = go.Figure()
    for driver in df["driver"].unique():
        ddf = df[df["driver"] == driver]
        color = color_map.get(driver, "#AAAAAA")
        fig.add_trace(go.Scatter(
            x=ddf["round"],
            y=ddf["cum_points"],
            name=driver,
            mode="lines",
            line=dict(color=color, width=2),
        ))

    fig.update_xaxes(dtick=1)
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Round",
        yaxis_title="Cumulative Points",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=-0.3),
        hovermode="x unified",
    )
    return fig

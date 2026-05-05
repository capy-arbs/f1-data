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
    """Map each driver label to their team color.

    Keyed by constructor first so teammates always share a color — both
    when the team is in TEAM_COLORS and when it falls back. The previous
    implementation iterated drivers and incremented the fallback index per
    driver, which gave teammates different fallback colors (e.g. Cadillac's
    two cars showing up as different colors on the same chart).
    """
    team_color: dict[str, str] = {}
    fallback_idx = 0
    color_map: dict[str, str] = {}

    # First pass: build a stable team -> color mapping.
    for constructor_id in df.dropna(subset=["constructor_id"])["constructor_id"].unique():
        if constructor_id in TEAM_COLORS:
            team_color[constructor_id] = TEAM_COLORS[constructor_id]
        else:
            team_color[constructor_id] = _FALLBACK_COLORS[fallback_idx % len(_FALLBACK_COLORS)]
            fallback_idx += 1

    # Second pass: each driver inherits their (last-known) team's color.
    for driver in df["driver"].unique():
        constructor_id = df[df["driver"] == driver].iloc[-1].get("constructor_id", "")
        color_map[driver] = team_color.get(constructor_id, "#AAAAAA")
    return color_map


def _drivers_grouped_by_team(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Return [(driver, constructor_id), ...] sorted so teammates are adjacent.

    Used so the unified hover tooltip lists drivers from the same team next to
    each other (Antonelli + Russell together, etc.) instead of in arbitrary
    appearance order, and so legend grouping is consistent across charts.
    """
    pairs = (
        df.groupby("driver")["constructor_id"]
        .last()
        .reset_index()
    )
    pairs = pairs.sort_values(["constructor_id", "driver"])
    return list(zip(pairs["driver"], pairs["constructor_id"]))


def position_progression_chart(df: pd.DataFrame) -> go.Figure:
    """Line chart showing championship position across rounds (P1 at top)."""
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    color_map = _build_color_map(df)

    fig = go.Figure()
    for driver, constructor_id in _drivers_grouped_by_team(df):
        ddf = df[df["driver"] == driver].sort_values("round")
        fig.add_trace(go.Scatter(
            x=ddf["round"],
            y=ddf["position"],
            name=driver,
            mode="lines+markers",
            line=dict(color=color_map.get(driver, "#AAAAAA"), width=2),
            marker=dict(size=6),
            legendgroup=constructor_id or driver,
            legendgrouptitle_text=constructor_id.replace("_", " ").title() if constructor_id else None,
        ))

    fig.update_yaxes(autorange="reversed", dtick=1)
    fig.update_xaxes(dtick=1)
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Round",
        yaxis_title="Championship Position",
        height=580,
        legend=dict(orientation="h", yanchor="bottom", y=-0.35, groupclick="togglegroup"),
        hovermode="x unified",
        # Compact hover so all 20+ drivers fit on screen without clipping.
        hoverlabel=dict(
            font_size=10,
            namelength=10,
            bgcolor="rgba(15,16,21,0.96)",
            bordercolor="#25262F",
            align="left",
        ),
    )
    return fig


def points_accumulation_chart(df: pd.DataFrame) -> go.Figure:
    """Cumulative points across rounds, grouped so teammates appear together in hover."""
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    color_map = _build_color_map(df)

    df = df.sort_values(["driver", "round"])
    df["cum_points"] = df.groupby("driver")["points"].cumsum()

    fig = go.Figure()
    for driver, constructor_id in _drivers_grouped_by_team(df):
        ddf = df[df["driver"] == driver]
        color = color_map.get(driver, "#AAAAAA")
        fig.add_trace(go.Scatter(
            x=ddf["round"],
            y=ddf["cum_points"],
            name=driver,
            mode="lines",
            line=dict(color=color, width=2),
            legendgroup=constructor_id or driver,
            legendgrouptitle_text=constructor_id.replace("_", " ").title() if constructor_id else None,
        ))

    fig.update_xaxes(dtick=1)
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Round",
        yaxis_title="Cumulative Points",
        height=580,
        legend=dict(orientation="h", yanchor="bottom", y=-0.35, groupclick="togglegroup"),
        hovermode="x unified",
        # Compact hover so all 20+ drivers fit on screen without clipping.
        hoverlabel=dict(
            font_size=10,
            namelength=10,
            bgcolor="rgba(15,16,21,0.96)",
            bordercolor="#25262F",
            align="left",
        ),
    )
    return fig

"""Plotly charts for Head-to-Head and Historical pages."""

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from config import PLOTLY_TEMPLATE


_DEFAULT_D1 = "#E10600"
_DEFAULT_D2 = "#3671C6"


def season_comparison_bar(d1_stats: pd.DataFrame, d2_stats: pd.DataFrame,
                          d1_name: str, d2_name: str,
                          d1_color: str | None = None,
                          d2_color: str | None = None) -> go.Figure:
    """Grouped bar chart comparing two drivers' points per season.

    ``d1_color`` / ``d2_color`` should be the drivers' current team colours
    so the chart reads as "Ferrari vs McLaren" not "red vs blue."
    """
    if d1_stats.empty and d2_stats.empty:
        return go.Figure()

    c1 = d1_color or _DEFAULT_D1
    c2 = d2_color or _DEFAULT_D2

    fig = go.Figure()
    fig.add_trace(go.Bar(name=d1_name, x=d1_stats["season"], y=d1_stats["points"], marker_color=c1))
    fig.add_trace(go.Bar(name=d2_name, x=d2_stats["season"], y=d2_stats["points"], marker_color=c2))
    fig.update_layout(
        barmode="group",
        template=PLOTLY_TEMPLATE,
        xaxis_title="Season",
        yaxis_title="Points",
        height=450,
    )
    return fig


def cumulative_wins_chart(d1_stats: pd.DataFrame, d2_stats: pd.DataFrame,
                          d1_name: str, d2_name: str,
                          d1_color: str | None = None,
                          d2_color: str | None = None) -> go.Figure:
    """Line chart of cumulative wins over seasons."""
    fig = go.Figure()
    for stats, name, color in [
        (d1_stats, d1_name, d1_color or _DEFAULT_D1),
        (d2_stats, d2_name, d2_color or _DEFAULT_D2),
    ]:
        if stats.empty:
            continue
        s = stats.copy()
        s["cum_wins"] = s["wins"].cumsum()
        fig.add_trace(go.Scatter(
            x=s["season"], y=s["cum_wins"],
            name=name, mode="lines+markers",
            line=dict(color=color, width=3),
        ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Season",
        yaxis_title="Cumulative Wins",
        height=450,
    )
    return fig


def h2h_qualifying_chart(h2h_df: pd.DataFrame, d1_name: str, d2_name: str,
                         d1_color: str | None = None,
                         d2_color: str | None = None) -> go.Figure:
    """Show qualifying head-to-head between teammates."""
    if h2h_df.empty:
        return go.Figure()

    d1_ahead = (h2h_df["d1_grid"] < h2h_df["d2_grid"]).sum()
    d2_ahead = (h2h_df["d2_grid"] < h2h_df["d1_grid"]).sum()

    fig = go.Figure(go.Bar(
        x=[d1_ahead, d2_ahead],
        y=[d1_name, d2_name],
        orientation="h",
        marker_color=[d1_color or _DEFAULT_D1, d2_color or _DEFAULT_D2],
        text=[d1_ahead, d2_ahead],
        textposition="auto",
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Races Ahead in Qualifying",
        height=200,
    )
    return fig


def career_comparison_radar(df: pd.DataFrame) -> go.Figure:
    """Radar chart comparing multiple drivers across key metrics."""
    if df.empty:
        return go.Figure()

    categories = ["win_pct", "podium_pct", "points_per_race"]
    cat_labels = ["Win %", "Podium %", "Points/Race"]
    colors = ["#E10600", "#3671C6", "#27F4D2", "#FF8000", "#229971"]

    fig = go.Figure()
    for i, (_, row) in enumerate(df.iterrows()):
        name = f"{row['given_name']} {row['family_name']}"
        values = [row.get(c, 0) for c in categories]
        values.append(values[0])  # close the polygon
        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=cat_labels + [cat_labels[0]],
            fill="toself",
            name=name,
            line_color=colors[i % len(colors)],
            opacity=0.6,
        ))

    fig.update_layout(
        polar=dict(bgcolor="rgba(0,0,0,0)"),
        template=PLOTLY_TEMPLATE,
        height=450,
        showlegend=True,
    )
    return fig


def normalized_points_chart(dfs: dict[str, pd.DataFrame]) -> go.Figure:
    """Line chart comparing actual vs normalized points across seasons."""
    colors = ["#E10600", "#3671C6", "#27F4D2", "#FF8000"]
    fig = go.Figure()

    for i, (name, df) in enumerate(dfs.items()):
        if df.empty:
            continue
        color = colors[i % len(colors)]
        fig.add_trace(go.Scatter(
            x=df["season"], y=df["actual_points"],
            name=f"{name} (actual)",
            mode="lines+markers",
            line=dict(color=color, width=2),
        ))
        fig.add_trace(go.Scatter(
            x=df["season"], y=df["normalized_points"],
            name=f"{name} (normalized)",
            mode="lines+markers",
            line=dict(color=color, width=2, dash="dash"),
        ))

    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Season",
        yaxis_title="Points",
        height=500,
    )
    return fig

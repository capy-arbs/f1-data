"""Plotly charts for the Sprint Analysis page. DataFrames in, Figures out."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import COLOR_NEGATIVE, COLOR_POSITIVE, PLOTLY_TEMPLATE


def sprint_points_bar(points_df: pd.DataFrame, top_n: int = 15) -> go.Figure:
    """Horizontal sprint-points leaderboard for the top ``top_n`` drivers."""
    fig = px.bar(
        points_df.head(top_n), x="sprint_points", y="driver", orientation="h",
        template=PLOTLY_TEMPLATE, text="sprint_points",
        color="sprint_points", color_continuous_scale="YlOrRd",
    )
    fig.update_layout(yaxis=dict(autorange="reversed"), height=450, xaxis_title="Sprint Points")
    return fig


def sprint_vs_race_bar(driver_avg: pd.DataFrame) -> go.Figure:
    """Average sprint-vs-race position delta per driver (green = better in sprints)."""
    fig = go.Figure(go.Bar(
        x=driver_avg["diff"],
        y=driver_avg["code"],
        orientation="h",
        marker_color=[COLOR_POSITIVE if d > 0 else COLOR_NEGATIVE for d in driver_avg["diff"]],
        text=driver_avg["diff"].round(1),
        textposition="auto",
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE, height=500,
        xaxis_title="Avg Position Difference (Sprint - Race, positive = better in sprints)",
        yaxis=dict(autorange="reversed"),
    )
    return fig

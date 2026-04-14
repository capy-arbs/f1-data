"""Plotly charts for the Race Breakdown page."""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from config import PLOTLY_TEMPLATE, TEAM_COLORS


def _team_color(constructor_id: str) -> str:
    return TEAM_COLORS.get(constructor_id, "#AAAAAA")


def grid_vs_finish_chart(df: pd.DataFrame) -> go.Figure:
    """Dumbbell chart showing grid position vs finish position."""
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    # Only show drivers who finished
    finished = df[df["position"].notna()].copy()
    finished = finished.sort_values("position")

    fig = go.Figure()
    for _, row in finished.iterrows():
        grid = row["grid"]
        finish = row["position"]
        color = "#22c55e" if finish < grid else "#ef4444" if finish > grid else "#888888"
        fig.add_trace(go.Scatter(
            x=[grid, finish],
            y=[row["driver"], row["driver"]],
            mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=10),
            showlegend=False,
            hovertemplate=f"{row['driver']}: Grid {grid} → P{int(finish)}<extra></extra>",
        ))

    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Position",
        xaxis=dict(dtick=1, autorange="reversed"),
        height=max(400, len(finished) * 28),
        margin=dict(l=100),
    )
    return fig


def fastest_laps_chart(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar chart of fastest lap times."""
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    fl = df[df["fastest_lap_time"].notna()].copy()
    fl = fl.sort_values("fastest_lap_rank")

    colors = ["#E8002D" if r == 1 else "#3671C6" for r in fl["fastest_lap_rank"]]

    fig = go.Figure(go.Bar(
        y=fl["driver"],
        x=fl["fastest_lap_rank"],
        orientation="h",
        marker_color=colors,
        text=fl["fastest_lap_time"],
        textposition="auto",
        hovertemplate="%{y}: %{text}<extra></extra>",
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Fastest Lap Rank",
        height=max(400, len(fl) * 25),
        yaxis=dict(autorange="reversed"),
    )
    return fig


def pit_stop_chart(df: pd.DataFrame) -> go.Figure:
    """Bar chart of pit stop durations by driver."""
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])

    fig = px.bar(
        df,
        x="driver",
        y="duration_ms",
        color="stop_number",
        barmode="group",
        template=PLOTLY_TEMPLATE,
        labels={"duration_ms": "Duration (s)", "driver": "Driver", "stop_number": "Stop #"},
        text="duration",
    )
    fig.update_layout(height=400)
    return fig


def dnf_chart(df: pd.DataFrame) -> go.Figure:
    """Pie chart of DNF causes."""
    if df.empty:
        return go.Figure()

    dnfs = df[df["position"].isna()].copy()
    if dnfs.empty:
        return go.Figure()

    status_counts = dnfs["status"].value_counts().reset_index()
    status_counts.columns = ["status", "count"]

    fig = px.pie(
        status_counts,
        values="count",
        names="status",
        template=PLOTLY_TEMPLATE,
        hole=0.4,
    )
    fig.update_layout(height=350)
    return fig

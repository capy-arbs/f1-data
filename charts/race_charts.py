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


def _laptime_to_seconds(t) -> float | None:
    """Parse "M:SS.mmm" lap-time strings into seconds. Returns None on parse failure."""
    if pd.isna(t):
        return None
    try:
        mins, rest = str(t).split(":", 1)
        return int(mins) * 60 + float(rest)
    except (ValueError, AttributeError):
        return None


def fastest_laps_chart(df: pd.DataFrame) -> go.Figure:
    """Gap-to-fastest visualization: each driver as a horizontal bar showing
    how far behind the session's fastest lap they were, in seconds.

    The pole-sitter is at 0 (a marker, not a zero-width bar), and the spread
    of bars reveals true pace differences instead of just re-stating the rank.
    Bars are coloured by constructor.
    """
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    df["lap_seconds"] = df["fastest_lap_time"].apply(_laptime_to_seconds)
    fl = df[df["lap_seconds"].notna()].copy()
    if fl.empty:
        return go.Figure().update_layout(
            template=PLOTLY_TEMPLATE,
            title="No fastest-lap data for this race",
        )

    fastest = fl["lap_seconds"].min()
    fl["delta"] = fl["lap_seconds"] - fastest
    # Sort fastest-first; with autorange='reversed' on the y-axis, fastest
    # ends up at the top.
    fl = fl.sort_values("delta")

    colors = [_team_color(cid) for cid in fl["constructor_id"]]

    fig = go.Figure(go.Bar(
        y=fl["driver"],
        x=fl["delta"],
        orientation="h",
        marker=dict(color=colors, line=dict(color="#0A0B0F", width=0.5)),
        text=[
            f"{t}" if d == 0 else f"+{d:.3f}s"
            for d, t in zip(fl["delta"], fl["fastest_lap_time"])
        ],
        textposition="outside",
        cliponaxis=False,
        customdata=list(zip(fl["fastest_lap_time"], fl["constructor"])),
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Lap: %{customdata[0]} (%{customdata[1]})<br>"
            "Gap to fastest: +%{x:.3f}s"
            "<extra></extra>"
        ),
    ))

    # Vertical guide at zero so the "fastest" baseline is unambiguous.
    fig.add_vline(x=0, line_color="#888", line_width=1, line_dash="dot")

    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Gap to fastest lap (seconds)",
        yaxis_title=None,
        height=max(400, len(fl) * 26),
        yaxis=dict(autorange="reversed"),
        margin=dict(l=70, r=80),
        showlegend=False,
        hoverlabel=dict(bgcolor="rgba(15,16,21,0.96)", bordercolor="#25262F"),
    )
    return fig


def pit_stop_chart(df: pd.DataFrame) -> go.Figure:
    """Stacked bar chart of pit-stop durations by driver, ordered chronologically.

    Stop 1 sits at the bottom, stop 2 above, stop 3 above that. Total bar
    height = total stationary time in the pits across the race. Stops are
    coloured by their order so the legend reads top-down 1 -> 2 -> 3.

    Stops longer than ~2 minutes are filtered out — those are repairs,
    red-flag pit-lane waits, or recoveries (e.g. Stroll's 18-minute
    "stop" at Australia 2026), not normal tire changes. Including them
    would crush every other bar to invisibility. A caption notes any that
    were excluded.
    """
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    df["stop_number"] = df["stop_number"].astype(int)
    df = df.sort_values(["driver", "stop_number"])

    # Filter out abnormal "stops" (>120s = clearly an incident, not a tire change).
    OUTLIER_S = 120.0
    excluded = df[df["duration_ms"] > OUTLIER_S]
    df = df[(df["duration_ms"].notna()) & (df["duration_ms"] <= OUTLIER_S)]

    # Stop-number palette — desaturated, cohesive, evenly-lit colours so no
    # single segment dominates the eye. Each stop gets a clearly different
    # hue (slate -> copper -> sage -> plum -> teal) for distinguishability
    # without the broadcast-graphic intensity of the team-colour scheme.
    stop_colors = ["#5B7C99", "#C29A6E", "#7A9B6E", "#8E7AA0", "#6B8B8E"]

    fig = go.Figure()
    for stop_num in sorted(df["stop_number"].unique()):
        stop_df = df[df["stop_number"] == stop_num]
        color = stop_colors[(stop_num - 1) % len(stop_colors)]
        fig.add_trace(go.Bar(
            x=stop_df["driver"],
            y=stop_df["duration_ms"],
            name=f"Stop {stop_num}",
            marker_color=color,
            text=stop_df["duration"].apply(lambda d: f"{d}s" if pd.notna(d) else ""),
            textposition="inside",
            textfont=dict(size=10),
            hovertemplate=(
                "<b>%{x}</b><br>"
                f"Stop {stop_num}: %{{y:.3f}}s"
                "<extra></extra>"
            ),
        ))

    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        barmode="stack",
        xaxis_title=None,
        yaxis_title="Pit time (s)",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, traceorder="normal"),
        hoverlabel=dict(bgcolor="rgba(15,16,21,0.96)", bordercolor="#25262F"),
    )

    # Surface any excluded outliers so the chart doesn't quietly drop them.
    if not excluded.empty:
        notes = ", ".join(
            f"{r['driver']} stop {int(r['stop_number'])} ({r['duration']})"
            for _, r in excluded.iterrows()
        )
        fig.add_annotation(
            x=0.5, y=1.06, xref="paper", yref="paper",
            showarrow=False, xanchor="center",
            text=f"Excluded (likely repair/red-flag delay): {notes}",
            font=dict(color="#888A95", size=11),
        )
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

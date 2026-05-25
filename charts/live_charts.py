"""Plotly figures for the Live Race page."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from config import PLOTLY_TEMPLATE

# Pirelli compound colours (used both on TV graphics and in OpenF1 metadata).
COMPOUND_COLOURS = {
    "SOFT": "#FF3333",
    "MEDIUM": "#FFD43B",
    "HARD": "#F0F0F0",
    "INTERMEDIATE": "#43A047",
    "WET": "#1E88E5",
    "UNKNOWN": "#808080",
}


def stint_gantt(stints_df: pd.DataFrame, drivers_df: pd.DataFrame) -> go.Figure:
    """Horizontal-bar Gantt of every stint for every driver, coloured by compound."""
    if stints_df.empty or drivers_df.empty:
        return go.Figure().update_layout(template=PLOTLY_TEMPLATE, title="No stint data")

    df = stints_df.merge(
        drivers_df[["driver_number", "name_acronym"]], on="driver_number", how="left"
    )
    df["acronym"] = df["name_acronym"].fillna(df["driver_number"].astype(str))
    df["length"] = (df["lap_end"].fillna(df["lap_start"]) - df["lap_start"] + 1).clip(lower=1)
    df["compound"] = df["compound"].fillna("UNKNOWN")

    # Sort drivers by finishing position (if available), falling back to
    # lap_end for sessions where position isn't in the drivers frame.
    if "position" in drivers_df.columns:
        pos_map = drivers_df.dropna(subset=["position"]).set_index("driver_number")["position"]
        df["_pos"] = df["driver_number"].map(pos_map).fillna(99)
        order = (
            df.groupby("acronym")["_pos"].min().sort_values(ascending=False).index.tolist()
        )
        df.drop(columns="_pos", inplace=True)
    else:
        order = (
            df.groupby("acronym")["lap_end"].max().sort_values(ascending=True).index.tolist()
        )

    fig = go.Figure()
    for compound, colour in COMPOUND_COLOURS.items():
        sub = df[df["compound"] == compound]
        if sub.empty:
            continue
        fig.add_bar(
            x=sub["length"],
            y=sub["acronym"],
            base=sub["lap_start"] - 1,
            orientation="h",
            marker=dict(color=colour, line=dict(color="#222", width=0.5)),
            name=compound.title(),
            customdata=sub[["lap_start", "lap_end", "stint_number", "tyre_age_at_start"]].values,
            hovertemplate=(
                "%{y} — %{base} → %{base}+%{x:.0f}<br>"
                "Compound: " + compound + "<br>"
                "Stint #%{customdata[2]} (started age %{customdata[3]})<extra></extra>"
            ),
        )
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        barmode="stack",
        title="Tire stints",
        xaxis_title="Lap",
        yaxis_title="Driver",
        height=max(360, 18 * df["acronym"].nunique() + 80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=40, l=60, r=20),
    )
    return fig


def pace_trace_chart(
    laps_df: pd.DataFrame,
    drivers_df: pd.DataFrame,
    chaser: int,
    target: int,
    window: int = 15,
) -> go.Figure:
    """Lap-time line for the two drivers, with each driver's recent mean as a dashed reference."""
    fig = go.Figure().update_layout(template=PLOTLY_TEMPLATE, title="Recent pace")
    if laps_df.empty:
        return fig

    def _trace(num: int, label_default: str, dash: str = "solid"):
        d = laps_df[laps_df["driver_number"] == num].sort_values("lap_number").tail(window)
        d = d.dropna(subset=["lap_duration"])
        if d.empty:
            return None
        acronym = label_default
        if not drivers_df.empty:
            row = drivers_df[drivers_df["driver_number"] == num]
            if not row.empty:
                acronym = row.iloc[0]["name_acronym"]
                colour = "#" + (row.iloc[0]["team_colour"] or "888888")
            else:
                colour = "#888888"
        else:
            colour = "#888888"
        fig.add_trace(go.Scatter(
            x=d["lap_number"], y=d["lap_duration"],
            mode="lines+markers", name=acronym,
            line=dict(color=colour, dash=dash, width=2),
            hovertemplate="Lap %{x}: %{y:.3f}s<extra>" + acronym + "</extra>",
        ))
        # Mean reference line
        mean = d["lap_duration"].mean()
        fig.add_trace(go.Scatter(
            x=[d["lap_number"].min(), d["lap_number"].max()],
            y=[mean, mean],
            mode="lines", name=f"{acronym} avg",
            line=dict(color=colour, dash="dot", width=1),
            showlegend=False, hoverinfo="skip",
        ))
        return acronym

    _trace(chaser, str(chaser))
    _trace(target, str(target))
    fig.update_layout(
        title="Recent pace (lap time)",
        xaxis_title="Lap",
        yaxis_title="Lap time (s)",
        height=320,
        margin=dict(t=50, b=40, l=50, r=20),
    )
    return fig


def gap_evolution_chart(
    intervals_df: pd.DataFrame,
    drivers_df: pd.DataFrame,
    chaser: int,
    target: int,
) -> go.Figure:
    """How the gap between two drivers has evolved over the session."""
    fig = go.Figure().update_layout(template=PLOTLY_TEMPLATE, title="Gap evolution")
    if intervals_df.empty:
        return fig

    # merge_asof requires non-null keys, so drop rows missing date or gap up front.
    a = (
        intervals_df[intervals_df["driver_number"] == chaser][["date", "gap_to_leader"]]
        .dropna()
        .sort_values("date")
    )
    b = (
        intervals_df[intervals_df["driver_number"] == target][["date", "gap_to_leader"]]
        .dropna()
        .sort_values("date")
    )
    if a.empty or b.empty:
        return fig

    # Align on time using a merge_asof so we get the gap-delta over time even
    # though the two drivers' samples don't share timestamps exactly.
    merged = pd.merge_asof(
        a.rename(columns={"gap_to_leader": "chaser_gap"}),
        b.rename(columns={"gap_to_leader": "target_gap"}),
        on="date", direction="nearest", tolerance=pd.Timedelta(seconds=8),
    ).dropna()
    if merged.empty:
        return fig

    merged["delta"] = merged["chaser_gap"] - merged["target_gap"]

    chaser_label = str(chaser)
    if not drivers_df.empty:
        row = drivers_df[drivers_df["driver_number"] == chaser]
        if not row.empty:
            chaser_label = row.iloc[0]["name_acronym"]
    target_label = str(target)
    if not drivers_df.empty:
        row = drivers_df[drivers_df["driver_number"] == target]
        if not row.empty:
            target_label = row.iloc[0]["name_acronym"]

    fig.add_trace(go.Scatter(
        x=merged["date"], y=merged["delta"],
        mode="lines", line=dict(color="#FFD43B", width=2),
        name=f"{chaser_label} − {target_label} gap",
        hovertemplate="%{x|%H:%M:%S}<br>Gap: %{y:.2f}s<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dot", line_color="#888")
    fig.update_layout(
        title=f"{chaser_label} → {target_label}: gap over time",
        xaxis_title="Time",
        yaxis_title="Gap (s)",
        height=300,
        margin=dict(t=50, b=40, l=50, r=20),
    )
    return fig

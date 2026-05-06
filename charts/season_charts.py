"""Plotly charts for the Season Tracker page."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from config import PLOTLY_TEMPLATE, TEAM_COLORS

# Fallback colors for teams not in the config
_FALLBACK_COLORS = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
    "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
]


def _build_color_map(df: pd.DataFrame) -> dict[str, str]:
    """Map each driver label to their team color.

    Keyed by constructor first so teammates always share a color.
    """
    team_color: dict[str, str] = {}
    fallback_idx = 0
    color_map: dict[str, str] = {}

    for constructor_id in df.dropna(subset=["constructor_id"])["constructor_id"].unique():
        if constructor_id in TEAM_COLORS:
            team_color[constructor_id] = TEAM_COLORS[constructor_id]
        else:
            team_color[constructor_id] = _FALLBACK_COLORS[fallback_idx % len(_FALLBACK_COLORS)]
            fallback_idx += 1

    for driver in df["driver"].unique():
        constructor_id = df[df["driver"] == driver].iloc[-1].get("constructor_id", "")
        color_map[driver] = team_color.get(constructor_id, "#AAAAAA")
    return color_map


def _drivers_grouped_by_team(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Return [(driver, constructor_id), ...] sorted so teammates render adjacent."""
    pairs = (
        df.groupby("driver")["constructor_id"]
        .last()
        .reset_index()
    )
    pairs = pairs.sort_values(["constructor_id", "driver"])
    return list(zip(pairs["driver"], pairs["constructor_id"]))


def _build_team_round_lookup(df: pd.DataFrame, value_col: str) -> dict:
    """Index (round, constructor_id) -> list of {driver, value}.

    Used by the hover layer to find a driver's teammate (or teammates,
    in the rare case of a mid-season swap) at the round under the cursor.
    """
    lookup: dict[tuple[int, str], list[dict]] = {}
    for (rd, cid), group in df.groupby(["round", "constructor_id"]):
        lookup[(rd, cid)] = group[["driver", value_col]].to_dict("records")
    return lookup


def _format_team_label(constructor_id: str) -> str:
    return (constructor_id or "").replace("_", " ").title()


def position_progression_chart(df: pd.DataFrame) -> go.Figure:
    """Line chart showing championship position across rounds (P1 at top).

    Hover (closest mode): shows team header, the hovered driver's position,
    and their teammate's position at the same round in a 2-line tooltip.
    """
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    color_map = _build_color_map(df)
    lookup = _build_team_round_lookup(df, "position")

    fig = go.Figure()
    for driver, constructor_id in _drivers_grouped_by_team(df):
        ddf = df[df["driver"] == driver].sort_values("round")
        team_label = _format_team_label(constructor_id)

        # customdata[0] = teammate string ("RUS: P3" or "" if no teammate)
        customdata = []
        for _, row in ddf.iterrows():
            mates = [
                m for m in lookup.get((row["round"], row["constructor_id"]), [])
                if m["driver"] != driver
            ]
            if mates and pd.notna(mates[0].get("position")):
                tm = mates[0]
                customdata.append([f"{tm['driver']}: P{int(tm['position'])}"])
            else:
                customdata.append([""])

        fig.add_trace(go.Scatter(
            x=ddf["round"],
            y=ddf["position"],
            name=driver,
            mode="lines+markers",
            line=dict(color=color_map.get(driver, "#AAAAAA"), width=2),
            marker=dict(size=6),
            legendgroup=constructor_id or driver,
            legendgrouptitle_text=team_label or None,
            customdata=customdata,
            hovertemplate=(
                f"<b>{team_label}</b> · Round %{{x}}<br>"
                f"<b>{driver}</b>: P%{{y}}<br>"
                "%{customdata[0]}"
                "<extra></extra>"
            ),
        ))

    fig.update_yaxes(autorange="reversed", dtick=1)
    fig.update_xaxes(dtick=1)
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Round",
        yaxis_title="Championship Position",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=-0.35, groupclick="togglegroup"),
        hovermode="closest",
        hoverlabel=dict(
            font_size=12,
            bgcolor="rgba(15,16,21,0.96)",
            bordercolor="#25262F",
            align="left",
        ),
    )
    return fig


def points_accumulation_chart(df: pd.DataFrame) -> go.Figure:
    """Cumulative points across rounds. Hover shows hovered driver + teammate."""
    if df.empty:
        return go.Figure()

    df = df.copy()
    df["driver"] = df["code"].fillna(df["family_name"])
    color_map = _build_color_map(df)

    # NOTE: driver_standings.points is already a season-to-date total per
    # round (championship cumulative), so we copy it through directly. Doing
    # cumsum() on top would double-cumulate — Antonelli's R4 chart would
    # read 237 instead of his real 100.
    df = df.sort_values(["driver", "round"])
    df["cum_points"] = df["points"]
    lookup = _build_team_round_lookup(df, "cum_points")

    fig = go.Figure()
    for driver, constructor_id in _drivers_grouped_by_team(df):
        ddf = df[df["driver"] == driver]
        team_label = _format_team_label(constructor_id)

        customdata = []
        for _, row in ddf.iterrows():
            mates = [
                m for m in lookup.get((row["round"], row["constructor_id"]), [])
                if m["driver"] != driver
            ]
            if mates and pd.notna(mates[0].get("cum_points")):
                tm = mates[0]
                customdata.append([f"{tm['driver']}: {int(tm['cum_points'])} pts"])
            else:
                customdata.append([""])

        fig.add_trace(go.Scatter(
            x=ddf["round"],
            y=ddf["cum_points"],
            name=driver,
            mode="lines+markers",
            line=dict(color=color_map.get(driver, "#AAAAAA"), width=2),
            marker=dict(size=6),
            legendgroup=constructor_id or driver,
            legendgrouptitle_text=team_label or None,
            customdata=customdata,
            hovertemplate=(
                f"<b>{team_label}</b> · Round %{{x}}<br>"
                f"<b>{driver}</b>: %{{y:.0f}} pts<br>"
                "%{customdata[0]}"
                "<extra></extra>"
            ),
        ))

    fig.update_xaxes(dtick=1)
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Round",
        yaxis_title="Cumulative Points",
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=-0.35, groupclick="togglegroup"),
        hovermode="closest",
        hoverlabel=dict(
            font_size=12,
            bgcolor="rgba(15,16,21,0.96)",
            bordercolor="#25262F",
            align="left",
        ),
    )
    return fig

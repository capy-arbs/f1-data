"""Championship Momentum — rolling form across the season."""

import streamlit as st
import plotly.graph_objects as go

from db.schema import init_db
from queries.historical import get_championship_momentum
from queries.standings import get_available_seasons
from config import PLOTLY_TEMPLATE, TEAM_COLORS

init_db()

st.title("Championship Momentum")
st.caption(
    "Rolling sum of points over the trailing N races. A leader whose rolling sum is "
    "falling while a chaser's is climbing is the classic 'in-form' story."
)

seasons = get_available_seasons()
if not seasons:
    st.warning("No data loaded.")
    st.stop()

ctrls = st.columns([1, 1, 2])
season = ctrls[0].selectbox("Season", seasons)
window = ctrls[1].slider("Rolling window (races)", 2, 8, 3)

df = get_championship_momentum(season, window=window)
if df.empty:
    st.info("No data for that season.")
    st.stop()

# Pick which drivers to show — default to top 6 by season total at the latest round.
final_round = df["round"].max()
top_at_end = (
    df[df["round"] == final_round]
    .sort_values("season_total", ascending=False)
    .head(6)["family_name"]
    .tolist()
)
drivers = ctrls[2].multiselect(
    "Drivers", sorted(df["family_name"].unique()), default=top_at_end
)
if not drivers:
    st.info("Pick at least one driver.")
    st.stop()

plot_df = df[df["family_name"].isin(drivers)].copy()

# Sort drivers so teammates render adjacent.
team_by_driver = (
    plot_df.groupby("family_name")["constructor_id"].last().to_dict()
)
ordered_drivers = sorted(drivers, key=lambda d: (team_by_driver.get(d, ""), d))

# Build a (round, constructor_id) -> [{driver, rolling_points, season_total}, ...] index
# so each trace's hover can include the teammate's value at the same round.
team_round_lookup: dict = {}
for (rd, cid), group in plot_df.groupby(["round", "constructor_id"]):
    team_round_lookup[(rd, cid)] = group[["family_name", "rolling_points", "season_total"]].to_dict("records")


def _teammate_text(row, value_col: str, suffix: str) -> str:
    mates = [
        m for m in team_round_lookup.get((row["round"], row["constructor_id"]), [])
        if m["family_name"] != row["family_name"]
    ]
    if not mates:
        return ""
    val = mates[0].get(value_col)
    if val is None:
        return ""
    return f"{mates[0]['family_name']}: {val:.0f}{suffix}"


# Rolling-window line chart — closest-mode hover with driver + teammate
fig = go.Figure()
for driver in ordered_drivers:
    d = plot_df[plot_df["family_name"] == driver].sort_values("round")
    if d.empty:
        continue
    constructor_id = d["constructor_id"].iloc[-1]
    color = TEAM_COLORS.get(constructor_id, "#888888")
    team_label = (constructor_id or "").replace("_", " ").title()
    customdata = [[_teammate_text(row, "rolling_points", "")] for _, row in d.iterrows()]
    fig.add_trace(go.Scatter(
        x=d["round"], y=d["rolling_points"],
        mode="lines+markers", name=driver,
        line=dict(color=color, width=2.5),
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
fig.update_layout(
    template=PLOTLY_TEMPLATE,
    title=f"Form over trailing {window} races",
    xaxis_title="Round",
    yaxis_title=f"Points (last {window} races)",
    height=440,
    margin=dict(t=60, b=40, l=50, r=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, groupclick="togglegroup"),
    hovermode="closest",
    hoverlabel=dict(font_size=12, bgcolor="rgba(15,16,21,0.96)", bordercolor="#25262F", align="left"),
)
st.plotly_chart(fig, use_container_width=True)

# Cumulative season-total comparison
st.subheader("Season total")
fig2 = go.Figure()
for driver in ordered_drivers:
    d = plot_df[plot_df["family_name"] == driver].sort_values("round")
    if d.empty:
        continue
    constructor_id = d["constructor_id"].iloc[-1]
    color = TEAM_COLORS.get(constructor_id, "#888888")
    team_label = (constructor_id or "").replace("_", " ").title()
    customdata = [[_teammate_text(row, "season_total", " pts")] for _, row in d.iterrows()]
    fig2.add_trace(go.Scatter(
        x=d["round"], y=d["season_total"],
        mode="lines", name=driver,
        line=dict(color=color, width=2),
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
fig2.update_layout(
    template=PLOTLY_TEMPLATE,
    xaxis_title="Round",
    yaxis_title="Cumulative points",
    height=360,
    margin=dict(t=30, b=40, l=50, r=20),
    legend=dict(orientation="h", yanchor="bottom", y=-0.25, groupclick="togglegroup"),
    hovermode="closest",
    hoverlabel=dict(font_size=12, bgcolor="rgba(15,16,21,0.96)", bordercolor="#25262F", align="left"),
)
st.plotly_chart(fig2, use_container_width=True)

# Momentum leader callout — highest rolling sum at the latest round
latest_form = (
    plot_df[plot_df["round"] == final_round]
    .sort_values("rolling_points", ascending=False)
)
if not latest_form.empty:
    leader = latest_form.iloc[0]
    st.success(
        f"**Form leader after R{final_round}:** {leader['family_name']} "
        f"with {leader['rolling_points']:.0f} pts in the last {window} races."
    )

"""Pit Stop Records — fastest pit stops leaderboard."""

import streamlit as st
import plotly.express as px

from db.schema import init_db
from queries.historical import get_fastest_pit_stops
from queries.standings import get_available_seasons
from config import PLOTLY_TEMPLATE

init_db()

st.title("Pit Stop Records")
st.caption(
    "Fastest pit stops in the database. Pit timing is only recorded from 2011 onwards. "
    "Note: 'duration' is just the stationary time — full pit-lane time is longer."
)

seasons = get_available_seasons()
if not seasons:
    st.warning("No data loaded.")
    st.stop()

filter_cols = st.columns([1, 1, 2])
scope = filter_cols[0].radio("Scope", ["All-time", "Single season"], horizontal=True)
season = None
if scope == "Single season":
    season = filter_cols[1].selectbox("Season", seasons)
limit = filter_cols[2].slider("Show top", 10, 100, 30, step=10)

df = get_fastest_pit_stops(season=season, limit=limit)
if df.empty:
    st.info("No pit-stop data matches your filter.")
    st.stop()

# Optional team filter
teams = sorted(df["constructor"].dropna().unique())
chosen = st.multiselect("Filter by team", teams, default=[])
if chosen:
    df = df[df["constructor"].isin(chosen)]

# Headline metric — fastest stop in the filtered set
top = df.iloc[0]
metric_cols = st.columns(3)
metric_cols[0].metric("Fastest stop", f"{top['duration']}s")
metric_cols[1].metric("Driver", top["driver"])
metric_cols[2].metric("Race", f"{top['race_name']} ({top['season']})")

st.divider()

# Leaderboard table
display = df.copy()
display["Time (s)"] = display["duration"]
display["Race"] = display["race_name"] + " " + display["season"].astype(str)
st.dataframe(
    display[["Time (s)", "driver", "constructor", "Race", "lap"]].rename(
        columns={"driver": "Driver", "constructor": "Team", "lap": "Lap"}
    ),
    hide_index=True,
    use_container_width=True,
)

# Distribution by team
st.subheader("Average fastest stop by team")
team_avg = (
    df.groupby("constructor", as_index=False)["duration_s"]
    .mean()
    .sort_values("duration_s")
)
fig = px.bar(
    team_avg,
    x="constructor", y="duration_s",
    template=PLOTLY_TEMPLATE,
    labels={"constructor": "Team", "duration_s": "Avg duration (s)"},
    title="Mean of the top stops shown above, per team",
)
st.plotly_chart(fig, use_container_width=True)

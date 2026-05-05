"""Season Tracker — standings and progression charts."""

import streamlit as st

from db.schema import init_db
from queries.standings import (
    get_available_seasons,
    get_driver_standings,
    get_constructor_standings,
    get_position_progression,
    get_rounds_for_season,
)
from charts.season_charts import position_progression_chart, points_accumulation_chart

init_db()

st.title("Season Tracker")

seasons = get_available_seasons()
if not seasons:
    st.warning("No data loaded. Head to **Load Data** to fetch some seasons first.")
    st.stop()

season = st.selectbox("Season", seasons)
rounds = get_rounds_for_season(season)

if not rounds:
    st.warning(f"No race data for {season}.")
    st.stop()

# Standings tables
st.subheader(f"{season} Championship Standings")
col1, col2 = st.columns(2)

with col1:
    st.markdown("**Drivers**")
    driver_df = get_driver_standings(season)
    if not driver_df.empty:
        st.dataframe(
            driver_df.rename(columns={
                "position": "Pos", "code": "Driver", "constructor": "Team",
                "points": "Points", "wins": "Wins",
            })[["Pos", "Driver", "Team", "Points", "Wins"]],
            hide_index=True,
            use_container_width=True,
        )

with col2:
    st.markdown("**Constructors**")
    constructor_df = get_constructor_standings(season)
    if not constructor_df.empty:
        st.dataframe(
            constructor_df.rename(columns={
                "position": "Pos", "constructor": "Team",
                "points": "Points", "wins": "Wins",
            })[["Pos", "Team", "Points", "Wins"]],
            hide_index=True,
            use_container_width=True,
        )

# Position progression
st.subheader("Championship Position Progression")
progression_df = get_position_progression(season)
if not progression_df.empty:
    fig = position_progression_chart(progression_df)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No standings progression data available for this season.")

# Points accumulation
st.subheader("Points Accumulation")
if not progression_df.empty:
    fig = points_accumulation_chart(progression_df)
    st.plotly_chart(fig, use_container_width=True)

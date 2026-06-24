"""Race Calendar — season schedule with results."""

import streamlit as st

from db.schema import init_db
from queries.circuits import get_race_calendar
from queries.standings import get_available_seasons

init_db()

st.title("Race Calendar")

seasons = get_available_seasons()
if not seasons:
    st.warning("No data loaded. Head to **Load Data** first.")
    st.stop()

season = st.selectbox("Season", seasons, key="cal_season")
calendar = get_race_calendar(season)

if calendar.empty:
    st.warning(f"No calendar data for {season}.")
    st.stop()

st.subheader(f"{season} Season Schedule")

# Summary stats
total = len(calendar)
completed = calendar["winner"].notna().sum()
remaining = total - completed

col1, col2, col3 = st.columns(3)
col1.metric("Total Races", total)
col2.metric("Completed", completed)
col3.metric("Remaining", remaining)

st.divider()

# Calendar display
for _, race in calendar.iterrows():
    has_result = race["winner"] is not None

    with st.container():
        cols = st.columns([0.5, 3, 2, 2])

        # Round number
        cols[0].markdown(f"### R{race['round']}")

        # Race name and circuit
        cols[1].markdown(f"**{race['race_name']}**")
        cols[1].caption(f"{race['circuit']} — {race['locality']}, {race['country']}")

        # Date
        cols[2].markdown(f"**{race['date']}**")

        # Winner or upcoming
        if has_result:
            cols[3].markdown(f":trophy: **{race['winner']}**")
            cols[3].caption(race["winning_team"] or "")
        else:
            cols[3].markdown(":clock3: *Upcoming*")

        st.divider()

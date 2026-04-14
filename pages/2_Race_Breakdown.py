"""Race Breakdown — deep dive into individual race results."""

import streamlit as st

from db.schema import init_db
from db.connection import get_db
from queries.standings import get_available_seasons, get_rounds_for_season
from queries.races import get_race_results, get_race_info, get_pit_stops, get_qualifying_results
from data.loader import load_pit_stops_for_race
from charts.race_charts import grid_vs_finish_chart, fastest_laps_chart, pit_stop_chart, dnf_chart

init_db()

st.title("Race Breakdown")

seasons = get_available_seasons()
if not seasons:
    st.warning("No data loaded. Head to **Load Data** first.")
    st.stop()

season = st.sidebar.selectbox("Season", seasons, key="rb_season")
rounds = get_rounds_for_season(season)
if not rounds:
    st.warning(f"No races for {season}.")
    st.stop()

round_options = {f"R{r['round']}: {r['race_name']}": r["round"] for r in rounds}
selected = st.sidebar.selectbox("Race", list(round_options.keys()))
round_num = round_options[selected]

# Race info header
info = get_race_info(season, round_num)
if info:
    st.subheader(f"{info['race_name']}")
    st.caption(f"{info['circuit']} — {info['locality']}, {info['country']} | {info['date']}")

# Results table
results_df = get_race_results(season, round_num)
if results_df.empty:
    st.warning("No results data for this race.")
    st.stop()

st.subheader("Results")
display_df = results_df.copy()
display_df["Driver"] = display_df["code"].fillna(display_df["family_name"])
display_df["Pos"] = display_df["position_text"]
st.dataframe(
    display_df[["Pos", "Driver", "constructor", "grid", "points", "status", "fastest_lap_time"]]
    .rename(columns={
        "constructor": "Team", "grid": "Grid", "points": "Pts",
        "status": "Status", "fastest_lap_time": "Fastest Lap",
    }),
    hide_index=True,
    use_container_width=True,
)

# Grid vs Finish
st.subheader("Grid vs Finish Position")
fig = grid_vs_finish_chart(results_df)
st.plotly_chart(fig, use_container_width=True)
st.caption("Green = gained positions, Red = lost positions")

# Fastest laps
st.subheader("Fastest Laps")
fig = fastest_laps_chart(results_df)
st.plotly_chart(fig, use_container_width=True)

# DNFs
dnfs = results_df[results_df["position"].isna()]
if not dnfs.empty:
    st.subheader(f"Retirements ({len(dnfs)})")
    col1, col2 = st.columns([1, 1])
    with col1:
        dnf_display = dnfs.copy()
        dnf_display["Driver"] = dnf_display["code"].fillna(dnf_display["family_name"])
        st.dataframe(
            dnf_display[["Driver", "constructor", "grid", "laps", "status"]]
            .rename(columns={"constructor": "Team", "grid": "Grid", "laps": "Laps", "status": "Reason"}),
            hide_index=True,
        )
    with col2:
        fig = dnf_chart(results_df)
        st.plotly_chart(fig, use_container_width=True)

# Pit stops (lazy loaded)
st.subheader("Pit Stops")
with get_db() as conn:
    load_pit_stops_for_race(conn, season, round_num)
pit_df = get_pit_stops(season, round_num)
if not pit_df.empty:
    fig = pit_stop_chart(pit_df)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Pit stop data not available for this race.")

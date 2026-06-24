"""Sprint Analysis — sprint race results and stats (2021+)."""

import streamlit as st

from charts.sprint_charts import sprint_points_bar, sprint_vs_race_bar
from db.schema import init_db
from queries.sprint import (
    get_sprint_points_by_driver,
    get_sprint_races,
    get_sprint_results,
    get_sprint_seasons,
    get_sprint_vs_race,
    sprint_vs_race_summary,
)

init_db()

st.title("Sprint Race Analysis")
st.markdown("Sprint races have been part of F1 since 2021. Explore results and stats here.")


sprint_seasons = get_sprint_seasons()
if not sprint_seasons:
    st.warning("No sprint data loaded. Load seasons from 2021 onwards and re-fetch to include sprint results.")
    st.stop()

season = st.selectbox("Season", sprint_seasons, key="sprint_season")

# Sprint points leaderboard
st.subheader(f"{season} Sprint Points")
points_df = get_sprint_points_by_driver(season)
if not points_df.empty:
    st.plotly_chart(sprint_points_bar(points_df), use_container_width=True)

    st.dataframe(
        points_df.rename(columns={
            "driver": "Driver", "sprint_points": "Sprint Pts",
            "sprint_races": "Sprints", "sprint_wins": "Sprint Wins",
        }),
        hide_index=True, use_container_width=True,
    )

# Individual sprint results
st.divider()
st.subheader("Sprint Race Results")
sprint_races = get_sprint_races(season)
if sprint_races:
    race_opts = {f"R{r['round']}: {r['race_name']}": r["round"] for r in sprint_races}
    selected_race = st.selectbox("Select Sprint", list(race_opts.keys()))
    round_num = race_opts[selected_race]

    sprint_df = get_sprint_results(season, round_num)
    if not sprint_df.empty:
        display = sprint_df.copy()
        display["Driver"] = display["code"].fillna(display["family_name"])
        st.dataframe(
            display[["position_text", "Driver", "constructor", "grid", "points", "status"]]
            .rename(columns={
                "position_text": "Pos", "constructor": "Team",
                "grid": "Grid", "points": "Pts", "status": "Status",
            }),
            hide_index=True, use_container_width=True,
        )

# Sprint vs Main Race comparison
st.divider()
st.subheader("Sprint vs Main Race Performance")
comparison = get_sprint_vs_race(season)
driver_avg = sprint_vs_race_summary(comparison)
if not driver_avg.empty:
    st.plotly_chart(sprint_vs_race_bar(driver_avg), use_container_width=True)
    st.caption("Positive = driver performs better in sprints than the main race on average")

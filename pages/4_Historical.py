"""Historical — cross-era comparisons and records."""

import streamlit as st

from db.schema import init_db
from queries.drivers import get_all_drivers
from queries.historical import (
    get_career_comparison,
    get_normalized_season_points,
    get_records,
    get_championship_wins,
)
from charts.comparison_charts import career_comparison_radar, normalized_points_chart
from config import POINT_SYSTEMS

init_db()

st.title("Historical Comparison")

drivers = get_all_drivers()
if not drivers:
    st.warning("No data loaded. Head to **Load Data** first.")
    st.stop()

driver_options = {f"{d['given_name']} {d['family_name']}": d["driver_id"] for d in drivers}

# Era comparison tool
st.subheader("Cross-Era Driver Comparison")
st.markdown("Compare drivers from any era. Stats are shown as career totals and per-race averages.")

selected_names = st.multiselect(
    "Select drivers to compare",
    list(driver_options.keys()),
    default=[],
    max_selections=5,
)

if selected_names:
    selected_ids = [driver_options[n] for n in selected_names]
    comparison_df = get_career_comparison(selected_ids)

    if not comparison_df.empty:
        # Stats table
        display = comparison_df.copy()
        display["Driver"] = display["given_name"] + " " + display["family_name"]
        st.dataframe(
            display[["Driver", "races", "wins", "podiums", "poles",
                      "total_points", "win_pct", "podium_pct", "points_per_race"]]
            .rename(columns={
                "races": "Races", "wins": "Wins", "podiums": "Podiums", "poles": "Poles",
                "total_points": "Points", "win_pct": "Win %", "podium_pct": "Podium %",
                "points_per_race": "Pts/Race",
            }),
            hide_index=True,
            use_container_width=True,
        )

        # Radar chart
        fig = career_comparison_radar(comparison_df)
        st.plotly_chart(fig, use_container_width=True)

# Normalized points comparison
st.divider()
st.subheader("Point System Normalization")
st.markdown("See what a driver's career would look like under a different scoring system.")

norm_col1, norm_col2 = st.columns([2, 1])
norm_drivers = norm_col1.multiselect(
    "Select drivers",
    list(driver_options.keys()),
    default=[],
    max_selections=4,
    key="norm_drivers",
)
target_system = norm_col2.selectbox("Target point system", list(POINT_SYSTEMS.keys()))

if norm_drivers:
    norm_data = {}
    for name in norm_drivers:
        did = driver_options[name]
        df = get_normalized_season_points(did, target_system)
        if not df.empty:
            norm_data[name.split()[-1]] = df

    if norm_data:
        fig = normalized_points_chart(norm_data)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Dashed lines show points recalculated under the **{target_system}** system.")

# Records section
st.divider()
st.subheader("All-Time Records")

# Championships
st.markdown("**World Championships**")
champs = get_championship_wins()
if not champs.empty:
    champs["Driver"] = champs["given_name"] + " " + champs["family_name"]
    st.dataframe(
        champs[["Driver", "championships"]].rename(columns={"championships": "Titles"}),
        hide_index=True,
        use_container_width=True,
    )

record_tabs = st.tabs(["Most Wins", "Most Podiums", "Most Poles", "Most Points", "Most Races", "Highest Win Rate"])
record_types = ["most_wins", "most_podiums", "most_poles", "most_points", "most_races", "highest_win_rate"]
record_labels = ["Wins", "Podiums", "Poles", "Points", "Races", "Win Rate (%)"]

for tab, rtype, label in zip(record_tabs, record_types, record_labels):
    with tab:
        df = get_records(rtype)
        if not df.empty:
            df["Driver"] = df["given_name"] + " " + df["family_name"]
            df = df[["Driver", "value"]].rename(columns={"value": label})
            st.dataframe(df, hide_index=True, use_container_width=True)

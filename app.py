"""F1 Analytics Dashboard — entry point and navigation."""

import streamlit as st

from db.schema import init_db

st.set_page_config(
    page_title="F1 Analytics Dashboard",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Idempotent — only runs DDL on first launch.
init_db()


def home() -> None:
    """Landing view: brief intro and quick-glance counts of what's loaded."""
    from db.connection import get_db

    st.title("F1 Analytics Dashboard")
    st.markdown(
        "Live timing, race history, and analytics for Formula 1 — 1950 to today. "
        "Pick a section from the sidebar."
    )

    with get_db() as conn:
        season_count = conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]
        race_count = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
        driver_count = conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]

    col1, col2, col3 = st.columns(3)
    col1.metric("Seasons Loaded", season_count)
    col2.metric("Races", race_count)
    col3.metric("Drivers", driver_count)

    if season_count == 0:
        st.info(
            "No historical data loaded yet. Open **Settings → Load Data** "
            "to pull seasons from the Jolpica API."
        )
    else:
        st.caption(
            "Live timing pulls from OpenF1 in real time and doesn't require a data load."
        )


# Single source of truth for sidebar nav. st.navigation replaces Streamlit's
# auto-generated file-based nav, so the numeric prefixes on filenames in
# pages/ no longer affect ordering — this dict does.
nav = {
    # Ungrouped landing page at the top of the sidebar.
    "": [
        st.Page(home, title="Home", default=True),
    ],
    "Live": [
        st.Page("pages/14_Live_Race.py", title="Live Race"),
    ],
    "This Season": [
        st.Page("pages/1_Season_Tracker.py", title="Standings"),
        st.Page("pages/9_Race_Calendar.py", title="Race Calendar"),
        st.Page("pages/2_Race_Breakdown.py", title="Race Breakdown"),
        st.Page("pages/11_Sprint_Analysis.py", title="Sprint Analysis"),
        st.Page("pages/16_Championship_Momentum.py", title="Championship Momentum"),
    ],
    "Drivers": [
        st.Page("pages/6_Driver_Profiles.py", title="Driver Profiles"),
        st.Page("pages/3_Head_to_Head.py", title="Head-to-Head"),
        st.Page("pages/7_GOAT_Calculator.py", title="GOAT Calculator"),
    ],
    "Circuits": [
        st.Page("pages/5_Circuit_Map.py", title="Circuit Map"),
    ],
    "Play": [
        st.Page("pages/8_What_If.py", title="What-If Simulator"),
        st.Page("pages/10_Trivia.py", title="Trivia"),
        st.Page("pages/13_Predictions.py", title="Prediction Tracker"),
    ],
    "Records & History": [
        st.Page("pages/4_Historical.py", title="Era Comparison"),
        st.Page("pages/15_Pit_Stop_Records.py", title="Pit Stop Records"),
        st.Page("pages/17_Lap_Time_Evolution.py", title="Lap Time Evolution"),
        st.Page("pages/12_Safety_Stats.py", title="DNF Analysis"),
    ],
    "Settings": [
        st.Page("pages/0_Load_Data.py", title="Load Data"),
    ],
}

st.navigation(nav).run()

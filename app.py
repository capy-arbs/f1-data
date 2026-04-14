"""F1 Analytics Dashboard — Main entry point."""

import streamlit as st

from db.schema import init_db

st.set_page_config(
    page_title="F1 Analytics Dashboard",
    page_icon="🏎️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize database on first run
init_db()

st.title("F1 Analytics Dashboard")
st.markdown(
    "Explore Formula 1 data from 1950 to today. "
    "Use the sidebar to load seasons, then navigate to the dashboard pages."
)

# Sidebar: data loading controls
st.sidebar.header("Data Management")

if st.sidebar.button("Load Data", use_container_width=True):
    st.switch_page("pages/0_Load_Data.py")

st.sidebar.divider()

st.sidebar.markdown("**Analysis**")
st.sidebar.page_link("pages/1_Season_Tracker.py", label="Season Tracker")
st.sidebar.page_link("pages/2_Race_Breakdown.py", label="Race Breakdown")
st.sidebar.page_link("pages/3_Head_to_Head.py", label="Head-to-Head")
st.sidebar.page_link("pages/4_Historical.py", label="Historical Comparison")
st.sidebar.page_link("pages/11_Sprint_Analysis.py", label="Sprint Analysis")

st.sidebar.markdown("**Explore**")
st.sidebar.page_link("pages/5_Circuit_Map.py", label="Circuit Map")
st.sidebar.page_link("pages/6_Driver_Profiles.py", label="Driver Profiles")
st.sidebar.page_link("pages/9_Race_Calendar.py", label="Race Calendar")
st.sidebar.page_link("pages/12_Safety_Stats.py", label="Safety & DNF Stats")

st.sidebar.markdown("**Fun**")
st.sidebar.page_link("pages/7_GOAT_Calculator.py", label="GOAT Calculator")
st.sidebar.page_link("pages/8_What_If.py", label="What-If Simulator")
st.sidebar.page_link("pages/10_Trivia.py", label="F1 Trivia Quiz")
st.sidebar.page_link("pages/13_Predictions.py", label="Prediction Tracker")

# Landing page stats
from db.connection import get_db

with get_db() as conn:
    season_count = conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]
    race_count = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    driver_count = conn.execute("SELECT COUNT(*) FROM drivers").fetchone()[0]

col1, col2, col3 = st.columns(3)
col1.metric("Seasons Loaded", season_count)
col2.metric("Races", race_count)
col3.metric("Drivers", driver_count)

if season_count == 0:
    st.info("No data loaded yet. Head to **Load Data** in the sidebar to get started.")

"""F1 Analytics Dashboard — entry point and navigation."""

import streamlit as st

from db.schema import init_db

st.set_page_config(
    page_title="Box-Box",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Idempotent — only runs DDL on first launch.
init_db()

# Sidebar styling: hide Streamlit's auto-rendered nav (we render our own
# below with collapsible groups) and shrink the sidebar to ~240px since the
# default 336px dominates a 1366px screen and our labels fit easily.
st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] { display: none !important; }
    section[data-testid="stSidebar"] {
        width: 240px !important;
        min-width: 240px !important;
        max-width: 240px !important;
    }
    section[data-testid="stSidebar"] > div:first-child {
        width: 240px !important;
    }
    /* Tighter spacing inside expanders so groups read like a menu, not cards */
    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        border: none;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] details {
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# -- Page registry ---------------------------------------------------------
# Each page is created once and used twice: once in the navigation dict
# (which handles routing) and once via st.page_link in our custom sidebar.

# Live Race is the default landing page — it's the marquee feature, and it
# falls back to the most recent completed session when no race is running,
# so it's never empty.
live_race_page = st.Page("pages/14_Live_Race.py", title="Live Race", default=True)

# Each tuple: (group_label, [page, ...])
GROUPS: list[tuple[str, list[st.Page]]] = [
    ("Live", [
        live_race_page,
    ]),
    ("This Season", [
        st.Page("pages/1_Season_Tracker.py", title="Standings"),
        st.Page("pages/9_Race_Calendar.py", title="Race Calendar"),
        st.Page("pages/2_Race_Breakdown.py", title="Race Breakdown"),
        st.Page("pages/11_Sprint_Analysis.py", title="Sprint Analysis"),
        st.Page("pages/16_Championship_Momentum.py", title="Championship Momentum"),
    ]),
    ("Drivers", [
        st.Page("pages/6_Driver_Profiles.py", title="Driver Profiles"),
        st.Page("pages/3_Head_to_Head.py", title="Head-to-Head"),
    ]),
    ("Circuits", [
        st.Page("pages/5_Circuit_Map.py", title="Circuit Map"),
    ]),
    ("Play", [
        st.Page("pages/7_GOAT_Calculator.py", title="GOAT Calculator"),
        st.Page("pages/8_What_If.py", title="What-If Simulator"),
        st.Page("pages/10_Trivia.py", title="Trivia"),
        st.Page("pages/13_Predictions.py", title="Prediction Tracker"),
    ]),
    ("Records & History", [
        st.Page("pages/18_Driver_Profiles_Historical.py", title="Historical Driver Profiles"),
        st.Page("pages/19_Head_to_Head_Historical.py", title="Historical Head-to-Head"),
        st.Page("pages/4_Historical.py", title="Era Comparison"),
        st.Page("pages/15_Pit_Stop_Records.py", title="Pit Stop Records"),
        st.Page("pages/17_Lap_Time_Evolution.py", title="Lap Time Evolution"),
        st.Page("pages/12_Safety_Stats.py", title="DNF Analysis"),
    ]),
    ("Settings", [
        st.Page("pages/0_Load_Data.py", title="Load Data"),
    ]),
]

# Flatten for st.navigation — it just needs the registry, position="hidden"
# means it handles routing without rendering anything.
nav_dict: dict[str, list[st.Page]] = {label: pages for label, pages in GROUPS}

current = st.navigation(nav_dict, position="hidden")


# -- Custom sidebar (collapsed groups by default) --------------------------
with st.sidebar:
    for group_label, pages in GROUPS:
        # Auto-expand the group containing the current page, so the user
        # always sees where they are without losing context.
        contains_current = any(p.url_path == current.url_path for p in pages)
        with st.expander(group_label, expanded=contains_current):
            for page in pages:
                st.page_link(page)


# Run the routed page
current.run()

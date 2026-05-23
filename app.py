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

# Pitwall theme — broadcast-graphics-inspired CSS layered on top of the
# config.toml palette. Hides Streamlit's auto-nav (we render our own),
# tightens the sidebar, and gives headings + metrics a more F1-broadcast
# feel (uppercase, condensed letter-spacing, red accent under page titles).
st.markdown(
    """
    <style>
    /* --- Sidebar: hide auto-nav, narrow width, flatten expander chrome --- */
    [data-testid="stSidebarNav"] { display: none !important; }
    section[data-testid="stSidebar"] {
        width: 240px !important;
        min-width: 240px !important;
        max-width: 240px !important;
        background: linear-gradient(180deg, #15161D 0%, #0F1015 100%);
        border-right: 1px solid #25262F;
    }
    section[data-testid="stSidebar"] > div:first-child { width: 240px !important; }
    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        border: none;
        margin-bottom: 0 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] details {
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
        font-size: 11px !important;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: #B0B2BD;
        font-weight: 600;
        padding-top: 2px !important;
        padding-bottom: 2px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.25rem !important;
    }
    section[data-testid="stSidebar"] a[data-testid="stPageLink"] {
        font-size: 14px !important;
        padding: 4px 8px !important;
        border-radius: 4px !important;
    }

    /* --- Headings: broadcast-style condensed weight + red accent --- */
    h1, h2, h3 {
        letter-spacing: -0.01em;
        font-weight: 700;
    }
    h1 {
        text-transform: uppercase;
        letter-spacing: 0.02em;
        border-bottom: 2px solid #E10600;
        padding-bottom: 8px;
        margin-bottom: 16px !important;
    }
    h2 {
        text-transform: uppercase;
        font-size: 1.15rem !important;
        letter-spacing: 0.04em;
        color: #F5F5F7;
        margin-top: 1.5rem !important;
    }
    h3 {
        text-transform: uppercase;
        font-size: 0.95rem !important;
        letter-spacing: 0.06em;
        color: #B0B2BD;
    }

    /* --- Metric cards: bigger, monospace numerics for that timing-board feel --- */
    [data-testid="stMetric"] {
        background: #15161D;
        border: 1px solid #25262F;
        border-radius: 4px;
        padding: 10px 14px;
    }
    [data-testid="stMetricValue"] {
        font-family: "JetBrains Mono", "SF Mono", "Roboto Mono", Menlo, monospace !important;
        font-size: 1.6rem !important;
        font-weight: 600;
        color: #F5F5F7;
    }
    [data-testid="stMetricLabel"] {
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 11px !important;
        color: #888A95 !important;
    }

    /* --- Buttons: filled F1 red --- */
    .stButton > button[kind="primary"] {
        background: #E10600;
        border: none;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .stButton > button[kind="primary"]:hover { background: #B30500; }

    /* --- Data tables: thinner borders, subtle row striping --- */
    [data-testid="stDataFrame"] {
        border: 1px solid #25262F;
        border-radius: 4px;
    }

    /* --- Captions: match broadcast-graphic muted look --- */
    .stCaption, [data-testid="stCaptionContainer"] {
        color: #888A95 !important;
        font-size: 12px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# Plotly always-visible modebar — patches st.plotly_chart so every chart
# call gets a consistent toolbar (with the reset-axes button visible) and
# Plotly's logo dropped. Avoids touching 37 individual call sites.
_original_plotly_chart = st.plotly_chart


def _plotly_chart_with_modebar(*args, **kwargs):
    config = dict(kwargs.get("config") or {})
    config.setdefault("displaylogo", False)
    config.setdefault("displayModeBar", True)
    kwargs["config"] = config
    return _original_plotly_chart(*args, **kwargs)


st.plotly_chart = _plotly_chart_with_modebar


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
        st.Page("pages/8_What_If.py", title="What-If Simulator"),
    ]),
    ("Records & History", [
        st.Page("pages/18_Driver_Profiles_Historical.py", title="Historical Driver Profiles"),
        st.Page("pages/19_Head_to_Head_Historical.py", title="Historical Head-to-Head"),
        st.Page("pages/4_Historical.py", title="Era Comparison"),
        st.Page("pages/15_Pit_Stop_Records.py", title="Pit Stop Records"),
        st.Page("pages/17_Lap_Time_Evolution.py", title="Lap Time Evolution"),
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

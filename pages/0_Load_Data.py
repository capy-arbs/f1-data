"""Data loading page — select seasons to fetch from the API."""

from datetime import datetime

import streamlit as st

from data.loader import load_all_race_winners, load_season, load_seasons
from db.connection import get_db
from db.schema import init_db

init_db()

st.title("Load F1 Data")
st.markdown("Select which seasons to download from the API and store locally.")

# Load seasons list first
with get_db() as conn:
    season_count = conn.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]

if season_count == 0:
    st.info("Fetching available seasons...")
    with get_db() as conn:
        count = load_seasons(conn)
    st.success(f"Found {count} seasons (1950–present)")
    st.rerun()

# Show available seasons
with get_db() as conn:
    all_seasons = [
        r["year"] for r in conn.execute(
            "SELECT year FROM seasons ORDER BY year DESC"
        ).fetchall()
    ]
    loaded = set(
        r["season"] for r in conn.execute(
            "SELECT DISTINCT season FROM fetch_log WHERE endpoint='results' AND record_count > 0"
        ).fetchall()
    )

current_year = datetime.now().year
default_start = max(current_year - 4, 1950)

st.subheader("Quick Load Presets")
preset_col1, preset_col2, preset_col3 = st.columns(3)
if preset_col1.button("Modern Era (2000–Now)", use_container_width=True):
    st.session_state["load_from"] = 2000
    st.session_state["load_to"] = current_year
if preset_col2.button("Full History (1950–Now)", use_container_width=True):
    st.session_state["load_from"] = 1950
    st.session_state["load_to"] = current_year
if preset_col3.button("Last 10 Years", use_container_width=True):
    st.session_state["load_from"] = current_year - 10
    st.session_state["load_to"] = current_year

st.subheader("Custom Range")
col1, col2 = st.columns(2)
default_from = st.session_state.get("load_from", default_start)
default_to = st.session_state.get("load_to", current_year)
from_idx = all_seasons.index(default_from) if default_from in all_seasons else 0
to_idx = all_seasons.index(default_to) if default_to in all_seasons else 0
start_year = col1.selectbox("From", all_seasons, index=from_idx)
end_year = col2.selectbox("To", all_seasons, index=to_idx)

years_to_load = [y for y in range(start_year, end_year + 1) if y in all_seasons]
already = [y for y in years_to_load if y in loaded]
needed = [y for y in years_to_load if y not in loaded]

if already:
    st.info(f"Already loaded: {', '.join(map(str, already))}")
if needed:
    st.markdown(f"**Will load:** {', '.join(map(str, needed))}")
else:
    st.success("All selected seasons are already loaded!")

if needed and st.button("Load Selected Seasons", type="primary", use_container_width=True):
    progress = st.progress(0, text="Starting...")
    for i, year in enumerate(needed):
        def update(msg, pct, i=i):
            overall = (i + pct) / len(needed)
            progress.progress(overall, text=msg)

        with get_db() as conn:
            load_season(conn, year, progress_callback=update)

    progress.progress(1.0, text="Done!")
    st.success(f"Loaded {len(needed)} season(s) successfully!")
    st.balloons()

# Circuit winners archive — winner-only rows for every season, powering the
# Circuit Explorer's all-time stats. Separate from full-season loads: it's one
# API page per season, so the whole 1950–today backfill takes ~2 minutes.
st.divider()
st.subheader("Circuit Winners Archive")
with get_db() as conn:
    winner_seasons = conn.execute(
        "SELECT COUNT(DISTINCT season) FROM circuit_race_winners"
    ).fetchone()[0]
st.caption(
    f"All-time race winners per circuit (Circuit Explorer stats): "
    f"{winner_seasons} of {current_year - 1949} seasons."
)
if st.button("Backfill All Seasons (1950–Now)", use_container_width=True):
    progress = st.progress(0, text="Starting winners backfill...")
    with get_db() as conn:
        load_all_race_winners(
            conn, progress_callback=lambda msg, pct: progress.progress(pct, text=msg)
        )
    progress.progress(1.0, text="Done!")
    st.success("Circuit winners archive is complete.")

# Show what's loaded
st.divider()
st.subheader("Loaded Data Summary")
with get_db() as conn:
    stats = conn.execute(
        """
        SELECT
            (SELECT COUNT(DISTINCT season) FROM races) as seasons,
            (SELECT COUNT(*) FROM races) as races,
            (SELECT COUNT(*) FROM drivers) as drivers,
            (SELECT COUNT(*) FROM results) as results
        """
    ).fetchone()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Seasons", stats["seasons"])
col2.metric("Races", stats["races"])
col3.metric("Drivers", stats["drivers"])
col4.metric("Results", stats["results"])

if stats["seasons"] > 0:
    with get_db() as conn:
        loaded_seasons = conn.execute(
            "SELECT DISTINCT season FROM races ORDER BY season"
        ).fetchall()
    st.caption(f"Seasons in database: {', '.join(str(r['season']) for r in loaded_seasons)}")

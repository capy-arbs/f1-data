"""Circuit Explorer — track outline view, race history, decade summaries."""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from db.schema import init_db
from db.connection import get_db
from queries.circuits import get_all_circuits, get_circuit_history
from queries.standings import get_available_seasons
from config import PLOTLY_TEMPLATE

init_db()

st.title("Circuit Explorer")

circuits = get_all_circuits()
if circuits.empty:
    st.warning("No circuit data loaded. Head to **Load Data** first.")
    st.stop()

# Only show circuits that have hosted races.
active = circuits[circuits["race_count"] > 0].copy()
if active.empty:
    st.warning("No race data found for any circuits.")
    st.stop()

# Split into Current vs Past based on the most-recent loaded season.
seasons = get_available_seasons()
latest_season = max(seasons) if seasons else None
if latest_season is not None:
    current = active[active["last_race"] == latest_season].sort_values("name")
    past = active[active["last_race"] != latest_season].sort_values("name")
else:
    current = active.iloc[0:0]
    past = active.sort_values("name")


# -- Filter: Current vs Past + circuit picker -----------------------------

filter_cols = st.columns([1, 3])
scope = filter_cols[0].radio(
    "Scope",
    options=["Current", "Past"],
    index=0 if not current.empty else 1,
    horizontal=True,
)
pool = current if scope == "Current" else past
if pool.empty:
    st.info(f"No circuits in '{scope}' for the current data load.")
    st.stop()

circuit_options = {
    f"{r['name']} — {r['locality']}, {r['country']}": idx
    for idx, r in pool.iterrows()
}
selected_label = filter_cols[1].selectbox("Circuit", list(circuit_options.keys()))
idx = circuit_options[selected_label]
circuit = pool.loc[idx]


# -- Header + key stats ---------------------------------------------------

st.subheader(circuit["name"])
st.caption(f"{circuit['locality']}, {circuit['country']}")

col1, col2, col3 = st.columns(3)
col1.metric("Races Held", int(circuit["race_count"]))
col2.metric("First Race", int(circuit["first_race"]) if circuit["first_race"] else "N/A")
col3.metric("Latest Race", int(circuit["last_race"]) if circuit["last_race"] else "N/A")


# -- Track outline view --------------------------------------------------
# Plotly Scattermapbox with the open-street-map base tiles. Zoom level 14
# is where track shapes become clearly visible in OSM data — much more
# informative than a generic location pin on a country-level map.

if circuit["lat"] and circuit["lng"]:
    st.subheader("Track outline")
    st.caption(
        "Pan and zoom to inspect the layout. OSM renders the track surface — drag to "
        "explore turns or zoom out for context."
    )
    fig = go.Figure(go.Scattermapbox(
        lat=[circuit["lat"]],
        lon=[circuit["lng"]],
        mode="markers",
        marker=dict(size=14, color="#E10600", opacity=0.9),
        hovertext=[circuit["name"]],
        hoverinfo="text",
    ))
    fig.update_layout(
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=circuit["lat"], lon=circuit["lng"]),
            zoom=14,
        ),
        height=520,
        margin=dict(t=10, b=0, l=0, r=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    with get_db() as conn:
        wiki = conn.execute(
            "SELECT url FROM circuits WHERE circuit_id=?", (circuit["circuit_id"],)
        ).fetchone()
    if wiki and wiki["url"]:
        st.caption(f"More on [Wikipedia]({wiki['url']})")


# -- Race history -------------------------------------------------------

st.divider()
st.subheader("Race history")
history = get_circuit_history(circuit["circuit_id"])

if not history.empty:
    winners = history[history["winner"].notna()]["winner"]
    if not winners.empty:
        win_counts = winners.value_counts()
        m1, m2 = st.columns(2)
        m1.metric("Most wins here", f"{win_counts.index[0]} ({win_counts.iloc[0]})")
        if len(win_counts) > 1:
            m2.metric("Runner-up", f"{win_counts.index[1]} ({win_counts.iloc[1]})")

    unique_winners = winners.nunique()
    st.caption(f"{unique_winners} different winners across {len(history)} races")

    history_with_winners = history[history["winner"].notna()].copy()
    if not history_with_winners.empty:
        history_with_winners["decade"] = (history_with_winners["season"] // 10) * 10
        decade_counts = history_with_winners.groupby("decade").size().reset_index(name="races")
        fig = go.Figure(go.Bar(
            x=decade_counts["decade"].astype(str) + "s",
            y=decade_counts["races"],
            marker_color="#E10600",
            text=decade_counts["races"],
            textposition="auto",
        ))
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            xaxis_title="Decade",
            yaxis_title="Races held",
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)

    display = history.rename(columns={
        "season": "Year", "race_name": "Race", "date": "Date",
        "winner": "Winner", "constructor": "Team",
    })
    st.dataframe(
        display[["Year", "Race", "Date", "Winner", "Team"]],
        hide_index=True,
        use_container_width=True,
    )


# -- All circuits at a glance -------------------------------------------

st.divider()
st.subheader(f"All {scope.lower()} circuits")
summary = pool[["name", "locality", "country", "race_count", "first_race", "last_race"]].copy()
summary = summary.sort_values("race_count", ascending=False)
summary.columns = ["Circuit", "City", "Country", "Races", "First", "Last"]
st.dataframe(summary, hide_index=True, use_container_width=True)

"""Circuit Map — explore F1 circuits with track layouts."""

import streamlit as st
import plotly.graph_objects as go

from db.schema import init_db
from db.connection import get_db
from queries.circuits import get_all_circuits, get_circuit_history
from config import PLOTLY_TEMPLATE

init_db()

st.title("Circuit Explorer")

circuits = get_all_circuits()
if circuits.empty:
    st.warning("No circuit data loaded. Head to **Load Data** first.")
    st.stop()

# Only show circuits that have hosted races
active_circuits = circuits[circuits["race_count"] > 0].copy()

if active_circuits.empty:
    st.warning("No race data found for any circuits.")
    st.stop()

# Circuit selector
circuit_options = {
    f"{r['name']} — {r['locality']}, {r['country']}": idx
    for idx, r in active_circuits.iterrows()
}

selected_label = st.selectbox("Select a circuit", list(circuit_options.keys()))
idx = circuit_options[selected_label]
circuit = active_circuits.loc[idx]

# Circuit header
st.subheader(circuit["name"])
st.caption(f"{circuit['locality']}, {circuit['country']}")

# Key stats
col1, col2, col3 = st.columns(3)
col1.metric("Races Held", int(circuit["race_count"]))
col2.metric("First Race", int(circuit["first_race"]) if circuit["first_race"] else "N/A")
col3.metric("Latest Race", int(circuit["last_race"]) if circuit["last_race"] else "N/A")

# Track layout image from Wikipedia/Wikimedia
# The Ergast/Jolpica data includes Wikipedia URLs for circuits
# We construct a likely Wikimedia track layout image URL
st.divider()

with get_db() as conn:
    circuit_row = conn.execute(
        "SELECT url FROM circuits WHERE circuit_id=?", (circuit["circuit_id"],)
    ).fetchone()

if circuit_row and circuit_row["url"]:
    wiki_url = circuit_row["url"]
    st.markdown(f"[View on Wikipedia]({wiki_url})")

# Location map
if circuit["lat"] and circuit["lng"]:
    st.subheader("Location")
    import pandas as pd
    map_data = pd.DataFrame({
        "lat": [circuit["lat"]],
        "lon": [circuit["lng"]],
    })
    st.map(map_data, zoom=10)

# Race history
st.divider()
st.subheader("Race History")
history = get_circuit_history(circuit["circuit_id"])

if not history.empty:
    # Most successful driver at this circuit
    winners = history[history["winner"].notna()]["winner"]
    if not winners.empty:
        win_counts = winners.value_counts()
        col1, col2 = st.columns(2)
        col1.metric("Most Wins Here", f"{win_counts.index[0]} ({win_counts.iloc[0]})")
        if len(win_counts) > 1:
            col2.metric("2nd Most", f"{win_counts.index[1]} ({win_counts.iloc[1]})")

    # Unique winners chart
    unique_winners = winners.nunique()
    st.caption(f"{unique_winners} different winners across {len(history)} races")

    # Winners by decade
    history_with_winners = history[history["winner"].notna()].copy()
    if not history_with_winners.empty:
        history_with_winners["decade"] = (history_with_winners["season"] // 10) * 10

        fig = go.Figure()
        decade_counts = history_with_winners.groupby("decade").size().reset_index(name="races")
        fig.add_trace(go.Bar(
            x=decade_counts["decade"].astype(str) + "s",
            y=decade_counts["races"],
            marker_color="#E8002D",
            text=decade_counts["races"],
            textposition="auto",
        ))
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            xaxis_title="Decade",
            yaxis_title="Races Held",
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)

    # Full results table
    display = history.rename(columns={
        "season": "Year", "race_name": "Race", "date": "Date",
        "winner": "Winner", "constructor": "Team",
    })
    st.dataframe(
        display[["Year", "Race", "Date", "Winner", "Team"]],
        hide_index=True,
        use_container_width=True,
    )

# Other circuits at a glance
st.divider()
st.subheader("All Circuits")
st.caption("Sorted by number of races held")

summary = active_circuits[["name", "locality", "country", "race_count", "first_race", "last_race"]].copy()
summary = summary.sort_values("race_count", ascending=False)
summary.columns = ["Circuit", "City", "Country", "Races", "First", "Last"]
st.dataframe(summary, hide_index=True, use_container_width=True)

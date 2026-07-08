"""Circuit Explorer — track outline view, race history, decade summaries."""

import plotly.graph_objects as go
import streamlit as st

from config import PLOTLY_TEMPLATE
from data.circuit_facts import FIRST_GRAND_PRIX
from data.track_geojson import get_track_outline
from db.connection import get_db
from db.schema import init_db
from queries.circuits import get_all_circuits, get_circuit_history

init_db()

st.title("Circuit Explorer")

circuits = get_all_circuits()
if circuits.empty:
    st.warning("No circuit data loaded. Head to **Load Data** first.")
    st.stop()

# Circuits that have hosted a race, plus new ones on this season's calendar
# whose race hasn't run yet (they'd have race_count 0).
active = circuits[(circuits["race_count"] > 0) | (circuits["on_current_calendar"] == 1)].copy()
if active.empty:
    st.warning("No race data found for any circuits.")
    st.stop()

# Current = on this season's calendar (even before its race runs); Past = the rest.
current = active[active["on_current_calendar"] == 1].sort_values("name")
past = active[active["on_current_calendar"] != 1].sort_values("name")


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

# F1-championship stats come from the complete winners archive; the "First
# Grand Prix" metric adds the circuit's pre-championship history (e.g. Spa
# 1925) from the Wikipedia-curated facts, when it predates the F1 era.
fact = FIRST_GRAND_PRIX.get(circuit["circuit_id"])
if fact:
    col1, col_gp, col2, col3 = st.columns(4)
    col_gp.metric("First Grand Prix", fact[0], help=fact[1])
else:
    col1, col2, col3 = st.columns(3)
col1.metric("F1 Races Held", int(circuit["race_count"]),
            help="World Championship races at this circuit, 1950–today")
col2.metric("First F1 Race", int(circuit["first_race"]) if circuit["first_race"] else "N/A")
col3.metric("Latest F1 Race", int(circuit["last_race"]) if circuit["last_race"] else "N/A")


# -- Track outline view --------------------------------------------------
# Renders the actual track shape as a Plotly line plot, F1.com-style:
# clean SVG-like outline on the dark theme, no map background, equal
# aspect ratio so the geometry isn't squished. GeoJSON sourced from the
# bacinger/f1-circuits repo (MIT licensed).

st.subheader("Track outline")
outline = get_track_outline(
    circuit["circuit_id"],
    lat=circuit.get("lat"),
    lng=circuit.get("lng"),
)

if outline:
    coords = outline["coords"]
    props = outline.get("props", {})
    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]

    fig = go.Figure()
    # Subtle "shadow" trace under the main line for a touch of depth.
    fig.add_trace(go.Scatter(
        x=lngs, y=lats, mode="lines",
        line=dict(color="rgba(225, 6, 0, 0.18)", width=18),
        hoverinfo="skip", showlegend=False,
    ))
    # The track itself. No start/finish marker — the bacinger GeoJSON
    # files don't encode where the start/finish line is; LineStrings just
    # begin wherever the author drew them from. A marker on coords[0]
    # would be inaccurate per-circuit.
    fig.add_trace(go.Scatter(
        x=lngs, y=lats, mode="lines",
        line=dict(color="#E10600", width=4, shape="spline"),
        hoverinfo="skip", showlegend=False,
    ))

    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False, scaleanchor="x", scaleratio=1)
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        height=520,
        margin=dict(t=10, b=10, l=10, r=10),
        plot_bgcolor="#0A0B0F",
        paper_bgcolor="#0A0B0F",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Surface track metadata from the GeoJSON properties.
    meta_cols = st.columns(3)
    if props.get("length"):
        meta_cols[0].caption(f"**Track length:** {props['length']} m")
    if props.get("opened"):
        meta_cols[1].caption(f"**Opened:** {props['opened']}")
    if props.get("firstgp"):
        meta_cols[2].caption(f"**First GP:** {props['firstgp']}")
else:
    # Track outline data not available — fall back to a quick OSM map view
    # so users still get a sense of location without the empty state.
    if circuit["lat"] and circuit["lng"]:
        st.caption("No track outline available for this circuit — showing location on a map instead.")
        fig = go.Figure(go.Scattermapbox(
            lat=[circuit["lat"]], lon=[circuit["lng"]],
            mode="markers",
            marker=dict(size=14, color="#E10600", opacity=0.9),
            hovertext=[circuit["name"]], hoverinfo="text",
        ))
        fig.update_layout(
            mapbox=dict(style="open-street-map",
                        center=dict(lat=circuit["lat"], lon=circuit["lng"]), zoom=14),
            height=420,
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

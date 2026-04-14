"""Safety & DNF Statistics — retirement analysis across all seasons."""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from db.schema import init_db
from db.connection import get_db
from config import PLOTLY_TEMPLATE

init_db()

st.title("Safety & DNF Statistics")

MECHANICAL = {"Engine", "Gearbox", "Transmission", "Hydraulics", "Electrical",
              "Brakes", "Suspension", "Clutch", "Throttle", "Oil pressure",
              "Water pressure", "Fuel pressure", "Exhaust", "Turbo",
              "Power Unit", "ERS", "Fuel system", "Water leak", "Oil leak",
              "Overheating", "Radiator", "Wheel", "Tyre", "Driveshaft",
              "Power loss", "Technical", "Battery", "Fuel leak"}

RACING_INCIDENT = {"Accident", "Collision", "Spun off", "Collision damage",
                   "Damage", "Withdrew", "Fatal accident", "Injured"}

FINISHED_PREFIXES = {"Finished", "+"}


def categorize_status(status: str) -> str:
    if not status:
        return "Other"
    if status == "Finished" or status.startswith("+"):
        return "Finished"
    if status in MECHANICAL:
        return "Mechanical"
    if status in RACING_INCIDENT:
        return "Racing Incident"
    return "Other"


@st.cache_data(ttl=3600)
def get_all_results_with_status() -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, r.race_name, r.round, res.status, res.position,
                   d.driver_id, d.given_name || ' ' || d.family_name as driver_name,
                   d.code, ci.name as circuit, ci.country,
                   c.name as constructor
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            JOIN drivers d ON res.driver_id = d.driver_id
            JOIN circuits ci ON r.circuit_id = ci.circuit_id
            JOIN constructors c ON res.constructor_id = c.constructor_id
            """
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


df = get_all_results_with_status()
if df.empty:
    st.warning("No data loaded. Head to **Load Data** first.")
    st.stop()

df["category"] = df["status"].apply(categorize_status)
dnfs = df[df["category"] != "Finished"]

# --- DNF Overview ---
st.subheader("DNF Overview")
col1, col2, col3 = st.columns(3)
col1.metric("Total Entries", len(df))
col2.metric("Total DNFs", len(dnfs))
col3.metric("DNF Rate", f"{100 * len(dnfs) / len(df):.1f}%")

# Category breakdown
st.subheader("DNF Categories")
cat_counts = dnfs["category"].value_counts().reset_index()
cat_counts.columns = ["Category", "Count"]
colors = {"Mechanical": "#E8002D", "Racing Incident": "#FF8000", "Other": "#888888"}

fig = px.pie(
    cat_counts, values="Count", names="Category",
    color="Category", color_discrete_map=colors,
    template=PLOTLY_TEMPLATE, hole=0.4,
)
fig.update_layout(height=350)
st.plotly_chart(fig, use_container_width=True)

# Most common DNF reasons
st.subheader("Most Common DNF Reasons")
reason_counts = dnfs["status"].value_counts().head(20).reset_index()
reason_counts.columns = ["Status", "Count"]

fig = px.bar(
    reason_counts, x="Count", y="Status", orientation="h",
    template=PLOTLY_TEMPLATE, color="Count",
    color_continuous_scale="YlOrRd",
)
fig.update_layout(height=500, yaxis=dict(autorange="reversed"))
st.plotly_chart(fig, use_container_width=True)

# DNF rate by season
st.subheader("DNF Rate by Season")
season_stats = df.groupby("season").agg(
    total=("status", "count"),
    dnfs=("category", lambda x: (x != "Finished").sum()),
).reset_index()
season_stats["dnf_rate"] = 100 * season_stats["dnfs"] / season_stats["total"]

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=season_stats["season"], y=season_stats["dnf_rate"],
    mode="lines+markers", line=dict(color="#E8002D", width=2),
    fill="tozeroy", fillcolor="rgba(232, 0, 45, 0.15)",
))
fig.update_layout(
    template=PLOTLY_TEMPLATE, xaxis_title="Season",
    yaxis_title="DNF Rate (%)", height=400,
)
st.plotly_chart(fig, use_container_width=True)

# Mechanical vs Racing breakdown by season
st.subheader("Mechanical vs Racing Incidents by Season")
mech_by_season = dnfs[dnfs["category"] == "Mechanical"].groupby("season").size().reset_index(name="Mechanical")
race_by_season = dnfs[dnfs["category"] == "Racing Incident"].groupby("season").size().reset_index(name="Racing Incident")
breakdown = pd.merge(mech_by_season, race_by_season, on="season", how="outer").fillna(0)

fig = go.Figure()
fig.add_trace(go.Bar(x=breakdown["season"], y=breakdown["Mechanical"], name="Mechanical", marker_color="#E8002D"))
fig.add_trace(go.Bar(x=breakdown["season"], y=breakdown["Racing Incident"], name="Racing Incident", marker_color="#FF8000"))
fig.update_layout(
    template=PLOTLY_TEMPLATE, barmode="stack",
    xaxis_title="Season", yaxis_title="DNFs", height=400,
)
st.plotly_chart(fig, use_container_width=True)

# Most dangerous circuits
st.subheader("Highest DNF Rate by Circuit")
circuit_stats = df.groupby(["circuit", "country"]).agg(
    total=("status", "count"),
    dnfs=("category", lambda x: (x != "Finished").sum()),
).reset_index()
circuit_stats["dnf_rate"] = 100 * circuit_stats["dnfs"] / circuit_stats["total"]
circuit_stats = circuit_stats[circuit_stats["total"] >= 20].sort_values("dnf_rate", ascending=False).head(20)

fig = px.bar(
    circuit_stats, x="dnf_rate", y="circuit", orientation="h",
    template=PLOTLY_TEMPLATE, text=circuit_stats["dnf_rate"].round(1),
    labels={"dnf_rate": "DNF Rate (%)", "circuit": "Circuit"},
)
fig.update_layout(height=500, yaxis=dict(autorange="reversed"))
st.plotly_chart(fig, use_container_width=True)

# Most DNF-prone drivers
st.subheader("Most DNF-Prone Drivers")
min_races = st.slider("Minimum races", 20, 200, 50, key="dnf_min")
driver_stats = df.groupby(["driver_name", "code"]).agg(
    total=("status", "count"),
    dnfs=("category", lambda x: (x != "Finished").sum()),
).reset_index()
driver_stats["dnf_rate"] = 100 * driver_stats["dnfs"] / driver_stats["total"]
driver_stats = driver_stats[driver_stats["total"] >= min_races]

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Highest DNF Rate**")
    worst = driver_stats.sort_values("dnf_rate", ascending=False).head(15)
    st.dataframe(
        worst[["driver_name", "total", "dnfs", "dnf_rate"]]
        .rename(columns={"driver_name": "Driver", "total": "Races", "dnfs": "DNFs", "dnf_rate": "DNF %"})
        .style.format({"DNF %": "{:.1f}"}),
        hide_index=True, use_container_width=True,
    )

with col2:
    st.markdown("**Most Reliable (Lowest DNF Rate)**")
    best = driver_stats.sort_values("dnf_rate").head(15)
    st.dataframe(
        best[["driver_name", "total", "dnfs", "dnf_rate"]]
        .rename(columns={"driver_name": "Driver", "total": "Races", "dnfs": "DNFs", "dnf_rate": "DNF %"})
        .style.format({"DNF %": "{:.1f}"}),
        hide_index=True, use_container_width=True,
    )

"""Lap Time Evolution — fastest race lap at one circuit, year by year."""

import plotly.graph_objects as go
import streamlit as st

from config import PLOTLY_TEMPLATE
from db.schema import init_db
from queries.circuits import get_all_circuits
from queries.historical import get_lap_time_evolution

init_db()

st.title("Lap Time Evolution")
st.caption(
    "Fastest race lap recorded at a circuit, year by year. "
    "Captures regulation eras, ground-effect shifts, and refuelling changes "
    "in the bend of the curve. Note: F1's 'fastest lap' field only goes back "
    "to 2004 in the source data."
)

circuits = get_all_circuits()
if circuits.empty:
    st.warning("No circuit data loaded.")
    st.stop()

# Show circuits that actually have multi-season race history; sort by usage.
circuits = circuits[circuits["race_count"] >= 3].sort_values("race_count", ascending=False)
labels = {
    f"{r['name']} ({r['country']}) — {int(r['race_count'])} races": r["circuit_id"]
    for _, r in circuits.iterrows()
}

choice = st.selectbox("Circuit", list(labels.keys()))
circuit_id = labels[choice]

df = get_lap_time_evolution(circuit_id)
if df.empty:
    st.info(
        "No fastest-lap data for this circuit. Older races (pre-2004) and many "
        "non-championship venues didn't record one in the source feed."
    )
    st.stop()

# Year-on-year line + per-race scatter
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=df["season"], y=df["lap_seconds"],
    mode="lines+markers",
    line=dict(color="#FF8000", width=2.5),
    marker=dict(size=8, color="#FFD43B", line=dict(color="#222", width=1)),
    hovertemplate="<b>%{x}</b><br>Time: %{y:.3f}s<br>%{customdata[0]} (%{customdata[1]})<extra></extra>",
    customdata=df[["driver", "constructor"]].values,
    name="Fastest lap",
))
# Highlight all-time best
best = df.loc[df["lap_seconds"].idxmin()]
fig.add_trace(go.Scatter(
    x=[best["season"]], y=[best["lap_seconds"]],
    mode="markers",
    marker=dict(size=16, color="#FF3333", symbol="star", line=dict(color="white", width=1)),
    name=f"All-time best: {best['driver']} ({int(best['season'])})",
))

fig.update_layout(
    template=PLOTLY_TEMPLATE,
    title=f"Fastest race lap — {choice}",
    xaxis_title="Season",
    yaxis_title="Lap time (s)",
    height=460,
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    margin=dict(t=60, b=40, l=50, r=20),
)
# Inverted y so faster (lower) is "up" — more intuitive for evolution.
fig.update_yaxes(autorange="reversed")
st.plotly_chart(fig, use_container_width=True)

# Decade-over-decade summary
df_by_decade = df.copy()
df_by_decade["decade"] = (df_by_decade["season"] // 10) * 10
summary = (
    df_by_decade.groupby("decade", as_index=False)
    .agg(
        races=("season", "count"),
        avg_seconds=("lap_seconds", "mean"),
        best_seconds=("lap_seconds", "min"),
    )
    .sort_values("decade")
)
summary["avg_seconds"] = summary["avg_seconds"].round(3)
summary["best_seconds"] = summary["best_seconds"].round(3)
st.subheader("By decade")
st.dataframe(
    summary.rename(columns={
        "decade": "Decade",
        "races": "Races",
        "avg_seconds": "Avg lap (s)",
        "best_seconds": "Best lap (s)",
    }),
    hide_index=True,
    use_container_width=True,
)

# Headline records
m1, m2, m3 = st.columns(3)
m1.metric("All-time best", f"{best['lap_seconds']:.3f}s")
m2.metric("Set by", f"{best['driver']}")
m3.metric("Year", int(best["season"]))

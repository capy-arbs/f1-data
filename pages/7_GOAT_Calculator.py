"""GOAT Calculator — rank all-time greats with custom weights."""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from db.schema import init_db
from db.connection import get_db
from config import PLOTLY_TEMPLATE

init_db()

st.title("GOAT Calculator")
st.markdown("Adjust the weights to see how different priorities change the all-time rankings.")

from queries.standings import get_available_seasons
loaded = get_available_seasons()
if loaded:
    st.caption(f"Data covers: **{min(loaded)}–{max(loaded)}** ({len(loaded)} seasons). "
               f"Load more seasons for more accurate all-time rankings.")


@st.cache_data(ttl=3600)
def get_all_driver_stats(min_races: int = 20) -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.driver_id, d.given_name, d.family_name, d.code,
                   COUNT(*) as races,
                   SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN res.position <= 3 AND res.position IS NOT NULL THEN 1 ELSE 0 END) as podiums,
                   SUM(CASE WHEN res.grid = 1 THEN 1 ELSE 0 END) as poles,
                   SUM(res.points) as total_points,
                   ROUND(100.0 * SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as win_rate,
                   ROUND(SUM(res.points) / COUNT(*), 2) as points_per_race
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            GROUP BY res.driver_id
            HAVING COUNT(*) >= ?
            """,
            (min_races,),
        ).fetchall()

        df = pd.DataFrame([dict(r) for r in rows])
        if df.empty:
            return df

        # Add championship count
        for idx, row in df.iterrows():
            champs = conn.execute(
                """
                SELECT COUNT(*) as titles FROM driver_standings ds
                WHERE ds.driver_id=? AND ds.position=1
                  AND ds.round = (SELECT MAX(round) FROM driver_standings WHERE season=ds.season)
                """,
                (row["driver_id"],),
            ).fetchone()[0]
            df.at[idx, "championships"] = champs

    return df


# Weight sliders
st.sidebar.header("GOAT Weights")
w_wins = st.sidebar.slider("Wins", 0, 100, 25)
w_podiums = st.sidebar.slider("Podiums", 0, 100, 15)
w_poles = st.sidebar.slider("Poles", 0, 100, 10)
w_ppr = st.sidebar.slider("Points per Race", 0, 100, 20)
w_winrate = st.sidebar.slider("Win Rate (%)", 0, 100, 15)
w_champs = st.sidebar.slider("Championships", 0, 100, 30)
w_longevity = st.sidebar.slider("Longevity (Races)", 0, 100, 5)

min_races = st.sidebar.number_input("Minimum races to qualify", 10, 200, 20)

df = get_all_driver_stats(min_races)
if df.empty:
    st.warning("No driver data available. Load some seasons first.")
    st.stop()

# Normalize each metric to 0-100 scale
def normalize(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return series * 0
    return 100 * (series - mn) / (mx - mn)

df["n_wins"] = normalize(df["wins"])
df["n_podiums"] = normalize(df["podiums"])
df["n_poles"] = normalize(df["poles"])
df["n_ppr"] = normalize(df["points_per_race"])
df["n_winrate"] = normalize(df["win_rate"])
df["n_champs"] = normalize(df["championships"])
df["n_longevity"] = normalize(df["races"])

# Calculate weighted GOAT score
total_weight = w_wins + w_podiums + w_poles + w_ppr + w_winrate + w_champs + w_longevity
if total_weight == 0:
    total_weight = 1

df["goat_score"] = (
    df["n_wins"] * w_wins +
    df["n_podiums"] * w_podiums +
    df["n_poles"] * w_poles +
    df["n_ppr"] * w_ppr +
    df["n_winrate"] * w_winrate +
    df["n_champs"] * w_champs +
    df["n_longevity"] * w_longevity
) / total_weight

df = df.sort_values("goat_score", ascending=False).reset_index(drop=True)
df["driver"] = df["given_name"] + " " + df["family_name"]

# Top 20 table
st.subheader("Top 20 All-Time Rankings")
top20 = df.head(20).copy()
top20.index = range(1, len(top20) + 1)
top20.index.name = "Rank"

st.dataframe(
    top20[["driver", "goat_score", "races", "wins", "podiums", "poles",
           "championships", "win_rate", "points_per_race"]]
    .rename(columns={
        "driver": "Driver", "goat_score": "GOAT Score", "races": "Races",
        "wins": "Wins", "podiums": "Podiums", "poles": "Poles",
        "championships": "Titles", "win_rate": "Win %", "points_per_race": "Pts/Race",
    })
    .style.format({"GOAT Score": "{:.1f}", "Win %": "{:.1f}", "Pts/Race": "{:.1f}"}),
    use_container_width=True,
)

# Bar chart
st.subheader("GOAT Score Distribution")
fig = go.Figure(go.Bar(
    x=top20["goat_score"],
    y=top20["driver"],
    orientation="h",
    marker_color=px.colors.sequential.YlOrRd_r[:len(top20)],
    text=top20["goat_score"].round(1),
    textposition="auto",
))
fig.update_layout(
    template=PLOTLY_TEMPLATE,
    yaxis=dict(autorange="reversed"),
    xaxis_title="GOAT Score",
    height=600,
    margin=dict(l=150),
)
st.plotly_chart(fig, use_container_width=True)

# Radar chart of top 5
st.subheader("Top 5 — Radar Comparison")
top5 = df.head(5)
categories = ["Wins", "Podiums", "Poles", "Pts/Race", "Win Rate", "Titles", "Longevity"]
norm_cols = ["n_wins", "n_podiums", "n_poles", "n_ppr", "n_winrate", "n_champs", "n_longevity"]
colors = ["#E8002D", "#3671C6", "#27F4D2", "#FF8000", "#229971"]

fig = go.Figure()
for i, (_, row) in enumerate(top5.iterrows()):
    values = [row[c] for c in norm_cols]
    values.append(values[0])
    fig.add_trace(go.Scatterpolar(
        r=values,
        theta=categories + [categories[0]],
        fill="toself",
        name=row["driver"],
        line_color=colors[i],
        opacity=0.6,
    ))

fig.update_layout(
    polar=dict(bgcolor="rgba(0,0,0,0)"),
    template=PLOTLY_TEMPLATE,
    height=500,
    showlegend=True,
)
st.plotly_chart(fig, use_container_width=True)

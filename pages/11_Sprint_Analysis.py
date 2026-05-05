"""Sprint Analysis — sprint race results and stats (2021+)."""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from db.schema import init_db
from db.connection import get_db
from config import PLOTLY_TEMPLATE

init_db()

st.title("Sprint Race Analysis")
st.markdown("Sprint races have been part of F1 since 2021. Explore results and stats here.")


@st.cache_data(ttl=3600)
def get_sprint_seasons() -> list[int]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT r.season
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            ORDER BY r.season DESC
            """
        ).fetchall()
    return [r["season"] for r in rows]


def get_sprint_races(season: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT r.round, r.race_name
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            WHERE r.season = ?
            ORDER BY r.round
            """,
            (season,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_sprint_results(season: int, round_num: int) -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT sr.grid, sr.position, sr.position_text, sr.points,
                   sr.laps, sr.status, sr.time_text,
                   d.code, d.given_name, d.family_name,
                   c.name as constructor, c.constructor_id
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            JOIN drivers d ON sr.driver_id = d.driver_id
            JOIN constructors c ON sr.constructor_id = c.constructor_id
            WHERE r.season = ? AND r.round = ?
            ORDER BY CASE WHEN sr.position IS NOT NULL THEN sr.position ELSE 999 END
            """,
            (season, round_num),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_sprint_points_by_driver(season: int) -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.given_name || ' ' || d.family_name as driver,
                   d.code, SUM(sr.points) as sprint_points,
                   COUNT(*) as sprint_races,
                   SUM(CASE WHEN sr.position = 1 THEN 1 ELSE 0 END) as sprint_wins
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            JOIN drivers d ON sr.driver_id = d.driver_id
            WHERE r.season = ?
            GROUP BY sr.driver_id
            HAVING sprint_points > 0
            ORDER BY sprint_points DESC
            """,
            (season,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_sprint_vs_race(season: int) -> pd.DataFrame:
    """Compare sprint grid/finish to main race grid/finish."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.round, r.race_name,
                   d.code, d.given_name || ' ' || d.family_name as driver,
                   sr.position as sprint_pos, sr.grid as sprint_grid,
                   res.position as race_pos, res.grid as race_grid
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            JOIN drivers d ON sr.driver_id = d.driver_id
            LEFT JOIN results res ON sr.race_id = res.race_id AND sr.driver_id = res.driver_id
            WHERE r.season = ?
            ORDER BY r.round, sr.position
            """,
            (season,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


sprint_seasons = get_sprint_seasons()
if not sprint_seasons:
    st.warning("No sprint data loaded. Load seasons from 2021 onwards and re-fetch to include sprint results.")
    st.stop()

season = st.selectbox("Season", sprint_seasons, key="sprint_season")

# Sprint points leaderboard
st.subheader(f"{season} Sprint Points")
points_df = get_sprint_points_by_driver(season)
if not points_df.empty:
    fig = px.bar(
        points_df.head(15), x="sprint_points", y="driver", orientation="h",
        template=PLOTLY_TEMPLATE, text="sprint_points",
        color="sprint_points", color_continuous_scale="YlOrRd",
    )
    fig.update_layout(yaxis=dict(autorange="reversed"), height=450, xaxis_title="Sprint Points")
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        points_df.rename(columns={
            "driver": "Driver", "sprint_points": "Sprint Pts",
            "sprint_races": "Sprints", "sprint_wins": "Sprint Wins",
        }),
        hide_index=True, use_container_width=True,
    )

# Individual sprint results
st.divider()
st.subheader("Sprint Race Results")
sprint_races = get_sprint_races(season)
if sprint_races:
    race_opts = {f"R{r['round']}: {r['race_name']}": r["round"] for r in sprint_races}
    selected_race = st.selectbox("Select Sprint", list(race_opts.keys()))
    round_num = race_opts[selected_race]

    sprint_df = get_sprint_results(season, round_num)
    if not sprint_df.empty:
        display = sprint_df.copy()
        display["Driver"] = display["code"].fillna(display["family_name"])
        st.dataframe(
            display[["position_text", "Driver", "constructor", "grid", "points", "status"]]
            .rename(columns={
                "position_text": "Pos", "constructor": "Team",
                "grid": "Grid", "points": "Pts", "status": "Status",
            }),
            hide_index=True, use_container_width=True,
        )

# Sprint vs Main Race comparison
st.divider()
st.subheader("Sprint vs Main Race Performance")
comparison = get_sprint_vs_race(season)
if not comparison.empty:
    # Average position difference
    valid = comparison[(comparison["sprint_pos"].notna()) & (comparison["race_pos"].notna())].copy()
    if not valid.empty:
        valid["sprint_better"] = valid["race_pos"] - valid["sprint_pos"]
        driver_avg = valid.groupby(["driver", "code"]).agg(
            avg_sprint=("sprint_pos", "mean"),
            avg_race=("race_pos", "mean"),
            diff=("sprint_better", "mean"),
        ).reset_index().sort_values("diff", ascending=False)

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=driver_avg["diff"],
            y=driver_avg["code"],
            orientation="h",
            marker_color=["#22c55e" if d > 0 else "#ef4444" for d in driver_avg["diff"]],
            text=driver_avg["diff"].round(1),
            textposition="auto",
        ))
        fig.update_layout(
            template=PLOTLY_TEMPLATE, height=500,
            xaxis_title="Avg Position Difference (Sprint - Race, positive = better in sprints)",
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Positive = driver performs better in sprints than the main race on average")

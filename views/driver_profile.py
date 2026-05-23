"""Shared renderer for the Driver Profiles pages (current grid + full archive)."""

import streamlit as st
import plotly.graph_objects as go

from db.connection import get_db
from queries.drivers import (
    get_career_stats,
    get_season_stats,
    get_driver_seasons,
    get_season_supplements,
)
from queries.standings import get_available_seasons
from config import PLOTLY_TEMPLATE


def render(drivers, title: str, caption: str) -> None:
    st.title(title)
    st.caption(caption)

    if not drivers:
        st.warning("No data loaded. Head to **Load Data** first.")
        st.stop()

    driver_options = {f"{d['given_name']} {d['family_name']}": d["driver_id"] for d in drivers}
    selected_name = st.selectbox("Search for a driver", list(driver_options.keys()))
    driver_id = driver_options[selected_name]

    with get_db() as conn:
        driver_info = conn.execute(
            "SELECT * FROM drivers WHERE driver_id=?", (driver_id,)
        ).fetchone()
        driver_info = dict(driver_info) if driver_info else {}

        champs = conn.execute(
            """
            SELECT COUNT(*) as titles FROM driver_standings ds
            WHERE ds.driver_id=? AND ds.position=1
              AND ds.round = (SELECT MAX(round) FROM driver_standings WHERE season=ds.season)
            """,
            (driver_id,),
        ).fetchone()[0]

        teams = conn.execute(
            """
            SELECT DISTINCT c.constructor_id, c.name
            FROM results res
            JOIN constructors c ON res.constructor_id = c.constructor_id
            WHERE res.driver_id=?
            """,
            (driver_id,),
        ).fetchall()

    st.subheader(f"{driver_info.get('given_name', '')} {driver_info.get('family_name', '')}")
    st.caption(f"Nationality: {driver_info.get('nationality', 'N/A')} | "
               f"DOB: {driver_info.get('date_of_birth', 'N/A')} | "
               f"Number: {driver_info.get('number', 'N/A')}")

    driver_seasons = get_driver_seasons(driver_id)
    loaded_seasons = get_available_seasons()
    if driver_seasons and loaded_seasons:
        if min(driver_seasons) == min(loaded_seasons):
            st.warning(
                f"Stats below only cover loaded seasons ({min(loaded_seasons)}–{max(loaded_seasons)}). "
                f"This driver's career may extend further back — load more historical seasons for complete data."
            )

    stats = get_career_stats(driver_id)
    if stats:
        cols = st.columns(7)
        metrics = [
            ("Championships", champs),
            ("Races", stats.get("races", 0)),
            ("Wins", stats.get("wins", 0)),
            ("Podiums", stats.get("podiums", 0)),
            ("Poles", stats.get("poles", 0)),
            ("Points", f"{stats.get('total_points', 0):.0f}"),
            ("DNFs", stats.get("dnfs", 0)),
        ]
        for col, (label, val) in zip(cols, metrics):
            col.metric(label, val)

    if teams:
        st.subheader("Teams")
        st.markdown(" | ".join([t["name"] for t in teams]))

    st.subheader("Season-by-Season Results")
    season_df = get_season_stats(driver_id)
    if not season_df.empty:
        # Single-query enrichment with champ position + team per season.
        # Replaced an N+1 loop (2 queries/season) on 2026-05-23.
        suppl = get_season_supplements(driver_id)
        if not suppl.empty:
            season_df = season_df.merge(suppl, on="season", how="left")
            season_df["champ_pos"] = season_df["champ_pos"].astype("Int64")
        else:
            season_df["champ_pos"] = None
            season_df["team"] = ""

        display = season_df.rename(columns={
            "season": "Year", "team": "Team", "races": "Races", "wins": "Wins",
            "podiums": "Podiums", "poles": "Poles", "points": "Points",
            "dnfs": "DNFs", "champ_pos": "Champ Pos",
        })
        st.dataframe(
            display[["Year", "Team", "Races", "Wins", "Podiums", "Poles", "Points", "DNFs", "Champ Pos"]],
            hide_index=True,
            use_container_width=True,
        )

        st.subheader("Cumulative Wins Over Career")
        season_df = season_df.sort_values("season")
        season_df["cum_wins"] = season_df["wins"].cumsum()

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=season_df["season"],
            y=season_df["cum_wins"],
            mode="lines+markers",
            line=dict(color="#E10600", width=3),
            fill="tozeroy",
            fillcolor="rgba(225, 6, 0, 0.15)",
        ))
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            xaxis_title="Season",
            yaxis_title="Total Wins",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Points Per Season")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=season_df["season"],
            y=season_df["points"],
            marker_color="#3671C6",
        ))
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            xaxis_title="Season",
            yaxis_title="Points",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

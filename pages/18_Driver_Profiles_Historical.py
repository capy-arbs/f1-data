"""Historical Driver Profiles — full archive of every driver in the database."""

import streamlit as st
import plotly.graph_objects as go

from db.schema import init_db
from db.connection import get_db
from queries.drivers import get_all_drivers, get_career_stats, get_season_stats
from config import PLOTLY_TEMPLATE, TEAM_COLORS

init_db()

st.title("Historical Driver Profiles")
st.caption("Every driver in the database, 1950 to present. For just the current grid, use **Drivers → Driver Profiles**.")

drivers = get_all_drivers()
if not drivers:
    st.warning("No data loaded. Head to **Load Data** first.")
    st.stop()

driver_options = {f"{d['given_name']} {d['family_name']}": d["driver_id"] for d in drivers}
selected_name = st.selectbox("Search for a driver", list(driver_options.keys()))
driver_id = driver_options[selected_name]

# Get driver info
with get_db() as conn:
    driver_info = conn.execute(
        "SELECT * FROM drivers WHERE driver_id=?", (driver_id,)
    ).fetchone()
    driver_info = dict(driver_info) if driver_info else {}

    # Championships
    champs = conn.execute(
        """
        SELECT COUNT(*) as titles FROM driver_standings ds
        WHERE ds.driver_id=? AND ds.position=1
          AND ds.round = (SELECT MAX(round) FROM driver_standings WHERE season=ds.season)
        """,
        (driver_id,),
    ).fetchone()[0]

    # Teams driven for
    teams = conn.execute(
        """
        SELECT DISTINCT c.constructor_id, c.name
        FROM results res
        JOIN constructors c ON res.constructor_id = c.constructor_id
        WHERE res.driver_id=?
        """,
        (driver_id,),
    ).fetchall()

# Header
st.subheader(f"{driver_info.get('given_name', '')} {driver_info.get('family_name', '')}")
st.caption(f"Nationality: {driver_info.get('nationality', 'N/A')} | "
           f"DOB: {driver_info.get('date_of_birth', 'N/A')} | "
           f"Number: {driver_info.get('number', 'N/A')}")

# Data coverage warning
from queries.drivers import get_driver_seasons
from queries.standings import get_available_seasons
driver_seasons = get_driver_seasons(driver_id)
loaded_seasons = get_available_seasons()
if driver_seasons and loaded_seasons:
    if min(driver_seasons) == min(loaded_seasons):
        st.warning(
            f"Stats below only cover loaded seasons ({min(loaded_seasons)}–{max(loaded_seasons)}). "
            f"This driver's career may extend further back — load more historical seasons for complete data."
        )

# Career stats
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

# Teams
if teams:
    st.subheader("Teams")
    team_chips = []
    for t in teams:
        color = TEAM_COLORS.get(t["constructor_id"], "#888")
        team_chips.append(f":{color[1:]}[**{t['name']}**]" if len(color) == 7 else f"**{t['name']}**")
    st.markdown(" | ".join([t["name"] for t in teams]))

# Season-by-season
st.subheader("Season-by-Season Results")
season_df = get_season_stats(driver_id)
if not season_df.empty:
    # Add championship finish position
    with get_db() as conn:
        for idx, row in season_df.iterrows():
            pos = conn.execute(
                """
                SELECT position FROM driver_standings
                WHERE driver_id=? AND season=?
                  AND round = (SELECT MAX(round) FROM driver_standings WHERE season=?)
                """,
                (driver_id, int(row["season"]), int(row["season"])),
            ).fetchone()
            season_df.at[idx, "champ_pos"] = int(pos["position"]) if pos else None

        # Add team for each season
        for idx, row in season_df.iterrows():
            team = conn.execute(
                """
                SELECT DISTINCT c.name FROM results res
                JOIN constructors c ON res.constructor_id = c.constructor_id
                JOIN races r ON res.race_id = r.race_id
                WHERE res.driver_id=? AND r.season=?
                """,
                (driver_id, int(row["season"])),
            ).fetchone()
            season_df.at[idx, "team"] = team["name"] if team else ""

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

    # Cumulative wins chart
    st.subheader("Cumulative Wins Over Career")
    season_df = season_df.sort_values("season")
    season_df["cum_wins"] = season_df["wins"].cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=season_df["season"],
        y=season_df["cum_wins"],
        mode="lines+markers",
        line=dict(color="#E8002D", width=3),
        fill="tozeroy",
        fillcolor="rgba(232, 0, 45, 0.15)",
    ))
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        xaxis_title="Season",
        yaxis_title="Total Wins",
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Points per season chart
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

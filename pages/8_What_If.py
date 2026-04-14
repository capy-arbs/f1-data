"""What-If Simulator — alternate championship outcomes."""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from db.schema import init_db
from db.connection import get_db
from queries.standings import get_available_seasons
from config import PLOTLY_TEMPLATE, POINT_SYSTEMS

init_db()

st.title("What-If Simulator")


def get_season_results(season: int) -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.round, r.race_name, res.driver_id,
                   d.given_name || ' ' || d.family_name as driver_name,
                   d.code, res.position, res.points, res.grid,
                   c.name as constructor
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            JOIN drivers d ON res.driver_id = d.driver_id
            JOIN constructors c ON res.constructor_id = c.constructor_id
            WHERE r.season = ?
            ORDER BY r.round, res.position
            """,
            (season,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_season_drivers(season: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT d.driver_id, d.given_name || ' ' || d.family_name as name, d.code
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            JOIN races r ON res.race_id = r.race_id
            WHERE r.season = ?
            ORDER BY d.family_name
            """,
            (season,),
        ).fetchall()
    return [dict(r) for r in rows]


def calculate_standings(results: pd.DataFrame) -> pd.DataFrame:
    standings = results.groupby(["driver_id", "driver_name", "code"]).agg(
        total_points=("points", "sum"),
        wins=("position", lambda x: (x == 1).sum()),
        podiums=("position", lambda x: ((x >= 1) & (x <= 3)).sum()),
        races=("position", "count"),
    ).reset_index()
    standings = standings.sort_values(
        ["total_points", "wins"], ascending=[False, False]
    ).reset_index(drop=True)
    standings.index = standings.index + 1
    standings.index.name = "Pos"
    return standings


seasons = get_available_seasons()
if not seasons:
    st.warning("No data loaded. Head to **Load Data** first.")
    st.stop()

tab1, tab2 = st.tabs(["Driver Swap", "Alternative Points System"])

# --- Tab 1: Driver Swap ---
with tab1:
    st.subheader("What if a driver had someone else's results?")
    st.markdown("Swap one driver's results with another's and see how the championship changes.")

    season = st.selectbox("Season", seasons, key="swap_season")
    results = get_season_results(season)

    if results.empty:
        st.warning("No results for this season.")
        st.stop()

    drivers_list = get_season_drivers(season)
    driver_opts = {d["name"]: d["driver_id"] for d in drivers_list}

    col1, col2 = st.columns(2)
    replace_name = col1.selectbox("Replace this driver", list(driver_opts.keys()), key="replace")
    with_name = col2.selectbox("With this driver's results", list(driver_opts.keys()), index=1, key="with")

    replace_id = driver_opts[replace_name]
    with_id = driver_opts[with_name]

    # Original standings
    original = calculate_standings(results)

    # Modified: replace driver A's results with driver B's
    if replace_id != with_id:
        modified_results = results.copy()
        source_results = results[results["driver_id"] == with_id].copy()

        # For each round, give the replaced driver the source driver's position/points
        for _, src_row in source_results.iterrows():
            mask = (modified_results["driver_id"] == replace_id) & (modified_results["round"] == src_row["round"])
            if mask.any():
                modified_results.loc[mask, "position"] = src_row["position"]
                modified_results.loc[mask, "points"] = src_row["points"]

        modified = calculate_standings(modified_results)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Original Standings**")
            st.dataframe(
                original[["driver_name", "total_points", "wins"]].rename(
                    columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
                ).head(15),
                use_container_width=True,
            )
        with col2:
            st.markdown(f"**{replace_name} with {with_name}'s results**")
            st.dataframe(
                modified[["driver_name", "total_points", "wins"]].rename(
                    columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
                ).head(15),
                use_container_width=True,
            )

        # Visual comparison
        fig = go.Figure()
        top_drivers = original.head(10)["driver_name"].tolist()
        for driver in top_drivers:
            orig_pts = original[original["driver_name"] == driver]["total_points"].values
            mod_pts = modified[modified["driver_name"] == driver]["total_points"].values
            orig_val = orig_pts[0] if len(orig_pts) > 0 else 0
            mod_val = mod_pts[0] if len(mod_pts) > 0 else 0
            color = "#22c55e" if mod_val > orig_val else "#ef4444" if mod_val < orig_val else "#888"
            fig.add_trace(go.Bar(name=driver, x=["Original", "What-If"], y=[orig_val, mod_val],
                                 marker_color=color, showlegend=True))
        fig.update_layout(
            template=PLOTLY_TEMPLATE, barmode="group", height=450,
            yaxis_title="Points", legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Pick two different drivers to see the what-if scenario!")

# --- Tab 2: Alternative Points System ---
with tab2:
    st.subheader("What if a different points system was used?")

    season2 = st.selectbox("Season", seasons, key="pts_season")
    target_system = st.selectbox("Apply points system", list(POINT_SYSTEMS.keys()))
    points_map = POINT_SYSTEMS[target_system]

    results2 = get_season_results(season2)
    if results2.empty:
        st.warning("No results for this season.")
    else:
        original2 = calculate_standings(results2)

        # Recalculate with new points
        recalc = results2.copy()
        recalc["points"] = recalc["position"].apply(
            lambda p: float(points_map.get(int(p), 0)) if pd.notna(p) else 0.0
        )
        modified2 = calculate_standings(recalc)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Original Points**")
            st.dataframe(
                original2[["driver_name", "total_points", "wins"]].rename(
                    columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
                ).head(15),
                use_container_width=True,
            )
        with col2:
            st.markdown(f"**Under {target_system} system**")
            st.dataframe(
                modified2[["driver_name", "total_points", "wins"]].rename(
                    columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
                ).head(15),
                use_container_width=True,
            )

        # Position changes
        st.subheader("Position Changes")
        orig_rank = {row["driver_name"]: i + 1 for i, (_, row) in enumerate(original2.iterrows())}
        mod_rank = {row["driver_name"]: i + 1 for i, (_, row) in enumerate(modified2.iterrows())}

        changes = []
        for driver in orig_rank:
            orig_pos = orig_rank[driver]
            mod_pos = mod_rank.get(driver, orig_pos)
            diff = orig_pos - mod_pos  # positive = moved up
            if diff != 0:
                changes.append({"Driver": driver, "Original": orig_pos, "New": mod_pos, "Change": diff})

        if changes:
            change_df = pd.DataFrame(changes).sort_values("Change", ascending=False)
            fig = go.Figure(go.Bar(
                x=change_df["Change"],
                y=change_df["Driver"],
                orientation="h",
                marker_color=["#22c55e" if c > 0 else "#ef4444" for c in change_df["Change"]],
                text=change_df["Change"].apply(lambda x: f"+{x}" if x > 0 else str(x)),
                textposition="auto",
            ))
            fig.update_layout(
                template=PLOTLY_TEMPLATE, yaxis=dict(autorange="reversed"),
                xaxis_title="Position Change (positive = moved up)", height=500,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.success("No position changes under this system!")

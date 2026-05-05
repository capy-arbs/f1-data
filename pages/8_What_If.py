"""What-If Simulator — alternate championship outcomes.

Three thought experiments stacked into tabs:

1. Driver Swap — give one driver another driver's race-by-race results.
2. Alternative Points System — replay a season under different scoring rules.
3. Single-Race Override — change a single race result and watch the
   standings shift, with cascading position adjustments for everyone behind.
"""

from __future__ import annotations

import math

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from db.schema import init_db
from db.connection import get_db
from queries.standings import get_available_seasons, get_rounds_for_season
from config import PLOTLY_TEMPLATE, POINT_SYSTEMS

init_db()

st.title("What-If Simulator")
st.markdown(
    "Three tools for asking *what if?* about a season — give a driver someone else's "
    "year, replay under a different points system, or rewrite a single race result."
)


# -- Shared helpers ---------------------------------------------------------

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


def points_system_for(season: int) -> dict[int, int]:
    """Pick the points table that applies to ``season``."""
    if season >= 2010:
        return POINT_SYSTEMS["2010-present"]
    if season >= 2003:
        return POINT_SYSTEMS["2003-2009"]
    if season >= 1991:
        return POINT_SYSTEMS["1991-2002"]
    if season >= 1961:
        return POINT_SYSTEMS["1961-1990"]
    return POINT_SYSTEMS["1950-1960"]


seasons = get_available_seasons()
if not seasons:
    st.warning("No data loaded. Head to **Load Data** first.")
    st.stop()


tab1, tab2, tab3 = st.tabs([
    "Driver Swap",
    "Alternative Points System",
    "Single Race Override",
])


# ===========================================================================
# Tab 1 — Driver Swap
# ===========================================================================

with tab1:
    with st.container(border=True):
        st.markdown(
            "**Give one driver another driver's season.** Driver A's race-by-race "
            "results get replaced with Driver B's (positions, points, the lot). "
            "Driver B keeps their own results unchanged — this isn't a trade, "
            "it's a transplant. The championship is then recomputed from scratch."
        )
        st.caption(
            "Example: *Replace Verstappen with Norris* in 2024 → Verstappen now finishes "
            "wherever Norris finished, race by race. The question being asked: "
            "*if Verstappen had had Norris's season instead of his own, where would he end up?* "
            "A two-way swap would just shuffle two names in the standings table — the asymmetric version is the one that produces an actual answer."
        )

    season = st.selectbox("Season", seasons, key="swap_season")
    results = get_season_results(season)
    if results.empty:
        st.warning("No results for this season.")
        st.stop()

    drivers_list = get_season_drivers(season)
    driver_opts = {d["name"]: d["driver_id"] for d in drivers_list}

    col1, col2 = st.columns(2)
    replace_name = col1.selectbox("Replace this driver", list(driver_opts.keys()), key="replace")
    with_name = col2.selectbox(
        "With this driver's results", list(driver_opts.keys()),
        index=1 if len(driver_opts) > 1 else 0, key="with",
    )

    replace_id = driver_opts[replace_name]
    with_id = driver_opts[with_name]

    original = calculate_standings(results)

    if replace_id != with_id:
        modified_results = results.copy()
        source_results = results[results["driver_id"] == with_id].copy()
        for _, src in source_results.iterrows():
            mask = (modified_results["driver_id"] == replace_id) & (modified_results["round"] == src["round"])
            if mask.any():
                modified_results.loc[mask, "position"] = src["position"]
                modified_results.loc[mask, "points"] = src["points"]
        modified = calculate_standings(modified_results)

        col1, col2 = st.columns(2)
        col1.markdown("**Original**")
        col1.dataframe(
            original[["driver_name", "total_points", "wins"]].rename(
                columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
            ).head(15),
            use_container_width=True,
        )
        col2.markdown(f"**{replace_name} with {with_name}'s results**")
        col2.dataframe(
            modified[["driver_name", "total_points", "wins"]].rename(
                columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
            ).head(15),
            use_container_width=True,
        )

        # Visual delta
        fig = go.Figure()
        top_drivers = original.head(10)["driver_name"].tolist()
        for driver in top_drivers:
            orig_val = original[original["driver_name"] == driver]["total_points"].values
            mod_val = modified[modified["driver_name"] == driver]["total_points"].values
            o = orig_val[0] if len(orig_val) > 0 else 0
            m = mod_val[0] if len(mod_val) > 0 else 0
            color = "#22c55e" if m > o else "#ef4444" if m < o else "#888"
            fig.add_trace(go.Bar(name=driver, x=["Original", "What-If"], y=[o, m], marker_color=color))
        fig.update_layout(template=PLOTLY_TEMPLATE, barmode="group", height=450, yaxis_title="Points")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Pick two different drivers to see the what-if scenario.")


# ===========================================================================
# Tab 2 — Alternative Points System
# ===========================================================================

with tab2:
    with st.container(border=True):
        st.markdown(
            "**Replay a season under different scoring rules.** F1 has used six "
            "different points systems since 1950; pick a season, pick a system, "
            "and the standings recompute from each driver's actual finishing positions."
        )
        st.caption(
            "Use this to ask: were the era-champions still champions under modern scoring? "
            "Which fifth-place finishers would've been on the podium under 2010-present rules? "
            "**Note:** only base finish points are recalculated — fastest-lap bonuses and "
            "sprint points stick with the original recipient."
        )

    season2 = st.selectbox("Season", seasons, key="pts_season")
    target_system = st.selectbox("Apply points system", list(POINT_SYSTEMS.keys()))
    points_map = POINT_SYSTEMS[target_system]

    results2 = get_season_results(season2)
    if results2.empty:
        st.warning("No results for this season.")
    else:
        original2 = calculate_standings(results2)

        recalc = results2.copy()
        recalc["points"] = recalc["position"].apply(
            lambda p: float(points_map.get(int(p), 0)) if pd.notna(p) else 0.0
        )
        modified2 = calculate_standings(recalc)

        col1, col2 = st.columns(2)
        col1.markdown("**Original**")
        col1.dataframe(
            original2[["driver_name", "total_points", "wins"]].rename(
                columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
            ).head(15),
            use_container_width=True,
        )
        col2.markdown(f"**Under {target_system}**")
        col2.dataframe(
            modified2[["driver_name", "total_points", "wins"]].rename(
                columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
            ).head(15),
            use_container_width=True,
        )

        st.subheader("Position changes")
        orig_rank = {row["driver_name"]: i + 1 for i, (_, row) in enumerate(original2.iterrows())}
        mod_rank = {row["driver_name"]: i + 1 for i, (_, row) in enumerate(modified2.iterrows())}
        changes = []
        for driver, op in orig_rank.items():
            mp = mod_rank.get(driver, op)
            diff = op - mp
            if diff != 0:
                changes.append({"Driver": driver, "Original": op, "New": mp, "Change": diff})

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
                template=PLOTLY_TEMPLATE,
                yaxis=dict(autorange="reversed"),
                xaxis_title="Position change (positive = moved up)",
                height=500,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.success("No position changes under this system.")


# ===========================================================================
# Tab 3 — Single Race Override (NEW)
# ===========================================================================

with tab3:
    with st.container(border=True):
        st.markdown(
            "**Change a single race result and watch the standings shift.** Pick a "
            "race, a driver, and what would have happened to them — *finished P3 "
            "instead of retiring*, *won instead of losing the lead on the last lap*. "
            "Other drivers cascade up or down by one position to make room."
        )
        st.caption(
            "**Cascade rule:** if Verstappen moves from DNF to P3, everyone originally "
            "P3 and below shifts down one spot. Stack multiple overrides for compound "
            "what-ifs (\"P3 at Monaco AND wins Hungary\"). Points are recomputed using "
            "that season's points system; fastest-lap and sprint bonuses are left alone."
        )

    override_season = st.selectbox("Season", seasons, key="ov_season")
    rounds = get_rounds_for_season(override_season)
    if not rounds:
        st.warning("No races for this season.")
        st.stop()

    season_results = get_season_results(override_season)
    if season_results.empty:
        st.warning("No race results for this season.")
        st.stop()

    # ---- Override builder UI ---------------------------------------------
    cols = st.columns([2, 2, 1])
    round_opts = {f"R{r['round']}: {r['race_name']}": r["round"] for r in rounds
                  if r["round"] in season_results["round"].values}
    round_label = cols[0].selectbox("Race", list(round_opts.keys()), key="ov_race")
    round_num = round_opts[round_label]

    race_drivers = season_results[season_results["round"] == round_num][["driver_id", "driver_name", "position"]].drop_duplicates("driver_id")
    race_drivers = race_drivers.sort_values("driver_name")
    drv_label = cols[1].selectbox(
        "Driver",
        race_drivers["driver_name"].tolist(),
        key="ov_driver",
    )
    drv_row = race_drivers[race_drivers["driver_name"] == drv_label].iloc[0]
    drv_id = drv_row["driver_id"]
    orig_pos = drv_row["position"]
    orig_pos_str = "DNF" if pd.isna(orig_pos) else f"P{int(orig_pos)}"

    pos_options = ["DNF"] + [f"P{i}" for i in range(1, 21)]
    new_pos_label = cols[2].selectbox(
        f"New result (was {orig_pos_str})",
        pos_options,
        index=0 if pd.isna(orig_pos) else int(orig_pos),
        key="ov_newpos",
    )

    btn_cols = st.columns([1, 1, 4])
    if btn_cols[0].button("Apply override", type="primary", key="ov_apply"):
        st.session_state.setdefault("overrides", []).append({
            "season": override_season,
            "round": round_num,
            "race": round_label,
            "driver_id": drv_id,
            "driver_name": drv_label,
            "orig_pos": None if pd.isna(orig_pos) else int(orig_pos),
            "new_pos": None if new_pos_label == "DNF" else int(new_pos_label[1:]),
        })
    if btn_cols[1].button("Clear all", key="ov_clear"):
        st.session_state["overrides"] = []

    overrides = [o for o in st.session_state.get("overrides", []) if o["season"] == override_season]

    if not overrides:
        st.info("Apply an override above to see the simulated standings.")
        st.stop()

    # ---- Active override list -------------------------------------------
    st.subheader("Active overrides")
    ov_df = pd.DataFrame([
        {
            "Race": o["race"],
            "Driver": o["driver_name"],
            "Original": "DNF" if o["orig_pos"] is None else f"P{o['orig_pos']}",
            "New": "DNF" if o["new_pos"] is None else f"P{o['new_pos']}",
        }
        for o in overrides
    ])
    st.dataframe(ov_df, hide_index=True, use_container_width=True)

    # ---- Apply overrides with cascade insertion ------------------------
    points_map = points_system_for(override_season)
    modified = season_results.copy()

    def _recompute_points(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["points"] = df["position"].apply(
            lambda p: float(points_map.get(int(p), 0)) if pd.notna(p) else 0.0
        )
        return df

    for ov in overrides:
        rd = ov["round"]
        race_mask = modified["round"] == rd
        if not race_mask.any():
            continue
        race_slice = modified[race_mask].copy().sort_values("position", na_position="last")

        d_mask = race_slice["driver_id"] == ov["driver_id"]
        if not d_mask.any():
            continue

        old_p = ov["orig_pos"]
        new_p = ov["new_pos"]

        # Step 1: vacate the chosen driver's old slot — drivers below shift up.
        if old_p is not None:
            shift_up = (race_slice["position"].notna()) & (race_slice["position"] > old_p)
            race_slice.loc[shift_up, "position"] = race_slice.loc[shift_up, "position"] - 1

        # Step 2: insert the chosen driver at the new slot — push others down.
        if new_p is not None:
            shift_down = (race_slice["position"].notna()) & (race_slice["position"] >= new_p) & (~d_mask)
            race_slice.loc[shift_down, "position"] = race_slice.loc[shift_down, "position"] + 1
            race_slice.loc[d_mask, "position"] = new_p
        else:
            # Becoming DNF — clear position; no further shift needed beyond step 1.
            race_slice.loc[d_mask, "position"] = None

        # Recompute points across the whole race using the season's points system.
        race_slice = _recompute_points(race_slice)
        modified = pd.concat([modified[~race_mask], race_slice], ignore_index=True)

    modified = modified.sort_values(["round", "position"], na_position="last").reset_index(drop=True)

    # ---- Show standings comparison -------------------------------------
    original = calculate_standings(season_results)
    new_standings = calculate_standings(modified)

    st.subheader("Standings impact")
    col1, col2 = st.columns(2)
    col1.markdown("**Original**")
    col1.dataframe(
        original[["driver_name", "total_points", "wins"]].rename(
            columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
        ).head(15),
        use_container_width=True,
    )
    col2.markdown("**With overrides applied**")
    col2.dataframe(
        new_standings[["driver_name", "total_points", "wins"]].rename(
            columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"}
        ).head(15),
        use_container_width=True,
    )

    # Position-change bar chart
    orig_rank = {r["driver_name"]: i + 1 for i, (_, r) in enumerate(original.iterrows())}
    new_rank = {r["driver_name"]: i + 1 for i, (_, r) in enumerate(new_standings.iterrows())}
    changes = []
    for d, op in orig_rank.items():
        np_ = new_rank.get(d, op)
        if np_ != op:
            changes.append({"Driver": d, "Change": op - np_})

    if changes:
        ch_df = pd.DataFrame(changes).sort_values("Change", ascending=False)
        fig = go.Figure(go.Bar(
            x=ch_df["Change"], y=ch_df["Driver"], orientation="h",
            marker_color=["#22c55e" if c > 0 else "#ef4444" for c in ch_df["Change"]],
            text=ch_df["Change"].apply(lambda x: f"+{x}" if x > 0 else str(x)),
            textposition="auto",
        ))
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            yaxis=dict(autorange="reversed"),
            xaxis_title="Championship position change (positive = moved up)",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No championship-position changes from these overrides.")

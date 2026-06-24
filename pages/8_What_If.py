"""What-If Simulator — alternate championship outcomes.

Three thought experiments stacked into tabs:

1. Driver Swap — give one driver another driver's race-by-race results.
2. Alternative Points System — replay a season under different scoring rules.
3. Single-Race Override — change a single race result and watch the
   standings shift, with cascading position adjustments for everyone behind.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from charts.what_if_charts import position_change_bar, standings_comparison_bar
from config import POINT_SYSTEMS
from data.normalizer import get_point_system_for_year
from db.schema import init_db
from queries.standings import get_available_seasons, get_rounds_for_season
from queries.what_if import (
    apply_driver_swap,
    apply_overrides,
    apply_points_system,
    calculate_standings,
    get_season_drivers,
    get_season_results,
    standings_rank_changes,
)

init_db()


def _standings_table(standings: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    """Top-``n`` slice of a standings frame with display-friendly column names."""
    return (
        standings[["driver_name", "total_points", "wins"]]
        .rename(columns={"driver_name": "Driver", "total_points": "Points", "wins": "Wins"})
        .head(n)
    )

st.title("What-If Simulator")
st.markdown(
    "Three tools for asking *what if?* about a season — give a driver someone else's "
    "year, replay under a different points system, or rewrite a single race result."
)


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
        modified = calculate_standings(apply_driver_swap(results, replace_id, with_id))

        col1, col2 = st.columns(2)
        col1.markdown("**Original**")
        col1.dataframe(_standings_table(original), use_container_width=True)
        col2.markdown(f"**{replace_name} with {with_name}'s results**")
        col2.dataframe(_standings_table(modified), use_container_width=True)

        st.plotly_chart(
            standings_comparison_bar(original, modified), use_container_width=True
        )
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
        modified2 = calculate_standings(apply_points_system(results2, points_map))

        col1, col2 = st.columns(2)
        col1.markdown("**Original**")
        col1.dataframe(_standings_table(original2), use_container_width=True)
        col2.markdown(f"**Under {target_system}**")
        col2.dataframe(_standings_table(modified2), use_container_width=True)

        st.subheader("Position changes")
        change_df = standings_rank_changes(original2, modified2)
        if not change_df.empty:
            st.plotly_chart(
                position_change_bar(change_df, "Position change (positive = moved up)"),
                use_container_width=True,
            )
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
    # Look up the default via the value, not an offset — works regardless of
    # how pos_options is constructed and won't silently break if the order
    # ever changes (e.g. inserting "Disqualified" at the front).
    new_pos_label = cols[2].selectbox(
        f"New result (was {orig_pos_str})",
        pos_options,
        index=pos_options.index(orig_pos_str),
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
    points_map = get_point_system_for_year(override_season)
    modified = apply_overrides(season_results, overrides, points_map)

    # ---- Show standings comparison -------------------------------------
    original = calculate_standings(season_results)
    new_standings = calculate_standings(modified)

    st.subheader("Standings impact")
    col1, col2 = st.columns(2)
    col1.markdown("**Original**")
    col1.dataframe(_standings_table(original), use_container_width=True)
    col2.markdown("**With overrides applied**")
    col2.dataframe(_standings_table(new_standings), use_container_width=True)

    change_df = standings_rank_changes(original, new_standings)
    if not change_df.empty:
        st.plotly_chart(
            position_change_bar(
                change_df,
                "Championship position change (positive = moved up)",
                height=400,
            ),
            use_container_width=True,
        )
    else:
        st.info("No championship-position changes from these overrides.")

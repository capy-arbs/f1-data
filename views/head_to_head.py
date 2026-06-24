"""Shared renderer for the Head-to-Head pages (current grid + full archive)."""

import streamlit as st

from charts.comparison_charts import (
    cumulative_wins_chart,
    h2h_qualifying_chart,
    season_comparison_bar,
)
from config import TEAM_COLORS
from queries.drivers import (
    get_career_stats,
    get_driver_seasons,
    get_head_to_head,
    get_latest_constructor,
    get_season_stats,
    get_teammate_seasons,
)
from queries.standings import get_available_seasons


def render(drivers, title: str, caption: str) -> None:
    st.title(title)
    st.caption(caption)

    if not drivers:
        st.warning("No data loaded. Head to **Load Data** first.")
        st.stop()

    driver_options = {f"{d['given_name']} {d['family_name']}": d["driver_id"] for d in drivers}
    driver_names = list(driver_options.keys())

    col1, col2 = st.columns(2)
    d1_name = col1.selectbox("Driver 1", driver_names, index=0)
    d2_name = col2.selectbox("Driver 2", driver_names, index=min(1, len(driver_names) - 1))

    d1_id = driver_options[d1_name]
    d2_id = driver_options[d2_name]

    if d1_id == d2_id:
        st.warning("Pick two different drivers!")
        st.stop()

    d1_color = TEAM_COLORS.get(get_latest_constructor(d1_id) or "")
    d2_color = TEAM_COLORS.get(get_latest_constructor(d2_id) or "")

    loaded_seasons = set(get_available_seasons())
    d1_seasons = set(get_driver_seasons(d1_id))
    d2_seasons = set(get_driver_seasons(d2_id))

    if d1_seasons or d2_seasons:
        d1_range = f"{min(d1_seasons)}–{max(d1_seasons)}" if d1_seasons else "N/A"
        d2_range = f"{min(d2_seasons)}–{max(d2_seasons)}" if d2_seasons else "N/A"
        loaded_range = f"{min(loaded_seasons)}–{max(loaded_seasons)}" if loaded_seasons else "N/A"

        st.caption(f"Data loaded: **{loaded_range}** | "
                   f"{d1_name.split()[-1]}: **{d1_range}** ({len(d1_seasons)} seasons) | "
                   f"{d2_name.split()[-1]}: **{d2_range}** ({len(d2_seasons)} seasons)")

        if loaded_seasons:
            min_loaded = min(loaded_seasons)
            for name, dseasons in [(d1_name, d1_seasons), (d2_name, d2_seasons)]:
                if dseasons and min(dseasons) == min_loaded:
                    st.warning(
                        f"**{name}** has data starting from {min_loaded} (the earliest loaded season). "
                        f"Their career may extend further back — load more historical seasons for complete stats."
                    )

    st.subheader("Career Stats")
    s1 = get_career_stats(d1_id)
    s2 = get_career_stats(d2_id)

    metrics = [
        ("Races", "races"),
        ("Wins", "wins"),
        ("Podiums", "podiums"),
        ("Poles", "poles"),
        ("Total Points", "total_points"),
        ("DNFs", "dnfs"),
    ]

    cols = st.columns(len(metrics))
    for col, (label, key) in zip(cols, metrics):
        v1 = s1.get(key, 0) or 0
        v2 = s2.get(key, 0) or 0
        col.metric(label, f"{v1} vs {v2}")
        if v1 > v2:
            col.caption(f":red[{d1_name.split()[-1]}]")
        elif v2 > v1:
            col.caption(f":blue[{d2_name.split()[-1]}]")
        else:
            col.caption("Tied")

    st.subheader("Points by Season")
    d1_season_df = get_season_stats(d1_id)
    d2_season_df = get_season_stats(d2_id)
    fig = season_comparison_bar(d1_season_df, d2_season_df, d1_name, d2_name, d1_color, d2_color)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Cumulative Wins")
    fig = cumulative_wins_chart(d1_season_df, d2_season_df, d1_name, d2_name, d1_color, d2_color)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Head-to-Head in Shared Races")
    h2h = get_head_to_head(d1_id, d2_id)
    if not h2h.empty:
        d1_won = ((h2h["d1_pos"].notna()) & (h2h["d2_pos"].notna()) & (h2h["d1_pos"] < h2h["d2_pos"])).sum()
        d2_won = ((h2h["d1_pos"].notna()) & (h2h["d2_pos"].notna()) & (h2h["d2_pos"] < h2h["d1_pos"])).sum()
        total = len(h2h)

        c1, c2, c3 = st.columns(3)
        c1.metric(f"{d1_name.split()[-1]} Wins", d1_won)
        c2.metric("Shared Races", total)
        c3.metric(f"{d2_name.split()[-1]} Wins", d2_won)
    else:
        st.info("These drivers never competed in the same race.")

    st.subheader("Teammate Comparison")
    teammate_df = get_teammate_seasons(d1_id, d2_id)
    if not teammate_df.empty:
        seasons_together = teammate_df["season"].unique()
        st.markdown(f"Teammates in: **{', '.join(map(str, sorted(seasons_together)))}**")

        st.markdown("**Qualifying Head-to-Head**")
        fig = h2h_qualifying_chart(teammate_df, d1_name, d2_name, d1_color, d2_color)
        st.plotly_chart(fig, use_container_width=True)

        both_finished = teammate_df[(teammate_df["d1_pos"].notna()) & (teammate_df["d2_pos"].notna())]
        d1_race_wins = (both_finished["d1_pos"] < both_finished["d2_pos"]).sum()
        d2_race_wins = (both_finished["d2_pos"] < both_finished["d1_pos"]).sum()
        st.markdown(f"**Race Finish H2H:** {d1_name.split()[-1]} {d1_race_wins} – {d2_race_wins} {d2_name.split()[-1]}")

        tm_points = teammate_df.groupby("season").agg(
            d1_pts=("d1_points", "sum"),
            d2_pts=("d2_points", "sum"),
        ).reset_index()
        tm_points.columns = ["Season", d1_name.split()[-1], d2_name.split()[-1]]
        st.dataframe(tm_points, hide_index=True, use_container_width=True)
    else:
        st.info("These drivers were never teammates.")

"""Live Race — real-time timing, Time-to-Strike predictor, weather and race control.

Pulls live data from OpenF1. When no race is in progress, defaults to the
most recent session so the page is always populated.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from db.schema import init_db
from data.live import (
    list_sessions,
    get_latest_session,
    get_drivers,
    get_intervals,
    get_position,
    get_laps,
    get_stints,
    get_weather,
    get_race_control,
    build_live_grid,
)
from queries.strike import compute_strike, all_strike_pairs
from charts.live_charts import stint_gantt, pace_trace_chart, gap_evolution_chart

init_db()

st.title("Live Race")
st.caption(
    "Real-time data from the F1 timing feed (via OpenF1). "
    "Falls back to the latest completed session when no race is running."
)


# -- Sidebar: session picker + auto-refresh --------------------------------

with st.sidebar:
    st.header("Live controls")
    use_latest = st.checkbox("Use latest available session", value=True)

    if use_latest:
        sess = get_latest_session()
        if not sess:
            st.error("Could not reach OpenF1. Check your connection.")
            st.stop()
    else:
        year = st.selectbox("Season", list(range(datetime.utcnow().year, 2017, -1)), index=0)
        sessions_df = list_sessions(year)
        if sessions_df.empty:
            st.warning("No sessions found for that year.")
            st.stop()
        sessions_df = sessions_df.copy()
        sessions_df["label"] = (
            sessions_df["country_name"].fillna(sessions_df["location"].fillna(""))
            + " — " + sessions_df["session_name"]
            + " (" + sessions_df["date_start"].dt.strftime("%Y-%m-%d") + ")"
        )
        choice = st.selectbox("Session", sessions_df["label"].tolist())
        sess = sessions_df[sessions_df["label"] == choice].iloc[0].to_dict()

    st.divider()
    auto_refresh = st.checkbox("Auto-refresh", value=False, help="Re-runs the page on a fixed interval.")
    interval = st.select_slider("Interval (s)", options=[10, 15, 30, 60], value=15, disabled=not auto_refresh)
    refresh = st.button("Refresh now", use_container_width=True)


session_key = sess["session_key"]
session_label = f"{sess.get('country_name') or sess.get('location', '?')} — {sess.get('session_name', 'Session')} {sess.get('year', '')}"

# Force-clear caches so 'Refresh now' actually fetches fresh data instead of serving from TTL.
if refresh:
    for fn in (get_intervals, get_position, get_laps, get_stints, get_weather, get_race_control):
        fn.clear()


# -- Header strip ----------------------------------------------------------

header_cols = st.columns([3, 1, 1, 1])
header_cols[0].subheader(session_label)

drivers = get_drivers(session_key)
intervals = get_intervals(session_key)
positions = get_position(session_key)
laps = get_laps(session_key)
stints = get_stints(session_key)
weather = get_weather(session_key)
rc = get_race_control(session_key)

current_lap = int(laps["lap_number"].max()) if not laps.empty else 0
header_cols[1].metric("Current Lap", current_lap if current_lap else "—")

if not weather.empty:
    last_w = weather.iloc[-1]
    header_cols[2].metric("Track", f"{last_w['track_temperature']:.1f}°C")
    header_cols[3].metric("Air", f"{last_w['air_temperature']:.1f}°C")

# A current flag/status read from the latest race-control message.
status = "Green"
if not rc.empty:
    latest_rc = rc.iloc[0]
    if latest_rc.get("flag") in ("RED", "YELLOW", "DOUBLE YELLOW"):
        status = latest_rc["flag"]
    elif latest_rc.get("category") == "SafetyCar":
        status = "Safety Car"
status_colors = {"Green": "🟢", "YELLOW": "🟡", "DOUBLE YELLOW": "🟡", "RED": "🔴", "Safety Car": "🟠"}
st.markdown(f"**Status:** {status_colors.get(status, '⚪')} {status}")
st.divider()


# -- Live standings table --------------------------------------------------

grid = build_live_grid(drivers, positions, intervals, laps, stints)

st.subheader("Live standings")
if grid.empty or "position" not in grid.columns:
    st.info("Standings unavailable for this session.")
else:
    show = grid.dropna(subset=["position"]).copy()
    show = show.sort_values("position")
    show["Pos"] = show["position"].astype("Int64")
    show["#"] = show["driver_number"]
    show["Driver"] = show["name_acronym"].fillna(show["full_name"])
    show["Team"] = show["team_name"]
    show["Gap"] = show["gap_to_leader"].apply(
        lambda v: f"+{v:.3f}" if pd.notna(v) else "—"
    )
    show["Interval"] = show["interval"].apply(
        lambda v: f"+{v:.3f}" if pd.notna(v) else "—"
    )
    show["Last Lap"] = show["lap_duration"].apply(
        lambda v: f"{v:.3f}" if pd.notna(v) else "—"
    )
    show["Tire"] = show.apply(
        lambda r: f"{r['compound']} ({int(r['tyre_age'])})" if pd.notna(r.get("compound")) and pd.notna(r.get("tyre_age")) else "—",
        axis=1,
    )
    st.dataframe(
        show[["Pos", "#", "Driver", "Team", "Gap", "Interval", "Last Lap", "Tire"]],
        hide_index=True,
        use_container_width=True,
    )


# -- Time-to-Strike widget -------------------------------------------------

st.divider()
st.subheader("Time to Strike")
st.caption("Pick a chaser and a target. We estimate how many laps until the chaser closes the gap, given current pace.")

if grid.empty:
    st.info("Need driver data to compute Time-to-Strike.")
else:
    sortable = grid.dropna(subset=["position"]).sort_values("position") if "position" in grid.columns else grid
    options = {
        f"P{int(r['position'])}: {r['name_acronym']}" if pd.notna(r.get("position")) else r["name_acronym"]: int(r["driver_number"])
        for _, r in sortable.iterrows()
        if pd.notna(r.get("driver_number"))
    }

    keys = list(options.keys())
    if len(keys) < 2:
        st.info("Need at least two drivers with current data.")
    else:
        c1, c2 = st.columns(2)
        # Default chaser to P2, target to P1.
        default_chaser_idx = 1 if len(keys) > 1 else 0
        default_target_idx = 0
        chaser_label = c1.selectbox("Chaser", keys, index=default_chaser_idx, key="strike_chaser")
        # Filter target to drivers ahead of chaser by default-friendly logic, but keep all selectable.
        target_label = c2.selectbox("Target (driver ahead)", keys, index=default_target_idx, key="strike_target")

        chaser_n = options[chaser_label]
        target_n = options[target_label]

        # Total laps unknown for many sessions — try to read from race-control "LAP X/Y" if available, else None.
        total_laps = None
        if not rc.empty and "message" in rc.columns:
            for msg in rc["message"].dropna().head(20):
                m = str(msg).upper()
                if "/" in m and "LAP" in m:
                    parts = m.split()
                    for p in parts:
                        if "/" in p and p.replace("/", "").isdigit():
                            try:
                                total_laps = int(p.split("/")[1])
                                break
                            except ValueError:
                                pass
                    if total_laps:
                        break

        result = compute_strike(chaser_n, target_n, intervals, laps, stints, drivers, total_laps=total_laps)

        # Big verdict card
        verdict_col, conf_col = st.columns([3, 1])
        verdict_col.metric(
            label=f"{result.chaser} → {result.target}",
            value=("—" if result.laps_to_catch is None else f"{result.laps_to_catch} laps"),
            delta=result.verdict,
            delta_color="off",
        )
        conf_emoji = {"high": "🟢 high", "medium": "🟡 medium", "low": "🔴 low", "unknown": "⚪ unknown"}
        conf_col.markdown(f"**Confidence**\n\n{conf_emoji.get(result.confidence, result.confidence)}")

        # Numeric breakdown
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Gap", f"{result.gap_seconds:.3f}s" if result.gap_seconds is not None else "—")
        m2.metric("Δ Pace", f"{result.pace_delta:+.2f}s/lap" if result.pace_delta is not None else "—")
        m3.metric("Chaser pace", f"{result.chaser_pace:.3f}s" if result.chaser_pace else "—")
        m4.metric("Target pace", f"{result.target_pace:.3f}s" if result.target_pace else "—")

        f = result.factors
        f_cols = st.columns(2)
        with f_cols[0]:
            st.markdown("**Chaser tires**")
            st.write(f"{f.get('chaser_compound') or '—'} | age {f.get('chaser_tyre_age') if f.get('chaser_tyre_age') is not None else '—'} laps")
        with f_cols[1]:
            st.markdown("**Target tires**")
            st.write(f"{f.get('target_compound') or '—'} | age {f.get('target_tyre_age') if f.get('target_tyre_age') is not None else '—'} laps")

        if result.notes:
            with st.expander("Why this verdict", expanded=True):
                for n in result.notes:
                    st.markdown(f"- {n}")

        # Pace + gap trace charts
        chart_cols = st.columns(2)
        with chart_cols[0]:
            st.plotly_chart(
                pace_trace_chart(laps, drivers, chaser_n, target_n),
                use_container_width=True,
            )
        with chart_cols[1]:
            st.plotly_chart(
                gap_evolution_chart(intervals, drivers, chaser_n, target_n),
                use_container_width=True,
            )

        # Closest battles leaderboard
        with st.expander("All adjacent battles on track"):
            pairs = all_strike_pairs(grid, intervals, laps, stints, drivers, total_laps=total_laps, only_close=True)
            if pairs.empty:
                st.info("No catchable pairs at this snapshot.")
            else:
                st.dataframe(
                    pairs.sort_values("Laps to Catch"),
                    hide_index=True,
                    use_container_width=True,
                )


# -- Tire stint Gantt ------------------------------------------------------

st.divider()
st.subheader("Tire strategy")
st.plotly_chart(stint_gantt(stints, drivers), use_container_width=True)


# -- Weather + race control feed ------------------------------------------

st.divider()
wcol, rccol = st.columns([1, 1.4])

with wcol:
    st.subheader("Weather")
    if weather.empty:
        st.info("No weather data.")
    else:
        last = weather.iloc[-1]
        st.metric("Track temp", f"{last['track_temperature']:.1f} °C")
        st.metric("Air temp", f"{last['air_temperature']:.1f} °C")
        st.metric("Humidity", f"{last['humidity']:.0f}%")
        wind = f"{last['wind_speed']:.1f} m/s @ {int(last['wind_direction'])}°"
        st.metric("Wind", wind)
        if last.get("rainfall"):
            st.warning("Rain reported")

with rccol:
    st.subheader("Race control")
    if rc.empty:
        st.info("No race control messages.")
    else:
        for _, m in rc.head(12).iterrows():
            ts = m["date"].strftime("%H:%M:%S") if pd.notna(m["date"]) else "??:??:??"
            flag = m.get("flag") or m.get("category") or "Info"
            icon = {
                "GREEN": "🟢", "YELLOW": "🟡", "DOUBLE YELLOW": "🟡",
                "RED": "🔴", "BLUE": "🔵", "CHEQUERED": "🏁",
                "SafetyCar": "🟠", "Drs": "💨",
            }.get(str(flag).upper() if isinstance(flag, str) else flag, "•")
            st.markdown(f"{icon}  `{ts}`  **{flag}** — {m.get('message') or ''}")


# -- Auto-refresh: handled last so the whole page renders before sleeping. --
if auto_refresh:
    # Visible note so the user knows what's happening; spinner-free to avoid layout shift.
    st.caption(f"Auto-refresh in {interval}s …")
    time.sleep(interval)
    for fn in (get_intervals, get_position, get_laps, get_stints, get_weather, get_race_control):
        fn.clear()
    st.rerun()

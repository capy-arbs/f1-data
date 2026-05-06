"""Live Race — real-time timing, Time-to-Strike predictor, weather and race control.

Pulls live data from OpenF1. When no race is in progress, defaults to the
most recent session so the page is always populated.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st


def _is_live(sess: dict) -> bool:
    """Whether ``sess`` is currently in progress.

    OpenF1 returns ISO-8601 datetimes for date_start / date_end. We compare
    against current UTC. Treat any error or missing field as "not live" so
    the page degrades to its archived-session UX rather than crashing.
    """
    try:
        start = sess.get("date_start")
        end = sess.get("date_end")
        if not start or not end:
            return False
        if isinstance(start, str):
            start = datetime.fromisoformat(start)
        if isinstance(end, str):
            end = datetime.fromisoformat(end)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return start <= now <= end
    except (TypeError, ValueError, AttributeError):
        return False


def _time_since_end(sess: dict) -> str | None:
    """Human-friendly 'ended X ago' string for a finished session."""
    try:
        end = sess.get("date_end")
        if not end:
            return None
        if isinstance(end, str):
            end = datetime.fromisoformat(end)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta: timedelta = datetime.now(timezone.utc) - end
        if delta.total_seconds() < 0:
            return None
        days = delta.days
        hours = delta.seconds // 3600
        if days > 0:
            return f"{days}d ago"
        if hours > 0:
            return f"{hours}h ago"
        mins = delta.seconds // 60
        return f"{mins}m ago"
    except (TypeError, ValueError, AttributeError):
        return None

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


# Data freshness banner — surfaces if the historical DB is lagging behind
# (auto-refresh runs Mon/Wed; manual refresh is in Settings -> Load Data).
def _freshness_banner() -> None:
    from datetime import date
    from db.connection import get_db
    with get_db() as conn:
        latest = conn.execute(
            """
            SELECT ra.season, ra.round, ra.race_name, ra.date
            FROM results res
            JOIN races ra ON res.race_id = ra.race_id
            ORDER BY ra.date DESC
            LIMIT 1
            """
        ).fetchone()
    if not latest:
        return
    try:
        days_old = (date.today() - date.fromisoformat(latest["date"])).days
    except (TypeError, ValueError):
        return
    if days_old > 14:
        st.warning(
            f"Historical data may be stale — latest race in DB: "
            f"**{latest['race_name']}** ({days_old}d ago). "
            "Auto-refresh runs Mon/Wed; trigger manually from Settings → Load Data."
        )

_freshness_banner()


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
    # Live detection: if the session is currently in progress, default the
    # refresh ON and pick a tighter interval so users land on a live race
    # and immediately see updates without having to flip a toggle.
    live_now = _is_live(sess)
    auto_refresh = st.checkbox(
        "Auto-refresh",
        value=live_now,
        help="Re-runs the page on a fixed interval. On by default during a live session.",
    )
    interval = st.select_slider(
        "Interval (s)",
        options=[10, 15, 30, 60],
        value=10 if live_now else 15,
        disabled=not auto_refresh,
    )
    refresh = st.button("Refresh now", use_container_width=True)


session_key = sess["session_key"]
session_label = f"{sess.get('country_name') or sess.get('location', '?')} — {sess.get('session_name', 'Session')} {sess.get('year', '')}"

# Force-clear caches so 'Refresh now' actually fetches fresh data instead of serving from TTL.
if refresh:
    for fn in (get_intervals, get_position, get_laps, get_stints, get_weather, get_race_control):
        fn.clear()


# -- Header strip ----------------------------------------------------------

header_cols = st.columns([3, 1, 1, 1])
# LIVE badge or "ended X ago" subtitle next to the session name.
if live_now:
    header_cols[0].markdown(
        f"### {session_label}  "
        f"<span style='background:#E10600; color:#fff; padding:2px 10px; "
        f"border-radius:3px; font-size:0.65em; letter-spacing:0.1em; "
        f"font-weight:700; vertical-align:middle;'>LIVE</span>",
        unsafe_allow_html=True,
    )
else:
    elapsed = _time_since_end(sess)
    suffix = f" — ended {elapsed}" if elapsed else ""
    header_cols[0].subheader(f"{session_label}{suffix}")

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

# Session bests + per-driver personal bests for sector colouring (S1/S2/S3).
# Computed once from the full laps frame and merged into the standings row.
session_best = {
    "s1": float(laps["duration_sector_1"].min()) if not laps.empty and "duration_sector_1" in laps else None,
    "s2": float(laps["duration_sector_2"].min()) if not laps.empty and "duration_sector_2" in laps else None,
    "s3": float(laps["duration_sector_3"].min()) if not laps.empty and "duration_sector_3" in laps else None,
}

# Most recent lap's sector splits per driver.
if not laps.empty:
    last_lap_per_driver = (
        laps.dropna(subset=["lap_duration"])
        .sort_values(["driver_number", "lap_number"])
        .groupby("driver_number", as_index=False)
        .tail(1)[["driver_number", "duration_sector_1", "duration_sector_2", "duration_sector_3"]]
    )
    pb_per_driver = laps.groupby("driver_number").agg(
        pb_s1=("duration_sector_1", "min"),
        pb_s2=("duration_sector_2", "min"),
        pb_s3=("duration_sector_3", "min"),
    ).reset_index()
else:
    last_lap_per_driver = pd.DataFrame(columns=["driver_number", "duration_sector_1", "duration_sector_2", "duration_sector_3"])
    pb_per_driver = pd.DataFrame(columns=["driver_number", "pb_s1", "pb_s2", "pb_s3"])

st.subheader("Live standings")
standings_event = None  # populated by the dataframe row-select event below
if grid.empty or "position" not in grid.columns:
    st.info("Standings unavailable for this session.")
else:
    show = grid.dropna(subset=["position"]).copy()
    show = show.sort_values("position")
    show = show.merge(last_lap_per_driver, on="driver_number", how="left")
    show = show.merge(pb_per_driver, on="driver_number", how="left")

    show["Pos"] = show["position"].astype("Int64")
    show["Driver"] = show["name_acronym"].fillna(show["full_name"])
    show["Team"] = show["team_name"]
    show["Gap"] = show["gap_to_leader"].apply(
        lambda v: f"+{v:.3f}" if pd.notna(v) else "—"
    )
    show["Interval"] = show["interval"].apply(
        lambda v: f"+{v:.3f}" if pd.notna(v) else "—"
    )
    show["S1"] = show["duration_sector_1"].apply(lambda v: f"{v:.3f}" if pd.notna(v) else "—")
    show["S2"] = show["duration_sector_2"].apply(lambda v: f"{v:.3f}" if pd.notna(v) else "—")
    show["S3"] = show["duration_sector_3"].apply(lambda v: f"{v:.3f}" if pd.notna(v) else "—")
    show["Last Lap"] = show["lap_duration"].apply(
        lambda v: f"{v:.3f}" if pd.notna(v) else "—"
    )
    show["Tire"] = show.apply(
        lambda r: f"{r['compound']} ({int(r['tyre_age'])})" if pd.notna(r.get("compound")) and pd.notna(r.get("tyre_age")) else "—",
        axis=1,
    )

    visible_cols = ["Pos", "Driver", "Team", "Gap", "Interval", "S1", "S2", "S3", "Last Lap", "Tire"]

    # Sector-color styler: purple = session best, green = personal best,
    # default for everything else. Ties broken by rounding to 3dp since
    # OpenF1 returns floats with extra trailing precision.
    def _sector_style(val, sb, pb) -> str:
        if pd.isna(val):
            return ""
        try:
            v = round(float(val), 3)
        except (TypeError, ValueError):
            return ""
        if sb is not None and round(sb, 3) == v:
            return "background-color: rgba(139, 92, 246, 0.45); color: #fff; font-weight: 600"
        if pb is not None and round(pb, 3) == v:
            return "background-color: rgba(34, 197, 94, 0.35); color: #fff; font-weight: 600"
        return ""

    def _row_styles(row) -> list[str]:
        styles: dict[str, str] = {
            "S1": _sector_style(row.get("duration_sector_1"), session_best["s1"], row.get("pb_s1")),
            "S2": _sector_style(row.get("duration_sector_2"), session_best["s2"], row.get("pb_s2")),
            "S3": _sector_style(row.get("duration_sector_3"), session_best["s3"], row.get("pb_s3")),
        }
        return [styles.get(col, "") for col in visible_cols]

    styled = show[visible_cols + ["duration_sector_1", "duration_sector_2", "duration_sector_3",
                                  "pb_s1", "pb_s2", "pb_s3"]].style.apply(
        _row_styles, axis=1, subset=visible_cols
    )

    # selection_mode + on_select="rerun" lets us read a row click and use it
    # to populate the Time-to-Strike pickers below.
    standings_event = st.dataframe(
        styled,
        column_order=visible_cols,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="standings_table",
    )

    st.caption(
        "Click any row to set that driver as the **Chaser** in Time-to-Strike. "
        "Sectors: <span style='color:#8B5CF6;font-weight:700'>purple</span> = session best, "
        "<span style='color:#22c55e;font-weight:700'>green</span> = personal best.",
        unsafe_allow_html=True,
    )

    # -- Recent position changes ------------------------------------------
    # Look at the last 5 minutes of position events and surface gainers /
    # losers. For finished sessions we use the data's own max timestamp as
    # "now" so the window still works against archived data.
    if not positions.empty:
        latest_ts = positions["date"].max()
        cutoff = latest_ts - pd.Timedelta(minutes=5)
        latest_pos = (
            positions.sort_values("date")
            .groupby("driver_number").tail(1)
            .set_index("driver_number")["position"]
        )
        earlier_pos = (
            positions[positions["date"] <= cutoff]
            .sort_values("date")
            .groupby("driver_number").tail(1)
            .set_index("driver_number")["position"]
        )
        common = latest_pos.index.intersection(earlier_pos.index)
        if len(common) > 0:
            deltas = (earlier_pos.loc[common] - latest_pos.loc[common]).rename("delta")
            deltas = deltas[deltas != 0]
            if not deltas.empty:
                # Map driver_number -> acronym for display
                acro_map = drivers.set_index("driver_number")["name_acronym"].to_dict() if not drivers.empty else {}
                gainers = []
                losers = []
                for drv_num, d in deltas.sort_values(ascending=False).items():
                    acro = acro_map.get(drv_num, str(drv_num))
                    old = int(earlier_pos.loc[drv_num])
                    new = int(latest_pos.loc[drv_num])
                    label = f"**{acro}** {'+' if d > 0 else ''}{int(d)} (P{old}→P{new})"
                    (gainers if d > 0 else losers).append(label)
                col_g, col_l = st.columns(2)
                col_g.markdown(f"**Up:** {' · '.join(gainers) if gainers else '—'}")
                col_l.markdown(f"**Down:** {' · '.join(losers) if losers else '—'}")
                st.caption("Position movement over the last 5 minutes")


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
        # Click-to-fill: if the user clicked a row in the standings table
        # above, default the chaser to that driver and the target to whoever
        # is one position ahead. Falls back to P2 chasing P1 otherwise.
        default_chaser_idx = 1 if len(keys) > 1 else 0
        default_target_idx = 0
        clicked_rows = (
            standings_event.selection.rows
            if standings_event is not None and hasattr(standings_event, "selection")
            else []
        )
        if clicked_rows:
            clicked_position = clicked_rows[0] + 1  # row index 0 == P1
            # Map P{n} key prefixes back to keys list indices.
            for i, k in enumerate(keys):
                if k.startswith(f"P{clicked_position}:"):
                    default_chaser_idx = i
                    break
            target_position = max(1, clicked_position - 1)
            for i, k in enumerate(keys):
                if k.startswith(f"P{target_position}:"):
                    default_target_idx = i
                    break

        c1, c2 = st.columns(2)
        chaser_label = c1.selectbox("Chaser", keys, index=default_chaser_idx, key=f"strike_chaser_{default_chaser_idx}")
        target_label = c2.selectbox("Target (driver ahead)", keys, index=default_target_idx, key=f"strike_target_{default_target_idx}")

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

        def _tire_line(prefix: str) -> str:
            comp = f.get(f"{prefix}_compound") or "—"
            age = f.get(f"{prefix}_tyre_age")
            age_s = f"age {age} laps" if age is not None else "age —"
            slope = f.get(f"{prefix}_deg_slope")
            deg_s = f"deg {slope:+.2f}s/lap" if slope is not None else "deg —"
            return f"{comp} | {age_s} | {deg_s}"

        f_cols = st.columns(2)
        with f_cols[0]:
            st.markdown("**Chaser tires**")
            st.write(_tire_line("chaser"))
        with f_cols[1]:
            st.markdown("**Target tires**")
            st.write(_tire_line("target"))

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

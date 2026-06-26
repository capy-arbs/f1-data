"""Live F1 timing data — dual-source router.

Each public function tries F1's direct live-timing REST feed first (via
``data/f1_live_client.py``, which polls the ``livetiming.formula1.com/static``
``.jsonStream`` files used by the official broadcast) and falls back to FastF1
for completed sessions. Routing is automatic in ``_try_live_client`` /
``_has_live_timing``: live or about-to-start sessions in the current year go to
the REST client; everything else loads through FastF1. This replaced an
OpenF1-only path (gated behind a paid tier 2026-05-23) and then a FastF1-only
path (``session.load()`` returns nothing mid-race, swapped 2026-05-24).

**Architecture:** FastF1 (https://github.com/theOehrly/Fast-F1) loads a session
as a single object with attached DataFrames; the live client returns the same
shapes directly from the REST feed. Both reshape to the OpenF1-compatible
contracts so ``pages/14_Live_Race.py``, ``queries/strike.py``, and other
consumers don't need to know which source served a given call:

- ``session_key`` is now a ``"year|gp|identifier"`` string (e.g.
  ``"2026|Monaco|R"``), opaque to callers.
- DataFrame columns match what the old OpenF1 wrappers returned:
  ``driver_number`` (int), ``lap_duration`` (float seconds),
  ``duration_sector_{1,2,3}`` (float seconds), ``is_pit_out_lap`` (bool),
  ``gap_to_leader`` / ``interval`` (float seconds, NaN for lapped cars),
  ``date`` (datetime), ``compound`` / ``tyre_age``, etc.

**Caching:** Every public function is wrapped in ``@st.cache_data`` with a
TTL sized to the data's freshness. FastF1's own disk cache (default
``/tmp/fastf1_cache``, override with ``FASTF1_CACHE`` env var) stores the
per-session blob, so a cache-miss in Streamlit but a hit in FastF1 is
near-instant.

**Live-session behaviour:** FastF1 polls F1's live timing service; during
an active session, ``session.load()`` returns data up to the current lap.
The Streamlit TTLs mean the page refreshes on the same cadence as the old
OpenF1 polling.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC

import fastf1
import fastf1.exceptions
import pandas as pd
import streamlit as st

from data import f1_live_client as _live_client
from data import f1_signalr as _live_signalr

# Quiet FastF1's INFO chatter so Streamlit logs aren't noisy.
fastf1.set_log_level("WARNING")
logging.getLogger("fastf1").setLevel(logging.WARNING)

# Configure FastF1's disk cache once at module load.
_CACHE_DIR = os.environ.get("FASTF1_CACHE", "/tmp/fastf1_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(_CACHE_DIR)


# Module-level last-call state. Same shape as the previous OpenF1
# implementation so existing callers of feed_status() in
# pages/14_Live_Race.py keep working.
_LAST_STATUS: dict = {"code": None, "message": None}

# Outcome of the most recent live-client attempt, separate from _LAST_STATUS
# (which FastF1 overwrites on fallback). Lets the Live Race page show *why* the
# live feed is empty mid-session instead of silently looking broken.
_LIVE_DIAG: dict = {"fn": None, "outcome": None, "detail": None}


def feed_status() -> dict:
    """Outcome of the most recent FastF1 load.

    Returns a dict with:

    - ``code``: ``None`` on success; ``"error"`` for any load failure.
    - ``message``: human-readable detail string for a UI banner.
    """
    return dict(_LAST_STATUS)


def live_diagnostics() -> dict:
    """Why the last live-client attempt did or didn't return data.

    ``outcome`` is one of: ``"not_in_live_window"`` (FastF1 is the expected
    source), ``"no_such_fn"``, ``"exception"``, ``"empty"`` (ran but returned
    no rows — ``detail`` carries the client's own status, e.g. an HTTP 404),
    or ``"ok"``. Reflects the last live-routed fetch in the current render.
    """
    return dict(_LIVE_DIAG)


# -- Live-timing routing ---------------------------------------------------

def _has_live_timing(session_key: str) -> bool:
    """Whether F1's live timing static endpoints might have data.

    Returns True for sessions in the current year that started within the
    last 12 hours or are about to start within 30 minutes.
    """
    from datetime import datetime
    try:
        year, _, _ = _parse_key(session_key)
    except (ValueError, IndexError):
        return False
    if year < datetime.now(UTC).year:
        return False
    df = list_sessions(year)
    if df.empty:
        return False
    match = df[df["session_key"] == session_key]
    if match.empty:
        return False
    now = pd.Timestamp(datetime.now(UTC)).tz_localize(None)
    start = pd.Timestamp(match.iloc[0]["date_start"])
    hours = (now - start).total_seconds() / 3600
    return -0.5 <= hours <= 12


# Approximate session durations (hours) for deciding whether a session is
# actually running *right now*. The SignalR feed always streams the currently
# live session and isn't addressable by key, so we must only record the one
# session whose live window contains "now" — otherwise viewing an already-ended
# earlier session would capture the live session's data and mislabel it.
_LIVE_DURATIONS_H = {"Race": 3.0, "Sprint": 1.5}
_DEFAULT_DURATION_H = 2.0  # practice / qualifying, with buffer


def _is_live_now(session_key: str) -> bool:
    """Whether this exact session is on track at the current wall-clock time."""
    from datetime import datetime
    try:
        year, _, _ = _parse_key(session_key)
    except (ValueError, IndexError):
        return False
    if year != datetime.now(UTC).year:
        return False
    df = list_sessions(year)
    if df.empty:
        return False
    match = df[df["session_key"] == session_key]
    if match.empty:
        return False
    now = pd.Timestamp(datetime.now(UTC)).tz_localize(None)
    start = pd.Timestamp(match.iloc[0]["date_start"])
    name = str(match.iloc[0]["session_name"])
    duration = _LIVE_DURATIONS_H.get(name, _DEFAULT_DURATION_H)
    hours = (now - start).total_seconds() / 3600
    return -0.1 <= hours <= duration


def _try_live_client(fn_name: str, *args, **kwargs) -> pd.DataFrame | None:
    """Try F1's direct live timing API; return ``None`` to fall back to FastF1.

    Records the outcome in ``_LIVE_DIAG`` so the page can explain an empty live
    feed. ``_LAST_STATUS`` is only touched on success — on failure we leave it
    for FastF1's fallback to populate, but the diagnostic preserves the cause.
    """
    log = logging.getLogger(__name__)
    if not args or not _has_live_timing(args[0]):
        _LIVE_DIAG.update(fn=fn_name, outcome="not_in_live_window", detail=None)
        return None
    # While this session is actually on track the static .jsonStream archive
    # doesn't exist yet, so stream it live over the SignalR websocket. Gated on
    # _is_live_now (not the wider 12h static window) because the feed always
    # serves the currently-live session and isn't addressable by key. Idempotent
    # and non-blocking — the recording file fills in over the next few seconds.
    if _is_live_now(args[0]):
        _live_signalr.ensure_recording(args[0])
    fn = getattr(_live_client, fn_name, None)
    if fn is None:
        _LIVE_DIAG.update(fn=fn_name, outcome="no_such_fn", detail=fn_name)
        return None
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        log.warning("Live client %s failed: %s", fn_name, exc, exc_info=True)
        _LIVE_DIAG.update(fn=fn_name, outcome="exception",
                          detail=f"{type(exc).__name__}: {exc}")
        return None
    if result.empty:
        # The SignalR recorder takes a few seconds after connecting to flush its
        # first snapshot. While it's warming up, return the (empty, correctly
        # shaped) live frame instead of falling through to FastF1 — the static
        # archive 404/403s mid-session anyway, and a FastF1 load just burns a
        # rate-limited API call and shows a scary banner. The page renders its
        # "live session detected, data appears shortly" note from this diag.
        if _is_live_now(args[0]) and _live_signalr.is_recording(args[0]):
            _LIVE_DIAG.update(
                fn=fn_name, outcome="live_warming_up",
                detail="SignalR feed connected — data appears within a few seconds",
            )
            _LAST_STATUS.update(code=None, message=None, source="live")
            return result
        detail = _live_client.feed_status().get("message") or "no rows returned"
        log.warning("Live client %s returned empty: %s", fn_name, detail)
        _LIVE_DIAG.update(fn=fn_name, outcome="empty", detail=detail)
        return None
    status = _live_client.feed_status()
    status["source"] = "live"
    _LAST_STATUS.update(**status)
    _LIVE_DIAG.update(fn=fn_name, outcome="ok", detail=None)
    return result


# -- session_key helpers ---------------------------------------------------

def _build_key(year: int, gp: str, identifier: str) -> str:
    return f"{year}|{gp}|{identifier}"


def _parse_key(session_key) -> tuple[int, str, str]:
    parts = str(session_key).split("|")
    return int(parts[0]), parts[1], parts[2]


def _seconds(series_or_value):
    """Timedelta -> float seconds, NaT -> NaN. Works on Series or scalar."""
    if isinstance(series_or_value, pd.Series):
        return series_or_value.dt.total_seconds()
    if series_or_value is pd.NaT or series_or_value is None:
        return float("nan")
    try:
        return series_or_value.total_seconds()
    except AttributeError:
        return float("nan")


def _absolute_lap_time(sess, laps_df) -> pd.Series:
    """Best-effort absolute datetime per lap.

    FastF1's ``LapStartDate`` is the ideal source but isn't always populated
    (varies by session type and year). Falls back to ``session.date + Time``
    (session-start + session-relative cumulative time), and finally to
    ``Time`` itself so downstream sort-by-date logic still works.
    """
    if "LapStartDate" in laps_df.columns:
        lsd = pd.to_datetime(laps_df["LapStartDate"], errors="coerce")
        if lsd.notna().any():
            return lsd
    sess_date = getattr(sess, "date", None)
    if sess_date is not None and pd.notna(sess_date):
        return pd.to_datetime(sess_date) + laps_df["Time"]
    # Last resort: treat session-relative Time as the sort key. Not a true
    # datetime, but pandas sorts timedeltas correctly so groupby+tail(1)
    # still returns the most-recent row per driver.
    return laps_df["Time"]


# -- Session loading -------------------------------------------------------

def _load_session(session_key):
    """Load a FastF1 session and return it, or None on failure.

    Not cached at this layer — FastF1's own disk cache handles repeat loads
    within a process; @st.cache_data on the public functions handles per-
    Streamlit-rerun caching of the derived DataFrames.
    """
    year, gp, ident = _parse_key(session_key)
    try:
        sess = fastf1.get_session(year, gp, ident)
        sess.load(laps=True, telemetry=False, weather=True, messages=True)
        _LAST_STATUS.update(code=None, message=None, source="fastf1")
        return sess
    except Exception as e:
        _LAST_STATUS.update(
            code="error",
            message=f"FastF1 load failed for {session_key}: {e}",
        )
        return None


def _safe_attr(sess, name: str):
    """Access ``sess.<name>`` safely.

    FastF1's ``session.load()`` can succeed without populating every data
    category — common for sessions that ended less than an hour or two ago
    (the live timing pipeline hasn't fully ingested yet). Accessing an
    unloaded attribute raises ``DataNotLoadedError`` mid-render and crashes
    the Live Race page.

    Returns the attribute or ``None`` if it isn't loaded, and records a
    user-friendly message via ``feed_status()`` so the page can banner it.
    """
    if sess is None:
        return None
    try:
        return getattr(sess, name)
    except fastf1.exceptions.DataNotLoadedError:
        _LAST_STATUS.update(
            code="not_loaded",
            message=(
                "FastF1 hasn't fully loaded this session yet — F1's timing "
                "pipeline can take an hour or two to publish complete data "
                "after a session ends. Try again shortly."
            ),
        )
        return None


# -- Sessions list ---------------------------------------------------------

# Standard FastF1 session identifiers mapped to the human names the page UI
# already shows. Order matters — earlier entries are tried first when an
# event has fewer sessions (some old events skip FP3, sprint events differ).
_SESSION_IDENTS = [
    ("FP1", "Practice 1"),
    ("FP2", "Practice 2"),
    ("FP3", "Practice 3"),
    ("SQ", "Sprint Qualifying"),
    ("SS", "Sprint Shootout"),
    ("S", "Sprint"),
    ("Q", "Qualifying"),
    ("R", "Race"),
]


@st.cache_data(ttl=600, show_spinner=False)
def list_sessions(year: int | None = None) -> pd.DataFrame:
    """All sessions for a year (or current year if None), shaped like the
    OpenF1 result the page expects: one row per session with
    ``session_key``, ``session_name``, ``country_name``, ``location``,
    ``year``, ``date_start``, ``date_end``.
    """
    from datetime import datetime
    if year is None:
        year = datetime.now(UTC).year
    try:
        sched = fastf1.get_event_schedule(year, include_testing=False)
        _LAST_STATUS.update(code=None, message=None)
    except Exception as e:
        _LAST_STATUS.update(code="error", message=str(e))
        return pd.DataFrame()

    rows = []
    for _, evt in sched.iterrows():
        for i in range(1, 6):  # Up to 5 sessions per event
            name_col = f"Session{i}"
            date_col = f"Session{i}Date"
            if name_col not in evt or pd.isna(evt[name_col]):
                continue
            short = str(evt[name_col])
            # FastF1's Session{i} returns the short identifier ('FP1', 'Q', 'R', etc.)
            human = dict(_SESSION_IDENTS).get(short, short)
            rows.append({
                "session_key": _build_key(int(evt["EventDate"].year), evt["EventName"], short),
                "session_name": human,
                "country_name": evt.get("Country", ""),
                "location": evt.get("Location", ""),
                "circuit_short_name": evt.get("Location", ""),
                "year": int(evt["EventDate"].year),
                "date_start": evt[date_col],
                # FastF1 doesn't expose explicit end times; the live page uses
                # date_start for "ended X ago" calcs and tolerates a missing
                # end. Provide date_start as a sensible upper bound.
                "date_end": evt[date_col],
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # FastF1's schedule returns timezone-aware datetimes in the local
    # circuit timezone (e.g. +11:00 for Australia). Normalize to naive
    # UTC so downstream comparisons (get_latest_session, _is_live) don't
    # mix tz-aware vs tz-naive and trigger pandas TypeError.
    df["date_start"] = pd.to_datetime(df["date_start"], errors="coerce", utc=True).dt.tz_localize(None)
    df["date_end"] = pd.to_datetime(df["date_end"], errors="coerce", utc=True).dt.tz_localize(None)
    return df.sort_values("date_start", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def get_latest_session() -> dict | None:
    """Most recent session whose date_start is in the past, or the next
    upcoming session if none have started yet.
    """
    from datetime import datetime
    now = pd.Timestamp(datetime.now(UTC)).tz_localize(None)

    # Try current and previous year — early in a season the schedule for
    # the current year may have no completed sessions yet.
    for yr_offset in (0, -1):
        df = list_sessions(datetime.now(UTC).year + yr_offset)
        if df.empty:
            continue
        past = df[df["date_start"] <= now]
        if not past.empty:
            return past.iloc[0].to_dict()
        # No past session — return the next upcoming.
        return df.iloc[-1].to_dict()
    return None


# -- Drivers ---------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def _get_drivers_cached(session_key) -> pd.DataFrame:
    live = _try_live_client("get_drivers", session_key)
    if live is not None:
        return live
    sess = _load_session(session_key)
    res = _safe_attr(sess, "results")
    if res is None or res.empty:
        return pd.DataFrame(
            columns=["driver_number", "name_acronym", "full_name",
                     "team_name", "team_colour"]
        )
    df = pd.DataFrame({
        "driver_number": pd.to_numeric(res["DriverNumber"], errors="coerce").astype("Int64"),
        "name_acronym": res["Abbreviation"].astype(str),
        "full_name": res["FullName"].astype(str) if "FullName" in res.columns else res["BroadcastName"].astype(str),
        "team_name": res["TeamName"].astype(str),
        # FastF1's TeamColor is raw hex ("00D7B6"). Strip any leading "#"
        # defensively in case a future FastF1 version starts prefixing it.
        "team_colour": res["TeamColor"].apply(
            lambda c: str(c).lstrip("#") if isinstance(c, str) else "888888"
        ),
    })
    return df.dropna(subset=["driver_number"]).reset_index(drop=True)


def get_drivers(session_key) -> pd.DataFrame:
    """Driver list with number, acronym, full name, team name, team colour.

    Returns columns: ``driver_number`` (int), ``name_acronym``,
    ``full_name``, ``team_name``, ``team_colour`` (raw 6-char hex with
    no leading ``#``). The no-``#`` shape matches the previous OpenF1
    contract — ``charts/live_charts.py::pace_trace_chart`` does
    ``"#" + team_colour`` on it.

    The driver list is static per session, so the underlying fetch is cached
    for 600s. But during a *live* session it's briefly empty while the SignalR
    recorder warms up (the DriverList snapshot lands a couple seconds after the
    socket connects); without this, that empty would stick for the full 10min
    TTL and the standings grid — which requires this frame — would stay blank
    even as lap/weather data flowed. So drop a warm-up empty and let the next
    rerun refetch.
    """
    df = _get_drivers_cached(session_key)
    if df.empty and _is_live_now(session_key):
        _get_drivers_cached.clear()
    return df


# Preserve the cache-clear API in case a caller (e.g. a manual "Refresh now")
# clears this fetcher like the other cached ones.
get_drivers.clear = _get_drivers_cached.clear


# -- Laps + sectors --------------------------------------------------------

@st.cache_data(ttl=15, show_spinner=False)
def get_laps(session_key, driver_number: int | None = None) -> pd.DataFrame:
    """Lap-by-lap data reshaped to the OpenF1 column contract.

    Columns: ``driver_number`` (int), ``lap_number`` (int), ``lap_duration``
    (float seconds), ``duration_sector_1/2/3`` (float seconds),
    ``is_pit_out_lap`` (bool), ``date_start`` (datetime), ``compound``,
    ``tyre_life``, ``position``.
    """
    live = _try_live_client("get_laps", session_key, driver_number)
    if live is not None:
        return live
    sess = _load_session(session_key)
    laps = _safe_attr(sess, "laps")
    if laps is None or laps.empty:
        return pd.DataFrame(columns=[
            "driver_number", "lap_number", "lap_duration",
            "duration_sector_1", "duration_sector_2", "duration_sector_3",
            "is_pit_out_lap", "date_start", "compound", "tyre_life", "position",
        ])
    if driver_number is not None:
        laps = laps.pick_drivers(str(driver_number))

    out = pd.DataFrame({
        "driver_number": pd.to_numeric(laps["DriverNumber"], errors="coerce").astype("Int64"),
        "lap_number": laps["LapNumber"].astype("Int64"),
        "lap_duration": _seconds(laps["LapTime"]),
        "duration_sector_1": _seconds(laps["Sector1Time"]),
        "duration_sector_2": _seconds(laps["Sector2Time"]),
        "duration_sector_3": _seconds(laps["Sector3Time"]),
        # PitOutTime is non-NaT only on laps where the driver exited the pits.
        "is_pit_out_lap": laps["PitOutTime"].notna(),
        "date_start": _absolute_lap_time(sess, laps),
        "compound": laps["Compound"].astype(str),
        "tyre_life": laps["TyreLife"],
        "position": laps["Position"],
    })
    return out.reset_index(drop=True)


# -- Intervals (derived from laps) ----------------------------------------

@st.cache_data(ttl=10, show_spinner=False)
def get_intervals(session_key) -> pd.DataFrame:
    """Time-series of ``gap_to_leader`` and ``interval`` per driver.

    Derived from per-lap cumulative time since OpenF1's seconds-level
    snapshots don't exist in FastF1. ``date`` is the LapStartDate of each
    lap so downstream sorting works. ``gap_to_leader`` is in seconds;
    ``interval`` is gap to the car classified one position ahead at that
    lap. Lapped cars get NaN.
    """
    live = _try_live_client("get_intervals", session_key)
    if live is not None:
        return live
    sess = _load_session(session_key)
    laps = _safe_attr(sess, "laps")
    if laps is None or laps.empty:
        return pd.DataFrame(columns=["driver_number", "gap_to_leader",
                                       "interval", "date"])

    # Cumulative race time per driver = sum of LapTime across completed laps.
    # We use Time (session-relative timestamp at lap completion) which already
    # encodes the cumulative position.
    df = pd.DataFrame({
        "driver_number": pd.to_numeric(laps["DriverNumber"], errors="coerce").astype("Int64"),
        "lap_number": laps["LapNumber"].astype("Int64"),
        "cum_time_s": _seconds(laps["Time"]),
        "date": _absolute_lap_time(sess, laps),
        "position": laps["Position"],
    }).dropna(subset=["driver_number", "lap_number"])

    if df.empty:
        return pd.DataFrame(columns=["driver_number", "gap_to_leader",
                                       "interval", "date"])

    # Per lap, the leader's cum_time is the min across drivers who completed
    # that lap. gap_to_leader = this_driver_cum - leader_cum.
    leader_per_lap = df.groupby("lap_number")["cum_time_s"].min()
    df["gap_to_leader"] = df["cum_time_s"] - df["lap_number"].map(leader_per_lap)

    # interval = gap to the car classified one position ahead on this lap.
    # Sort by lap then position, take diff in gap_to_leader.
    df = df.sort_values(["lap_number", "position"])
    df["interval"] = df.groupby("lap_number")["gap_to_leader"].diff()

    return df[["driver_number", "gap_to_leader", "interval", "date"]].reset_index(drop=True)


# -- Position snapshots ----------------------------------------------------

@st.cache_data(ttl=10, show_spinner=False)
def get_position(session_key) -> pd.DataFrame:
    """Position snapshots per driver per lap.

    Returns columns: ``driver_number`` (int), ``position`` (int), ``date``.
    One row per (driver, lap) — OpenF1 had finer granularity (per change)
    but lap-level position is what every downstream consumer actually uses.
    """
    live = _try_live_client("get_position", session_key)
    if live is not None:
        return live
    sess = _load_session(session_key)
    laps = _safe_attr(sess, "laps")
    if laps is None or laps.empty:
        return pd.DataFrame(columns=["driver_number", "position", "date"])

    df = pd.DataFrame({
        "driver_number": pd.to_numeric(laps["DriverNumber"], errors="coerce").astype("Int64"),
        "position": laps["Position"],
        "date": _absolute_lap_time(sess, laps),
    }).dropna(subset=["driver_number", "position"])
    df["position"] = df["position"].astype("Int64")
    return df.reset_index(drop=True)


# -- Classification (authoritative running order) -------------------------

def _is_finisher_status(status) -> bool:
    """Whether a FastF1 ``Status`` string means the driver was running at the
    flag. ``"Finished"``, ``"Lapped"``, ``"+1 Lap"`` count; ``"Retired"``,
    ``"Accident"``, ``"Engine"``, ``"Did not start"`` etc. don't.
    """
    s = str(status).lower()
    return s == "finished" or "lap" in s


@st.cache_data(ttl=30, show_spinner=False)
def get_classification(session_key) -> pd.DataFrame:
    """Authoritative running order / final classification per driver.

    ``get_position`` is a lap-by-lap time series: a retired driver's last row
    is frozen at the on-track position they held when they stopped (e.g. a car
    that drops out while running P2 stays "P2" forever). This instead returns
    the *classified* position — retirements sorted to the back — plus a status
    string, so the standings reflect who's actually still in the race.

    Columns: ``driver_number`` (Int64), ``position`` (Int64), ``status`` (str),
    ``retired`` (bool). Empty when no classification exists yet (e.g. a live
    session FastF1 hasn't finished ingesting) — callers fall back to
    ``get_position``.
    """
    live = _try_live_client("get_classification", session_key)
    if live is not None:
        return live
    sess = _load_session(session_key)
    res = _safe_attr(sess, "results")
    if res is None or res.empty:
        return pd.DataFrame(columns=["driver_number", "position", "status", "retired"])
    status = res["Status"].astype(str)
    df = pd.DataFrame({
        "driver_number": pd.to_numeric(res["DriverNumber"], errors="coerce").astype("Int64"),
        "position": pd.to_numeric(res["Position"], errors="coerce").astype("Int64"),
        "status": status,
        "retired": ~status.map(_is_finisher_status),
    })
    return df.dropna(subset=["driver_number"]).reset_index(drop=True)


# -- Stints (derived from laps) -------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def get_stints(session_key) -> pd.DataFrame:
    """Tire stints: one row per (driver, stint).

    Columns: ``driver_number`` (int), ``stint_number`` (int),
    ``compound``, ``lap_start`` (int), ``lap_end`` (int),
    ``tyre_age_at_start`` (int).
    """
    live = _try_live_client("get_stints", session_key)
    if live is not None:
        return live
    sess = _load_session(session_key)
    all_laps = _safe_attr(sess, "laps")
    if all_laps is None or all_laps.empty:
        return pd.DataFrame(columns=[
            "driver_number", "stint_number", "compound",
            "lap_start", "lap_end", "tyre_age_at_start",
        ])
    laps = all_laps[["DriverNumber", "Stint", "Compound", "LapNumber", "TyreLife"]].copy()
    laps = laps.dropna(subset=["DriverNumber", "Stint", "LapNumber"])

    rows = []
    for (drv, stint), grp in laps.groupby(["DriverNumber", "Stint"]):
        grp_sorted = grp.sort_values("LapNumber")
        rows.append({
            "driver_number": int(drv),
            "stint_number": int(stint),
            "compound": grp_sorted["Compound"].iloc[0],
            "lap_start": int(grp_sorted["LapNumber"].iloc[0]),
            "lap_end": int(grp_sorted["LapNumber"].iloc[-1]),
            # TyreLife at stint start = TyreLife on the first lap minus how
            # many laps into this stint that first lap was (0 if the stint
            # started fresh, >0 if a stint started on used tyres).
            "tyre_age_at_start": int(grp_sorted["TyreLife"].iloc[0] - 1)
                                  if pd.notna(grp_sorted["TyreLife"].iloc[0]) else 0,
        })
    return pd.DataFrame(rows)


# -- Pits (derived from laps) ---------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def get_pits(session_key) -> pd.DataFrame:
    """Pit lane events with stop duration.

    Columns: ``driver_number`` (int), ``lap_number`` (int),
    ``pit_duration`` (float seconds, gap between PitInTime and the next
    PitOutTime), ``date``.
    """
    live = _try_live_client("get_pits", session_key)
    if live is not None:
        return live
    sess = _load_session(session_key)
    laps = _safe_attr(sess, "laps")
    if laps is None or laps.empty:
        return pd.DataFrame(columns=["driver_number", "lap_number",
                                       "pit_duration", "date"])
    rows = []
    for drv, grp in laps.groupby("DriverNumber"):
        grp = grp.sort_values("LapNumber")
        for _idx, row in grp.iterrows():
            if pd.notna(row["PitInTime"]):
                # Find this driver's next pit-out time.
                future = grp[(grp["LapNumber"] > row["LapNumber"]) &
                              (grp["PitOutTime"].notna())]
                if not future.empty:
                    pit_out = future.iloc[0]["PitOutTime"]
                    dur = (pit_out - row["PitInTime"]).total_seconds()
                else:
                    dur = float("nan")
                rows.append({
                    "driver_number": int(drv),
                    "lap_number": int(row["LapNumber"]),
                    "pit_duration": dur,
                    "date": pd.to_datetime(row["PitInTime"], errors="coerce"),
                })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


# -- Weather ---------------------------------------------------------------

@st.cache_data(ttl=20, show_spinner=False)
def get_weather(session_key) -> pd.DataFrame:
    """Track + air temp, humidity, wind, rainfall — minute-resolution."""
    live = _try_live_client("get_weather", session_key)
    if live is not None:
        return live
    sess = _load_session(session_key)
    w = _safe_attr(sess, "weather_data")
    if w is None or w.empty:
        return pd.DataFrame(columns=["date", "air_temperature",
                                       "track_temperature", "humidity",
                                       "rainfall", "wind_speed",
                                       "wind_direction"])
    # FastF1's Time is session-relative; combine with the session's start.
    if hasattr(sess, "date") and sess.date is not None:
        abs_date = pd.to_datetime(sess.date) + w["Time"]
    else:
        abs_date = w["Time"]
    df = pd.DataFrame({
        "date": pd.to_datetime(abs_date, errors="coerce"),
        "air_temperature": w["AirTemp"],
        "track_temperature": w["TrackTemp"],
        "humidity": w["Humidity"],
        "rainfall": w["Rainfall"],
        "wind_speed": w["WindSpeed"],
        "wind_direction": w["WindDirection"],
    })
    return df.sort_values("date").reset_index(drop=True)


# -- Race control ----------------------------------------------------------

@st.cache_data(ttl=15, show_spinner=False)
def get_race_control(session_key) -> pd.DataFrame:
    """Race control messages — flags, safety cars, incidents, penalties.

    Columns: ``date``, ``message``, ``flag``, ``category``.
    """
    live = _try_live_client("get_race_control", session_key)
    if live is not None:
        return live
    sess = _load_session(session_key)
    rc = _safe_attr(sess, "race_control_messages")
    if rc is None or rc.empty:
        return pd.DataFrame(columns=["date", "message", "flag", "category"])
    df = pd.DataFrame({
        "date": pd.to_datetime(rc["Time"], errors="coerce"),
        "message": rc["Message"].astype(str),
        "flag": rc["Flag"].astype(str).replace({"None": None, "nan": None}),
        "category": rc["Category"].astype(str),
    })
    return df.sort_values("date", ascending=False).reset_index(drop=True)


# -- Team radio (placeholder — FastF1 doesn't expose this directly) -------

@st.cache_data(ttl=20, show_spinner=False)
def get_team_radio(session_key) -> pd.DataFrame:
    """Team radio. FastF1 doesn't expose this; return empty so callers
    that include radio in their UI just skip the section gracefully.
    """
    return pd.DataFrame(columns=["driver_number", "date", "recording_url"])


# -- Composed views (unchanged from OpenF1 implementation) ----------------

def latest_intervals(intervals_df: pd.DataFrame) -> pd.DataFrame:
    """Reduce the intervals time-series to the most recent row per driver."""
    if intervals_df.empty:
        return intervals_df
    return (
        intervals_df.sort_values("date")
        .groupby("driver_number", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


def latest_positions(position_df: pd.DataFrame) -> pd.DataFrame:
    """Reduce the position time-series to the most recent position per driver."""
    if position_df.empty:
        return position_df
    return (
        position_df.sort_values("date")
        .groupby("driver_number", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


def current_stints(stints_df: pd.DataFrame, laps_df: pd.DataFrame) -> pd.DataFrame:
    """Active tire stint per driver, with current tire age in laps."""
    if stints_df.empty:
        return stints_df
    current_lap = int(laps_df["lap_number"].max()) if not laps_df.empty else 1
    cur = stints_df.sort_values(["driver_number", "stint_number"]).groupby(
        "driver_number", as_index=False
    ).tail(1).copy()
    cur["tyre_age"] = cur["tyre_age_at_start"] + (current_lap - cur["lap_start"]).clip(lower=0)
    cur["current_lap"] = current_lap
    return cur.reset_index(drop=True)


def build_live_grid(
    drivers_df: pd.DataFrame,
    position_df: pd.DataFrame,
    intervals_df: pd.DataFrame,
    laps_df: pd.DataFrame,
    stints_df: pd.DataFrame,
    classification_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One-row-per-driver snapshot of the current race state.

    When ``classification_df`` (from ``get_classification``) is supplied and
    non-empty it's the authoritative source for ``position`` — it puts retired
    drivers at the back instead of leaving them frozen at the on-track position
    they held when they stopped. Falls back to the lap-derived ``position_df``
    when no classification is available (e.g. mid-session before FastF1 has it).
    """
    if drivers_df.empty:
        return pd.DataFrame()

    use_classification = classification_df is not None and not classification_df.empty
    if use_classification:
        pos = classification_df[["driver_number", "position", "status", "retired"]]
    else:
        pos = (
            latest_positions(position_df)[["driver_number", "position"]]
            if not position_df.empty
            else pd.DataFrame(columns=["driver_number", "position"])
        )
    iv = (
        latest_intervals(intervals_df)[["driver_number", "gap_to_leader", "interval"]]
        if not intervals_df.empty
        else pd.DataFrame(columns=["driver_number", "gap_to_leader", "interval"])
    )

    last_lap = pd.DataFrame(columns=["driver_number", "lap_number", "lap_duration"])
    if not laps_df.empty:
        last_lap = (
            laps_df.sort_values(["driver_number", "lap_number"])
            .groupby("driver_number", as_index=False)
            .tail(1)[["driver_number", "lap_number", "lap_duration"]]
        )

    stints = (
        current_stints(stints_df, laps_df)
        if not stints_df.empty
        else pd.DataFrame(columns=["driver_number", "compound", "tyre_age"])
    )

    grid = drivers_df[["driver_number", "name_acronym", "full_name",
                        "team_name", "team_colour"]].copy()
    for piece in (
        pos, iv, last_lap,
        stints[["driver_number", "compound", "tyre_age"]] if not stints.empty else stints,
    ):
        grid = grid.merge(piece, on="driver_number", how="left")

    # A retired driver has no live gap/interval — blank them so the standings
    # don't show a stale "+2.3s" for a car that's been parked for 20 laps.
    if "retired" in grid.columns:
        retired_mask = grid["retired"].fillna(False).astype(bool)
        grid.loc[retired_mask, ["gap_to_leader", "interval"]] = float("nan")

    if "position" in grid.columns:
        grid = grid.sort_values("position", na_position="last").reset_index(drop=True)
    return grid

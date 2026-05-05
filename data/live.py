"""Live F1 timing data via the OpenF1 API.

OpenF1 mirrors the official F1 live timing feed: positions, intervals, sector
times, tire stints, weather, and race control messages. Free tier allows 3
req/s and 30 req/min — every public function is wrapped in ``st.cache_data``
with a TTL appropriate for how fast the underlying data changes.

All functions return pandas DataFrames; an empty frame is used when an endpoint
has no data for the requested session (e.g. between sessions, or for archived
sessions where a feed wasn't recorded).
"""

from __future__ import annotations

import requests
import pandas as pd
import streamlit as st

OPENF1_BASE = "https://api.openf1.org/v1"
TIMEOUT = 15


def _get(endpoint: str, **params) -> list[dict]:
    """Raw GET against OpenF1. Returns [] on transport errors so the UI degrades gracefully."""
    try:
        resp = requests.get(f"{OPENF1_BASE}/{endpoint}", params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return []


# -- Sessions ---------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def list_sessions(year: int | None = None) -> pd.DataFrame:
    """All sessions for a year (or all years if year is None)."""
    params = {"year": year} if year else {}
    rows = _get("sessions", **params)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date_start"] = pd.to_datetime(df["date_start"], errors="coerce")
    df["date_end"] = pd.to_datetime(df["date_end"], errors="coerce")
    return df.sort_values("date_start", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def get_latest_session() -> dict | None:
    """Most recent session that has data — used for the default 'live' view."""
    rows = _get("sessions", session_key="latest")
    if not rows:
        return None
    return rows[0] if isinstance(rows, list) else rows


# -- Drivers ----------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def get_drivers(session_key: int | str) -> pd.DataFrame:
    """Driver list for a session — driver_number, acronym, team, colour."""
    rows = _get("drivers", session_key=session_key)
    return pd.DataFrame(rows)


# -- Live state primitives --------------------------------------------------

@st.cache_data(ttl=10, show_spinner=False)
def get_intervals(session_key: int | str) -> pd.DataFrame:
    """Time-series of gap_to_leader and interval (gap to car ahead).

    During a live race this updates every ~4s. We cache for 10s — enough to
    smooth out the per-rerun call rate without lagging the UI badly.

    ``gap_to_leader`` and ``interval`` are normally floats but the API returns
    strings like "+1 LAP" once a car has been lapped — coerce to numeric so
    arithmetic downstream doesn't choke (lapped values become NaN).
    """
    rows = _get("intervals", session_key=session_key)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("gap_to_leader", "interval"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@st.cache_data(ttl=10, show_spinner=False)
def get_position(session_key: int | str) -> pd.DataFrame:
    """Position snapshots over time (one row per change per driver)."""
    rows = _get("position", session_key=session_key)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


@st.cache_data(ttl=15, show_spinner=False)
def get_laps(session_key: int | str, driver_number: int | None = None) -> pd.DataFrame:
    """Lap-by-lap data: lap_duration, sector splits, speed traps, pit-out flag."""
    params = {"session_key": session_key}
    if driver_number is not None:
        params["driver_number"] = driver_number
    rows = _get("laps", **params)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date_start"] = pd.to_datetime(df["date_start"], errors="coerce")
    return df


@st.cache_data(ttl=30, show_spinner=False)
def get_stints(session_key: int | str) -> pd.DataFrame:
    """Tire stints: compound, lap range, age at start."""
    rows = _get("stints", session_key=session_key)
    return pd.DataFrame(rows)


@st.cache_data(ttl=30, show_spinner=False)
def get_pits(session_key: int | str) -> pd.DataFrame:
    """Pit lane events with stop duration."""
    rows = _get("pit", session_key=session_key)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


@st.cache_data(ttl=20, show_spinner=False)
def get_weather(session_key: int | str) -> pd.DataFrame:
    """Track + air temp, humidity, wind, rainfall — one row per minute."""
    rows = _get("weather", session_key=session_key)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=15, show_spinner=False)
def get_race_control(session_key: int | str) -> pd.DataFrame:
    """Race control messages — flags, safety cars, incidents, penalties."""
    rows = _get("race_control", session_key=session_key)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=20, show_spinner=False)
def get_team_radio(session_key: int | str) -> pd.DataFrame:
    """Team radio clips with audio URLs."""
    rows = _get("team_radio", session_key=session_key)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.sort_values("date", ascending=False).reset_index(drop=True)


# -- Composed views ---------------------------------------------------------

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
) -> pd.DataFrame:
    """One-row-per-driver snapshot of the current race state."""
    if drivers_df.empty:
        return pd.DataFrame()

    pos = latest_positions(position_df)[["driver_number", "position"]] if not position_df.empty else pd.DataFrame(columns=["driver_number", "position"])
    iv = latest_intervals(intervals_df)[["driver_number", "gap_to_leader", "interval"]] if not intervals_df.empty else pd.DataFrame(columns=["driver_number", "gap_to_leader", "interval"])

    last_lap = pd.DataFrame(columns=["driver_number", "lap_number", "lap_duration"])
    if not laps_df.empty:
        last_lap = (
            laps_df.sort_values(["driver_number", "lap_number"])
            .groupby("driver_number", as_index=False)
            .tail(1)[["driver_number", "lap_number", "lap_duration"]]
        )

    stints = current_stints(stints_df, laps_df) if not stints_df.empty else pd.DataFrame(columns=["driver_number", "compound", "tyre_age"])

    grid = drivers_df[["driver_number", "name_acronym", "full_name", "team_name", "team_colour"]].copy()
    for piece in (pos, iv, last_lap, stints[["driver_number", "compound", "tyre_age"]] if not stints.empty else stints):
        grid = grid.merge(piece, on="driver_number", how="left")

    if "position" in grid.columns:
        grid = grid.sort_values("position", na_position="last").reset_index(drop=True)
    return grid

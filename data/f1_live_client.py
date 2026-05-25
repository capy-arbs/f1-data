"""Direct F1 live timing REST client.

Polls F1's static timing endpoints (livetiming.formula1.com/static/...) for
real-time data during active sessions.  Used as the primary data source when
FastF1's ``session.load()`` can't return data — i.e. during live races.

The static endpoints serve ``.jsonStream`` files: cumulative logs where each
line is a relative timestamp plus a JSON delta-update.  We replay all updates
to build the current state, then reshape into the DataFrame contracts that
``data/live.py`` consumers expect so pages don't need changes.
"""

from __future__ import annotations

import json
import logging
import re
import time as _time

import fastf1
import pandas as pd
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://livetiming.formula1.com"
_TIMEOUT = 10

_SHORT_TO_FULL = {
    "FP1": "Practice 1",
    "FP2": "Practice 2",
    "FP3": "Practice 3",
    "SQ": "Sprint Qualifying",
    "SS": "Sprint Shootout",
    "S": "Sprint",
    "Q": "Qualifying",
    "R": "Race",
}

_LAST_STATUS: dict = {"code": None, "message": None}
_SESSION_INFO_CACHE: dict[str, tuple[str | None, pd.Timestamp | None]] = {}
_STREAM_CACHE: dict[str, tuple[float, list]] = {}
_STREAM_CACHE_TTL = 5  # seconds — deduplicates within a single page render
_TS_SPLIT = re.compile(r"[:.]+")


def feed_status() -> dict:
    return dict(_LAST_STATUS)


# -- Path + HTTP infrastructure -------------------------------------------

def _get_session_info(session_key: str) -> tuple[str | None, pd.Timestamp | None]:
    """Return ``(url_path, session_start_utc)`` for a session key.

    Cached in module-level dict since session info doesn't change.
    """
    if session_key in _SESSION_INFO_CACHE:
        return _SESSION_INFO_CACHE[session_key]

    parts = str(session_key).split("|")
    if len(parts) != 3:
        _SESSION_INFO_CACHE[session_key] = (None, None)
        return None, None
    year, gp_name, ident = int(parts[0]), parts[1], parts[2]

    # ident may be a full name ("Race") or short identifier ("R").
    # Normalise to the full name for path construction.
    sname = _SHORT_TO_FULL.get(ident, ident)

    try:
        sched = fastf1.get_event_schedule(year, include_testing=False)
    except Exception:
        return None, None  # don't cache transient failures

    evt = sched[sched["EventName"] == gp_name]
    if evt.empty:
        _SESSION_INFO_CACHE[session_key] = (None, None)
        return None, None
    evt = evt.iloc[0]

    event_date = pd.Timestamp(evt["EventDate"]).strftime("%Y-%m-%d")

    session_date = None
    session_start = None
    for i in range(1, 6):
        col = f"Session{i}"
        dcol = f"Session{i}Date"
        if col not in evt.index or pd.isna(evt[col]):
            continue
        # Schedule uses full names; normalise both sides to compare.
        sched_full = _SHORT_TO_FULL.get(str(evt[col]), str(evt[col]))
        if sched_full == sname:
            raw_ts = pd.Timestamp(evt[dcol])
            session_date = raw_ts.strftime("%Y-%m-%d")
            if raw_ts.tzinfo is not None:
                session_start = raw_ts.tz_convert("UTC").tz_localize(None)
            else:
                session_start = raw_ts
            break

    if session_date is None:
        _SESSION_INFO_CACHE[session_key] = (None, None)
        return None, None

    path = f"/static/{year}/{event_date}_{gp_name}/{session_date}_{sname}/"
    path = path.replace(" ", "_")
    _SESSION_INFO_CACHE[session_key] = (path, session_start)
    return path, session_start


def _fetch_stream_raw(session_key: str, topic: str) -> list[tuple[str, dict]]:
    """Fetch a ``.jsonStream`` file and parse into ``(timestamp, data)`` pairs."""
    path, _ = _get_session_info(session_key)
    if path is None:
        _LAST_STATUS.update(code="error", message="Could not resolve session path")
        return []

    url = f"{BASE_URL}{path}{topic}"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        _LAST_STATUS.update(code="error", message=f"F1 live timing: {e}")
        return []

    _LAST_STATUS.update(code=None, message=None)
    entries: list[tuple[str, dict]] = []
    for raw_line in resp.text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        brace = line.find("{")
        bracket = line.find("[")
        candidates = [x for x in (brace, bracket) if x >= 0]
        if not candidates:
            continue
        split_at = min(candidates)
        ts = line[:split_at]
        try:
            data = json.loads(line[split_at:])
        except json.JSONDecodeError:
            continue
        entries.append((ts, data))
    return entries


def _fetch_stream(session_key: str, topic: str) -> list[tuple[str, dict]]:
    """Cached wrapper — deduplicates fetches within ``_STREAM_CACHE_TTL``."""
    key = f"{session_key}|{topic}"
    now = _time.monotonic()
    cached = _STREAM_CACHE.get(key)
    if cached is not None:
        ts, data = cached
        if now - ts < _STREAM_CACHE_TTL:
            return data
    result = _fetch_stream_raw(session_key, topic)
    _STREAM_CACHE[key] = (now, result)
    return result


# -- State helpers --------------------------------------------------------

def _deep_merge(base: dict, update) -> dict:
    if not isinstance(update, dict):
        return base
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _build_state(entries: list[tuple[str, dict]]) -> dict:
    state: dict = {}
    for _, data in entries:
        _deep_merge(state, data)
    return state


# -- Value parsers --------------------------------------------------------

def _parse_ts(ts_str: str, session_start: pd.Timestamp | None) -> pd.Timestamp:
    if not ts_str:
        return pd.NaT
    try:
        parts = _TS_SPLIT.split(ts_str.strip())
        h = int(parts[0]) if len(parts) > 0 else 0
        m = int(parts[1]) if len(parts) > 1 else 0
        s = int(parts[2]) if len(parts) > 2 else 0
        ms = int(parts[3]) if len(parts) > 3 else 0
        delta = pd.Timedelta(hours=h, minutes=m, seconds=s, milliseconds=ms)
        if session_start is not None:
            return session_start + delta
        return pd.Timestamp("2000-01-01") + delta
    except (ValueError, IndexError):
        return pd.NaT


def _parse_lap_time(value) -> float | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if ":" in s:
            parts = s.split(":")
            return float(parts[0]) * 60 + float(parts[1])
        return float(s)
    except (ValueError, IndexError):
        return None


def _parse_gap(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    upper = s.upper()
    if "LAP" in upper or upper.endswith("L"):
        return float("nan")
    s = s.lstrip("+")
    try:
        return float(s)
    except ValueError:
        return None


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


# -- Public data functions (matching data/live.py contracts) ---------------

def get_drivers(session_key) -> pd.DataFrame:
    entries = _fetch_stream(session_key, "DriverList.jsonStream")
    empty = pd.DataFrame(columns=["driver_number", "name_acronym", "full_name",
                                   "team_name", "team_colour"])
    if not entries:
        return empty

    state = _build_state(entries)
    rows = []
    for num, info in state.items():
        if not isinstance(info, dict):
            continue
        dn = _safe_int(info.get("RacingNumber", num))
        if dn is None:
            continue
        rows.append({
            "driver_number": dn,
            "name_acronym": info.get("Tla", ""),
            "full_name": info.get("FullName", info.get("BroadcastName", "")),
            "team_name": info.get("TeamName", ""),
            "team_colour": str(info.get("TeamColour", "888888")).lstrip("#"),
        })
    return pd.DataFrame(rows) if rows else empty


def get_laps(session_key, driver_number: int | None = None) -> pd.DataFrame:
    cols = [
        "driver_number", "lap_number", "lap_duration",
        "duration_sector_1", "duration_sector_2", "duration_sector_3",
        "is_pit_out_lap", "date_start", "compound", "tyre_life", "position",
    ]
    empty = pd.DataFrame(columns=cols)

    timing = _fetch_stream(session_key, "TimingData.jsonStream")
    if not timing:
        return empty

    _, session_start = _get_session_info(session_key)
    timing_app = _fetch_stream(session_key, "TimingAppData.jsonStream")

    # Build cumulative stint state per driver from TimingAppData.
    stint_state: dict[str, dict] = {}
    for _, data in timing_app:
        for drv, updates in (data.get("Lines") or {}).items():
            stints = updates.get("Stints")
            if stints and isinstance(stints, dict):
                _deep_merge(stint_state.setdefault(drv, {}), stints)

    def _tire_at_lap(drv: str, lap: int) -> tuple[str | None, int | None]:
        stints = stint_state.get(drv, {})
        if not stints:
            return None, None
        for _, sd in sorted(stints.items(), key=lambda x: int(x[0]), reverse=True):
            if not isinstance(sd, dict):
                continue
            start = _safe_int(sd.get("LapNumber")) or 0
            if lap >= start:
                age_base = _safe_int(sd.get("StartLaps")) or 0
                return sd.get("Compound"), age_base + (lap - start) + 1
        return None, None

    drv_state: dict[str, dict] = {}
    laps: list[dict] = []

    for ts, data in timing:
        for drv, updates in (data.get("Lines") or {}).items():
            if drv not in drv_state:
                drv_state[drv] = {"_n": 0, "_pit_out": False}
            st = drv_state[drv]
            old_n = st["_n"]

            if updates.get("PitOut") in (True, "true", "True"):
                st["_pit_out"] = True

            _deep_merge(st, updates)
            new_n = _safe_int(st.get("NumberOfLaps"))
            if new_n is None:
                continue
            st["_n"] = new_n

            if new_n > old_n >= 0:
                sectors = st.get("Sectors", {})
                comp, tlife = _tire_at_lap(drv, new_n)
                laps.append({
                    "driver_number": int(drv),
                    "lap_number": new_n,
                    "lap_duration": _parse_lap_time(
                        (st.get("LastLapTime") or {}).get("Value")),
                    "duration_sector_1": _parse_lap_time(
                        (sectors.get("0") or {}).get("Value")),
                    "duration_sector_2": _parse_lap_time(
                        (sectors.get("1") or {}).get("Value")),
                    "duration_sector_3": _parse_lap_time(
                        (sectors.get("2") or {}).get("Value")),
                    "is_pit_out_lap": st.get("_pit_out", False),
                    "date_start": _parse_ts(ts, session_start),
                    "compound": comp,
                    "tyre_life": tlife,
                    "position": _safe_int(st.get("Position")),
                })
                st["_pit_out"] = False

    if not laps:
        return empty
    df = pd.DataFrame(laps)
    if driver_number is not None:
        df = df[df["driver_number"] == driver_number]
    return df[cols].reset_index(drop=True)


def get_intervals(session_key) -> pd.DataFrame:
    timing = _fetch_stream(session_key, "TimingData.jsonStream")
    empty = pd.DataFrame(columns=["driver_number", "gap_to_leader", "interval", "date"])
    if not timing:
        return empty

    _, session_start = _get_session_info(session_key)
    drv_state: dict[str, dict] = {}
    rows: list[dict] = []

    for ts, data in timing:
        for drv, updates in (data.get("Lines") or {}).items():
            if drv not in drv_state:
                drv_state[drv] = {}
            _deep_merge(drv_state[drv], updates)
            st = drv_state[drv]

            gap = _parse_gap(st.get("GapToLeader"))
            iv = _parse_gap((st.get("IntervalToPositionAhead") or {}).get("Value"))

            if gap is None and _safe_int(st.get("Position")) == 1:
                gap = 0.0

            if gap is not None or iv is not None:
                rows.append({
                    "driver_number": int(drv),
                    "gap_to_leader": gap if gap is not None else float("nan"),
                    "interval": iv if iv is not None else float("nan"),
                    "date": _parse_ts(ts, session_start),
                })

    return pd.DataFrame(rows) if rows else empty


def get_position(session_key) -> pd.DataFrame:
    timing = _fetch_stream(session_key, "TimingData.jsonStream")
    empty = pd.DataFrame(columns=["driver_number", "position", "date"])
    if not timing:
        return empty

    _, session_start = _get_session_info(session_key)
    rows: list[dict] = []

    for ts, data in timing:
        for drv, updates in (data.get("Lines") or {}).items():
            pos = _safe_int(updates.get("Position"))
            if pos is not None:
                rows.append({
                    "driver_number": int(drv),
                    "position": pos,
                    "date": _parse_ts(ts, session_start),
                })

    if not rows:
        return empty
    df = pd.DataFrame(rows)
    df["position"] = df["position"].astype("Int64")
    return df


def get_stints(session_key) -> pd.DataFrame:
    cols = ["driver_number", "stint_number", "compound",
            "lap_start", "lap_end", "tyre_age_at_start"]
    empty = pd.DataFrame(columns=cols)

    timing_app = _fetch_stream(session_key, "TimingAppData.jsonStream")
    if not timing_app:
        return empty

    drv_stints: dict[str, dict] = {}
    for _, data in timing_app:
        for drv, updates in (data.get("Lines") or {}).items():
            stints = updates.get("Stints")
            if stints and isinstance(stints, dict):
                _deep_merge(drv_stints.setdefault(drv, {}), stints)

    if not drv_stints:
        return empty

    timing = _fetch_stream(session_key, "TimingData.jsonStream")
    cur_laps: dict[str, int] = {}
    for _, data in timing:
        for drv, updates in (data.get("Lines") or {}).items():
            nl = _safe_int(updates.get("NumberOfLaps"))
            if nl is not None:
                cur_laps[drv] = nl

    rows: list[dict] = []
    for drv, stints in drv_stints.items():
        sorted_s = sorted(stints.items(), key=lambda x: int(x[0]))
        for idx, (snum, sd) in enumerate(sorted_s):
            if not isinstance(sd, dict):
                continue
            lap_start = _safe_int(sd.get("LapNumber")) or 1
            start_laps = _safe_int(sd.get("StartLaps")) or 0
            if idx + 1 < len(sorted_s):
                next_start = _safe_int(sorted_s[idx + 1][1].get("LapNumber")) or lap_start
                lap_end = max(lap_start, next_start - 1)
            else:
                lap_end = cur_laps.get(drv, lap_start)
            rows.append({
                "driver_number": int(drv),
                "stint_number": int(snum) + 1,
                "compound": sd.get("Compound", "UNKNOWN"),
                "lap_start": lap_start,
                "lap_end": lap_end,
                "tyre_age_at_start": start_laps,
            })

    return pd.DataFrame(rows) if rows else empty


def get_pits(session_key) -> pd.DataFrame:
    stints_df = get_stints(session_key)
    empty = pd.DataFrame(columns=["driver_number", "lap_number", "pit_duration", "date"])
    if stints_df.empty:
        return empty

    rows: list[dict] = []
    for drv, grp in stints_df.groupby("driver_number"):
        grp = grp.sort_values("stint_number")
        for i in range(1, len(grp)):
            rows.append({
                "driver_number": int(drv),
                "lap_number": int(grp.iloc[i - 1]["lap_end"]),
                "pit_duration": float("nan"),
                "date": pd.NaT,
            })
    return pd.DataFrame(rows) if rows else empty


def get_weather(session_key) -> pd.DataFrame:
    entries = _fetch_stream(session_key, "WeatherData.jsonStream")
    empty = pd.DataFrame(columns=["date", "air_temperature", "track_temperature",
                                   "humidity", "rainfall", "wind_speed", "wind_direction"])
    if not entries:
        return empty

    _, session_start = _get_session_info(session_key)
    rows: list[dict] = []
    for ts, data in entries:
        if not isinstance(data, dict):
            continue
        try:
            rainfall = bool(int(float(data.get("Rainfall", "0") or "0")))
        except (ValueError, TypeError):
            rainfall = False
        rows.append({
            "date": _parse_ts(ts, session_start),
            "air_temperature": _safe_float(data.get("AirTemp")),
            "track_temperature": _safe_float(data.get("TrackTemp")),
            "humidity": _safe_float(data.get("Humidity")),
            "rainfall": rainfall,
            "wind_speed": _safe_float(data.get("WindSpeed")),
            "wind_direction": _safe_float(data.get("WindDirection")),
        })

    if not rows:
        return empty
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def get_race_control(session_key) -> pd.DataFrame:
    entries = _fetch_stream(session_key, "RaceControlMessages.jsonStream")
    empty = pd.DataFrame(columns=["date", "message", "flag", "category"])
    if not entries:
        return empty

    all_msgs: list[dict] = []
    for _, data in entries:
        msgs = data.get("Messages", {})
        if isinstance(msgs, dict):
            for _, msg in sorted(msgs.items(),
                                 key=lambda x: int(x[0]) if x[0].isdigit() else 0):
                if isinstance(msg, dict):
                    all_msgs.append(msg)
        elif isinstance(msgs, list):
            all_msgs.extend(m for m in msgs if isinstance(m, dict))

    rows: list[dict] = []
    for msg in all_msgs:
        flag = msg.get("Flag")
        if flag in (None, "None", "nan", ""):
            flag = None
        rows.append({
            "date": pd.to_datetime(msg.get("Utc"), errors="coerce"),
            "message": msg.get("Message", ""),
            "flag": flag,
            "category": msg.get("Category", ""),
        })

    if not rows:
        return empty
    return pd.DataFrame(rows).sort_values("date", ascending=False).reset_index(drop=True)

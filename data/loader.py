"""Orchestration: fetch from API, transform, insert into SQLite."""

import sys
import time
from datetime import datetime

from db.connection import get_db
from data.fetcher import (
    fetch_seasons,
    fetch_races,
    fetch_results,
    fetch_qualifying,
    fetch_sprint_results,
    fetch_pit_stops,
    fetch_driver_standings_for_round,
    fetch_constructor_standings_for_round,
)
from config import API_RATE_LIMIT_DELAY


def _already_fetched(conn, endpoint: str, season: int, round_num: int = 0) -> bool:
    """Check if we already have data for this endpoint/season/round."""
    row = conn.execute(
        "SELECT fetched_at FROM fetch_log WHERE endpoint=? AND season=? AND round=?",
        (endpoint, season, round_num),
    ).fetchone()
    if row is None:
        return False
    # For current year, re-fetch if older than 24 hours
    if season == datetime.now().year:
        from datetime import timedelta
        fetched = datetime.fromisoformat(row["fetched_at"])
        if datetime.now() - fetched > timedelta(hours=24):
            return False
    return True


def _log_fetch(conn, endpoint: str, season: int, round_num: int, count: int):
    conn.execute(
        "INSERT OR REPLACE INTO fetch_log (endpoint, season, round, fetched_at, record_count) "
        "VALUES (?, ?, ?, datetime('now'), ?)",
        (endpoint, season, round_num, count),
    )


def _upsert_driver(conn, d: dict):
    conn.execute(
        "INSERT OR IGNORE INTO drivers (driver_id, number, code, given_name, family_name, "
        "date_of_birth, nationality, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            d["driverId"],
            int(d.get("permanentNumber", 0)) or None,
            d.get("code"),
            d["givenName"],
            d["familyName"],
            d.get("dateOfBirth"),
            d.get("nationality"),
            d.get("url"),
        ),
    )


def _upsert_constructor(conn, c: dict):
    conn.execute(
        "INSERT OR IGNORE INTO constructors (constructor_id, name, nationality, url) "
        "VALUES (?, ?, ?, ?)",
        (c["constructorId"], c["name"], c.get("nationality"), c.get("url")),
    )


def _upsert_circuit(conn, c: dict):
    loc = c.get("Location", {})
    conn.execute(
        "INSERT OR IGNORE INTO circuits (circuit_id, name, locality, country, lat, lng, url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            c["circuitId"],
            c["circuitName"],
            loc.get("locality"),
            loc.get("country"),
            float(loc["lat"]) if loc.get("lat") not in (None, "") else None,
            float(loc["long"]) if loc.get("long") not in (None, "") else None,
            c.get("url"),
        ),
    )


def _get_race_id(conn, season: int, round_num: int) -> int | None:
    row = conn.execute(
        "SELECT race_id FROM races WHERE season=? AND round=?",
        (season, round_num),
    ).fetchone()
    return row["race_id"] if row else None


def load_seasons(conn):
    """Load the seasons list."""
    seasons = fetch_seasons()
    for s in seasons:
        conn.execute(
            "INSERT OR IGNORE INTO seasons (year, url) VALUES (?, ?)",
            (int(s["season"]), s.get("url")),
        )
    conn.commit()
    return len(seasons)


def load_races(conn, year: int):
    """Load all races for a season, including circuit data."""
    if _already_fetched(conn, "races", year):
        return
    races = fetch_races(year)
    for r in races:
        _upsert_circuit(conn, r["Circuit"])
        conn.execute(
            "INSERT OR IGNORE INTO races (season, round, race_name, circuit_id, date, time) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                int(r["season"]),
                int(r["round"]),
                r["raceName"],
                r["Circuit"]["circuitId"],
                r["date"],
                r.get("time"),
            ),
        )
    _log_fetch(conn, "races", year, 0, len(races))
    conn.commit()
    time.sleep(API_RATE_LIMIT_DELAY)


def load_results(conn, year: int):
    """Load race results for a season."""
    if _already_fetched(conn, "results", year):
        return
    results = fetch_results(year)
    for r in results:
        race_id = _get_race_id(conn, int(r["season"]), int(r["round"]))
        if not race_id:
            continue
        for res in r.get("Results", []):
            _upsert_driver(conn, res["Driver"])
            _upsert_constructor(conn, res["Constructor"])
            fl = res.get("FastestLap", {})
            pos = res.get("position")
            conn.execute(
                "INSERT OR IGNORE INTO results "
                "(race_id, driver_id, constructor_id, grid, position, position_text, "
                "points, laps, status, time_millis, time_text, "
                "fastest_lap_rank, fastest_lap_time, fastest_lap_speed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    race_id,
                    res["Driver"]["driverId"],
                    res["Constructor"]["constructorId"],
                    int(res.get("grid", 0)),
                    int(pos) if pos and pos.isdigit() else None,
                    res.get("positionText"),
                    float(res.get("points", 0)),
                    int(res.get("laps", 0)),
                    res.get("status"),
                    int(res["Time"]["millis"]) if "Time" in res else None,
                    res["Time"]["time"] if "Time" in res else None,
                    int(fl["rank"]) if fl.get("rank") else None,
                    fl.get("Time", {}).get("time"),
                    float(fl.get("AverageSpeed", {}).get("speed", 0)) or None,
                ),
            )
    _log_fetch(conn, "results", year, 0, len(results))
    conn.commit()
    time.sleep(API_RATE_LIMIT_DELAY)


def load_qualifying(conn, year: int):
    """Load qualifying results for a season."""
    if _already_fetched(conn, "qualifying", year):
        return
    try:
        quals = fetch_qualifying(year)
    except Exception as e:
        # Don't mark as fetched — a transient API/network failure used to
        # silently hide qualifying data forever (past seasons have no TTL).
        # Let the next refresh retry. Jolpica returns an empty list rather
        # than raising when a season genuinely has no qualifying data, so
        # an exception here is a real failure to surface.
        print(f"WARN: load_qualifying({year}) failed: {e}", file=sys.stderr)
        return
    for q in quals:
        race_id = _get_race_id(conn, int(q["season"]), int(q["round"]))
        if not race_id:
            continue
        for qr in q.get("QualifyingResults", []):
            _upsert_driver(conn, qr["Driver"])
            _upsert_constructor(conn, qr["Constructor"])
            conn.execute(
                "INSERT OR IGNORE INTO qualifying "
                "(race_id, driver_id, constructor_id, position, q1, q2, q3) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    race_id,
                    qr["Driver"]["driverId"],
                    qr["Constructor"]["constructorId"],
                    int(qr.get("position", 0)),
                    qr.get("Q1"),
                    qr.get("Q2"),
                    qr.get("Q3"),
                ),
            )
    _log_fetch(conn, "qualifying", year, 0, len(quals))
    conn.commit()
    time.sleep(API_RATE_LIMIT_DELAY)


def load_sprint_results(conn, year: int):
    """Load sprint race results for a season (available from 2021+)."""
    if _already_fetched(conn, "sprint_results", year):
        return
    if year < 2021:
        _log_fetch(conn, "sprint_results", year, 0, 0)
        conn.commit()
        return
    try:
        sprints = fetch_sprint_results(year)
    except Exception as e:
        # Same reasoning as load_qualifying — don't permanently hide a
        # season's sprint data behind a transient failure. The year<2021
        # check above already handles the legitimate "no sprint data" case.
        print(f"WARN: load_sprint_results({year}) failed: {e}", file=sys.stderr)
        return
    count = 0
    for s in sprints:
        race_id = _get_race_id(conn, int(s["season"]), int(s["round"]))
        if not race_id:
            continue
        for res in s.get("SprintResults", []):
            _upsert_driver(conn, res["Driver"])
            _upsert_constructor(conn, res["Constructor"])
            pos = res.get("position")
            conn.execute(
                "INSERT OR IGNORE INTO sprint_results "
                "(race_id, driver_id, constructor_id, grid, position, position_text, "
                "points, laps, status, time_text) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    race_id,
                    res["Driver"]["driverId"],
                    res["Constructor"]["constructorId"],
                    int(res.get("grid", 0)),
                    int(pos) if pos and str(pos).isdigit() else None,
                    res.get("positionText"),
                    float(res.get("points", 0)),
                    int(res.get("laps", 0)),
                    res.get("status"),
                    res.get("Time", {}).get("time") if "Time" in res else None,
                ),
            )
            count += 1
    _log_fetch(conn, "sprint_results", year, 0, count)
    conn.commit()
    time.sleep(API_RATE_LIMIT_DELAY)


def _parse_pit_duration(text) -> float | None:
    """Convert a pit-stop duration string into seconds.

    Handles both the normal seconds form ("22.630") and the M:SS.mmm form
    ("18:01.553") that Jolpica returns when a "stop" was actually a long
    repair or red-flag-induced pit-lane wait. Returns None when the input is
    blank or unparseable.
    """
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None
    if ":" in text:
        try:
            mins, rest = text.split(":", 1)
            return int(mins) * 60 + float(rest)
        except (ValueError, AttributeError):
            return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def load_pit_stops_for_race(conn, year: int, round_num: int):
    """Lazy-load pit stops for a specific race."""
    if _already_fetched(conn, "pitstops", year, round_num):
        return
    race_id = _get_race_id(conn, year, round_num)
    if not race_id:
        return
    try:
        stops = fetch_pit_stops(year, round_num)
    except Exception as e:
        # Don't mark as fetched on real failures — pit stops pre-2011 just
        # return empty (not exception), so an exception here means the API
        # call itself failed and should retry next time.
        print(f"WARN: load_pit_stops_for_race({year}/{round_num}) failed: {e}", file=sys.stderr)
        return
    for s in stops:
        for ps in s.get("PitStops", []) if isinstance(s, dict) and "PitStops" in s else [s]:
            dur = ps.get("duration", "0")
            dur_ms = _parse_pit_duration(dur)
            conn.execute(
                "INSERT OR IGNORE INTO pit_stops "
                "(race_id, driver_id, stop_number, lap, time_of_day, duration, duration_s) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    race_id,
                    ps["driverId"],
                    int(ps["stop"]),
                    int(ps.get("lap", 0)),
                    ps.get("time"),
                    dur,
                    dur_ms,
                ),
            )
    _log_fetch(conn, "pitstops", year, round_num, len(stops))
    conn.commit()


def _get_round_count(conn, year: int) -> int:
    """Get the number of rounds in a season from loaded race data."""
    row = conn.execute(
        "SELECT MAX(round) as max_round FROM races WHERE season=?", (year,)
    ).fetchone()
    return row["max_round"] if row and row["max_round"] else 0


def load_driver_standings(conn, year: int):
    """Load driver standings for every round of a season."""
    if _already_fetched(conn, "driver_standings", year):
        return
    total_rounds = _get_round_count(conn, year)
    if total_rounds == 0:
        return
    count = 0
    failed_rounds = 0
    for round_num in range(1, total_rounds + 1):
        try:
            standings_lists = fetch_driver_standings_for_round(year, round_num)
        except Exception as e:
            failed_rounds += 1
            print(
                f"WARN: load_driver_standings({year}/{round_num}) failed: {e}",
                file=sys.stderr,
            )
            continue
        for sl in standings_lists:
            for ds in sl.get("DriverStandings", []):
                _upsert_driver(conn, ds["Driver"])
                constrs = ds.get("Constructors", [])
                cid = None
                if constrs:
                    _upsert_constructor(conn, constrs[0])
                    cid = constrs[0]["constructorId"]
                pos = ds.get("position")
                if pos is None:
                    continue  # Driver didn't participate this round
                conn.execute(
                    "INSERT OR IGNORE INTO driver_standings "
                    "(season, round, driver_id, constructor_id, position, points, wins) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        year,
                        round_num,
                        ds["Driver"]["driverId"],
                        cid,
                        int(pos),
                        float(ds["points"]),
                        int(ds["wins"]),
                    ),
                )
                count += 1
        conn.commit()
        time.sleep(API_RATE_LIMIT_DELAY)
    if failed_rounds > 0:
        # Some rounds failed — leave the season unmarked so the next refresh
        # retries the whole set. Partial data is preserved by the per-round
        # commits above; INSERT OR IGNORE handles dedup on the next run.
        print(
            f"INFO: {failed_rounds}/{total_rounds} rounds failed for "
            f"driver_standings({year}); not marking as fetched",
            file=sys.stderr,
        )
        return
    _log_fetch(conn, "driver_standings", year, 0, count)
    conn.commit()


def load_constructor_standings(conn, year: int):
    """Load constructor standings for every round of a season."""
    if _already_fetched(conn, "constructor_standings", year):
        return
    total_rounds = _get_round_count(conn, year)
    if total_rounds == 0:
        return
    count = 0
    failed_rounds = 0
    for round_num in range(1, total_rounds + 1):
        try:
            standings_lists = fetch_constructor_standings_for_round(year, round_num)
        except Exception as e:
            failed_rounds += 1
            print(
                f"WARN: load_constructor_standings({year}/{round_num}) failed: {e}",
                file=sys.stderr,
            )
            continue
        for sl in standings_lists:
            for cs in sl.get("ConstructorStandings", []):
                _upsert_constructor(conn, cs["Constructor"])
                conn.execute(
                    "INSERT OR IGNORE INTO constructor_standings "
                    "(season, round, constructor_id, position, points, wins) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        year,
                        round_num,
                        cs["Constructor"]["constructorId"],
                        int(cs["position"]),
                        float(cs["points"]),
                        int(cs["wins"]),
                    ),
                )
                count += 1
        conn.commit()
        time.sleep(API_RATE_LIMIT_DELAY)
    if failed_rounds > 0:
        print(
            f"INFO: {failed_rounds}/{total_rounds} rounds failed for "
            f"constructor_standings({year}); not marking as fetched",
            file=sys.stderr,
        )
        return
    _log_fetch(conn, "constructor_standings", year, 0, count)
    conn.commit()


def load_season(conn, year: int, progress_callback=None):
    """Load all data for a single season."""
    steps = [
        ("Races", lambda: load_races(conn, year)),
        ("Results", lambda: load_results(conn, year)),
        ("Qualifying", lambda: load_qualifying(conn, year)),
        ("Sprint Results", lambda: load_sprint_results(conn, year)),
        ("Driver Standings", lambda: load_driver_standings(conn, year)),
        ("Constructor Standings", lambda: load_constructor_standings(conn, year)),
    ]
    for i, (name, fn) in enumerate(steps):
        if progress_callback:
            progress_callback(f"{year}: Loading {name}...", (i + 1) / len(steps))
        fn()

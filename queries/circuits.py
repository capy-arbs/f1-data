"""SQL queries for circuit and calendar data."""

import pandas as pd

from db.connection import get_db


def get_all_circuits() -> pd.DataFrame:
    """All circuits with all-time championship stats.

    Stats come from circuit_race_winners (complete 1950–today, completed races
    only) rather than the races table, which holds only the loaded seasons —
    and, for the current season, includes races that haven't run yet.
    on_current_calendar still comes from races: a circuit belongs to "Current"
    from the moment it's on this season's calendar, even before its race runs.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.circuit_id, c.name, c.locality, c.country, c.lat, c.lng,
                   COUNT(w.season) as race_count,
                   MIN(w.season) as first_race,
                   MAX(w.season) as last_race,
                   EXISTS(
                       SELECT 1 FROM races r
                       WHERE r.circuit_id = c.circuit_id
                         AND r.season = (SELECT MAX(season) FROM races)
                   ) as on_current_calendar
            FROM circuits c
            LEFT JOIN circuit_race_winners w ON c.circuit_id = w.circuit_id
            GROUP BY c.circuit_id
            ORDER BY race_count DESC
            """
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_circuit_history(circuit_id: str) -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT season, round, race_name, date,
                   winner_name as winner,
                   constructor_name as constructor
            FROM circuit_race_winners
            WHERE circuit_id = ?
            ORDER BY season DESC
            """,
            (circuit_id,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_race_calendar(season: int) -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.round, r.race_name, r.date, r.time,
                   ci.name as circuit, ci.locality, ci.country,
                   d.given_name || ' ' || d.family_name as winner,
                   d.code as winner_code,
                   c.name as winning_team
            FROM races r
            JOIN circuits ci ON r.circuit_id = ci.circuit_id
            LEFT JOIN results res ON r.race_id = res.race_id AND res.position = 1
            LEFT JOIN drivers d ON res.driver_id = d.driver_id
            LEFT JOIN constructors c ON res.constructor_id = c.constructor_id
            WHERE r.season = ?
            ORDER BY r.round
            """,
            (season,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])

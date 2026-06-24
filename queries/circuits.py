"""SQL queries for circuit and calendar data."""

import pandas as pd

from db.connection import get_db


def get_all_circuits() -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.circuit_id, c.name, c.locality, c.country, c.lat, c.lng,
                   COUNT(r.race_id) as race_count,
                   MIN(r.season) as first_race,
                   MAX(r.season) as last_race
            FROM circuits c
            LEFT JOIN races r ON c.circuit_id = r.circuit_id
            GROUP BY c.circuit_id
            ORDER BY race_count DESC
            """
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_circuit_history(circuit_id: str) -> pd.DataFrame:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, r.round, r.race_name, r.date,
                   d.given_name || ' ' || d.family_name as winner,
                   d.code as winner_code,
                   c.name as constructor
            FROM races r
            LEFT JOIN results res ON r.race_id = res.race_id AND res.position = 1
            LEFT JOIN drivers d ON res.driver_id = d.driver_id
            LEFT JOIN constructors c ON res.constructor_id = c.constructor_id
            WHERE r.circuit_id = ?
            ORDER BY r.season DESC
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

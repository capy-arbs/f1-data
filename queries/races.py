"""SQL queries for race results and pit stops."""

import pandas as pd

from db.connection import get_db


def get_race_results(season: int, round_num: int) -> pd.DataFrame:
    with get_db() as conn:
        race_id_row = conn.execute(
            "SELECT race_id FROM races WHERE season=? AND round=?",
            (season, round_num),
        ).fetchone()
        if not race_id_row:
            return pd.DataFrame()
        race_id = race_id_row["race_id"]

        rows = conn.execute(
            """
            SELECT r.grid, r.position, r.position_text, r.points, r.laps, r.status,
                   r.time_text, r.fastest_lap_rank, r.fastest_lap_time,
                   d.code, d.given_name, d.family_name,
                   c.name as constructor, c.constructor_id
            FROM results r
            JOIN drivers d ON r.driver_id = d.driver_id
            JOIN constructors c ON r.constructor_id = c.constructor_id
            WHERE r.race_id=?
            ORDER BY CASE WHEN r.position IS NOT NULL THEN r.position ELSE 999 END
            """,
            (race_id,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_race_info(season: int, round_num: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT r.race_name, r.date, r.time, ci.name as circuit,
                   ci.locality, ci.country
            FROM races r
            JOIN circuits ci ON r.circuit_id = ci.circuit_id
            WHERE r.season=? AND r.round=?
            """,
            (season, round_num),
        ).fetchone()
    return dict(row) if row else None


def get_qualifying_results(season: int, round_num: int) -> pd.DataFrame:
    with get_db() as conn:
        race_id_row = conn.execute(
            "SELECT race_id FROM races WHERE season=? AND round=?",
            (season, round_num),
        ).fetchone()
        if not race_id_row:
            return pd.DataFrame()

        rows = conn.execute(
            """
            SELECT q.position, q.q1, q.q2, q.q3,
                   d.code, d.given_name, d.family_name,
                   c.name as constructor
            FROM qualifying q
            JOIN drivers d ON q.driver_id = d.driver_id
            JOIN constructors c ON q.constructor_id = c.constructor_id
            WHERE q.race_id=?
            ORDER BY q.position
            """,
            (race_id_row["race_id"],),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_pit_stops(season: int, round_num: int) -> pd.DataFrame:
    with get_db() as conn:
        race_id_row = conn.execute(
            "SELECT race_id FROM races WHERE season=? AND round=?",
            (season, round_num),
        ).fetchone()
        if not race_id_row:
            return pd.DataFrame()

        rows = conn.execute(
            """
            SELECT ps.stop_number, ps.lap, ps.duration, ps.duration_s,
                   d.code, d.family_name
            FROM pit_stops ps
            JOIN drivers d ON ps.driver_id = d.driver_id
            WHERE ps.race_id=?
            ORDER BY ps.duration_s
            """,
            (race_id_row["race_id"],),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])

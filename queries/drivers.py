"""SQL queries for driver stats and head-to-head comparisons."""

import pandas as pd
from db.connection import get_db


def get_all_drivers() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.driver_id, d.code, d.given_name, d.family_name, d.nationality
            FROM drivers d
            ORDER BY d.family_name
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_career_stats(driver_id: str) -> dict:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as races,
                SUM(CASE WHEN position = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN position <= 3 AND position IS NOT NULL THEN 1 ELSE 0 END) as podiums,
                SUM(CASE WHEN grid = 1 THEN 1 ELSE 0 END) as poles,
                SUM(points) as total_points,
                SUM(CASE WHEN position IS NULL THEN 1 ELSE 0 END) as dnfs,
                MIN(CASE WHEN position IS NOT NULL THEN position END) as best_finish
            FROM results
            WHERE driver_id=?
            """,
            (driver_id,),
        ).fetchone()
    return dict(row) if row else {}


def get_driver_seasons(driver_id: str) -> list[int]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT r.season
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            WHERE res.driver_id=?
            ORDER BY r.season
            """,
            (driver_id,),
        ).fetchall()
    return [r["season"] for r in rows]


def get_season_stats(driver_id: str) -> pd.DataFrame:
    """Per-season breakdown for a driver."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season,
                   COUNT(*) as races,
                   SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN res.position <= 3 AND res.position IS NOT NULL THEN 1 ELSE 0 END) as podiums,
                   SUM(CASE WHEN res.grid = 1 THEN 1 ELSE 0 END) as poles,
                   SUM(res.points) as points,
                   SUM(CASE WHEN res.position IS NULL THEN 1 ELSE 0 END) as dnfs
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            WHERE res.driver_id=?
            GROUP BY r.season
            ORDER BY r.season
            """,
            (driver_id,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_head_to_head(d1: str, d2: str) -> pd.DataFrame:
    """Get races where both drivers competed, with their results side by side."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, r.round, r.race_name,
                   r1.position as d1_pos, r1.grid as d1_grid, r1.points as d1_points,
                   r2.position as d2_pos, r2.grid as d2_grid, r2.points as d2_points
            FROM results r1
            JOIN results r2 ON r1.race_id = r2.race_id
            JOIN races r ON r1.race_id = r.race_id
            WHERE r1.driver_id=? AND r2.driver_id=?
            ORDER BY r.season, r.round
            """,
            (d1, d2),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_teammate_seasons(d1: str, d2: str) -> pd.DataFrame:
    """Find seasons where two drivers were teammates (same constructor)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, r.round, r.race_name,
                   r1.position as d1_pos, r1.grid as d1_grid, r1.points as d1_points,
                   r2.position as d2_pos, r2.grid as d2_grid, r2.points as d2_points,
                   c.name as constructor
            FROM results r1
            JOIN results r2 ON r1.race_id = r2.race_id
            JOIN races r ON r1.race_id = r.race_id
            JOIN constructors c ON r1.constructor_id = c.constructor_id
            WHERE r1.driver_id=? AND r2.driver_id=?
              AND r1.constructor_id = r2.constructor_id
            ORDER BY r.season, r.round
            """,
            (d1, d2),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])

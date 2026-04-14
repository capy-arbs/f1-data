"""SQL queries for standings data."""

import pandas as pd
from db.connection import get_db


def get_available_seasons() -> list[int]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT season FROM races ORDER BY season DESC"
        ).fetchall()
    return [r["season"] for r in rows]


def get_driver_standings(season: int, round_num: int | None = None) -> pd.DataFrame:
    """Get driver standings for a season. If round is None, use the last round."""
    with get_db() as conn:
        if round_num is None:
            row = conn.execute(
                "SELECT MAX(round) as max_round FROM driver_standings WHERE season=?",
                (season,),
            ).fetchone()
            round_num = row["max_round"] if row else 1

        rows = conn.execute(
            """
            SELECT ds.position, d.code, d.given_name, d.family_name,
                   c.name as constructor, ds.points, ds.wins
            FROM driver_standings ds
            JOIN drivers d ON ds.driver_id = d.driver_id
            LEFT JOIN constructors c ON ds.constructor_id = c.constructor_id
            WHERE ds.season=? AND ds.round=?
            ORDER BY ds.position
            """,
            (season, round_num),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_constructor_standings(season: int, round_num: int | None = None) -> pd.DataFrame:
    with get_db() as conn:
        if round_num is None:
            row = conn.execute(
                "SELECT MAX(round) as max_round FROM constructor_standings WHERE season=?",
                (season,),
            ).fetchone()
            round_num = row["max_round"] if row else 1

        rows = conn.execute(
            """
            SELECT cs.position, c.name as constructor, cs.points, cs.wins
            FROM constructor_standings cs
            JOIN constructors c ON cs.constructor_id = c.constructor_id
            WHERE cs.season=? AND cs.round=?
            ORDER BY cs.position
            """,
            (season, round_num),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_position_progression(season: int) -> pd.DataFrame:
    """Get driver championship positions across all rounds of a season."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT ds.round, d.code, d.family_name, ds.position, ds.points,
                   ds.constructor_id
            FROM driver_standings ds
            JOIN drivers d ON ds.driver_id = d.driver_id
            WHERE ds.season=?
            ORDER BY ds.round, ds.position
            """,
            (season,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_rounds_for_season(season: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.round, r.race_name
            FROM races r
            WHERE r.season=?
            ORDER BY r.round
            """,
            (season,),
        ).fetchall()
    return [dict(r) for r in rows]

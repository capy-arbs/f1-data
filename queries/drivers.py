"""SQL queries for driver stats and head-to-head comparisons.

Sprint points note: results.points is *main-race only*. Sprint-race points
live in sprint_results.points (a separate table introduced for the 2021+
sprint-race format). When summing championship totals, both must be
included to match the official standings. The helpers here add sprint
contributions where appropriate; race-counts and wins/podiums/poles stay
main-race-only since those are tracked separately by F1.
"""

import pandas as pd
from db.connection import get_db


def _sprint_points_total(driver_id: str) -> float:
    """Career-long sprint points for a driver (0 if none)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(points), 0) AS p FROM sprint_results WHERE driver_id=?",
            (driver_id,),
        ).fetchone()
    return float(row["p"]) if row else 0.0


def _sprint_points_by_season(driver_id: str) -> dict[int, float]:
    """Per-season sprint points for a driver, keyed by year."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, SUM(sr.points) AS p
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            WHERE sr.driver_id=?
            GROUP BY r.season
            """,
            (driver_id,),
        ).fetchall()
    return {r["season"]: float(r["p"] or 0) for r in rows}


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


def get_current_drivers() -> list[dict]:
    """Drivers who raced in the most recent season in the database.

    Used by the "current grid" pages (Driver Profiles, Head-to-Head) so the
    dropdown isn't padded with 70 years of retired drivers — those live on the
    historical-archive versions instead.
    """
    with get_db() as conn:
        latest = conn.execute(
            "SELECT MAX(season) AS s FROM races"
        ).fetchone()
        if not latest or latest["s"] is None:
            return []
        rows = conn.execute(
            """
            SELECT DISTINCT d.driver_id, d.code, d.given_name, d.family_name, d.nationality
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            JOIN races r ON res.race_id = r.race_id
            WHERE r.season = ?
            ORDER BY d.family_name
            """,
            (latest["s"],),
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
    if not row:
        return {}
    d = dict(row)
    # Add sprint points to the championship total — wins/podiums/poles stay
    # main-race-only by F1 convention.
    d["total_points"] = (d.get("total_points") or 0) + _sprint_points_total(driver_id)
    return d


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
    """Per-season breakdown for a driver. ``points`` includes sprint points."""
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
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    sprint_by_season = _sprint_points_by_season(driver_id)
    if sprint_by_season:
        df["points"] = df["points"].fillna(0) + df["season"].map(sprint_by_season).fillna(0)
    return df


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

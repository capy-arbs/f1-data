"""SQL queries for historical records and era comparisons."""

import pandas as pd
from db.connection import get_db
from data.normalizer import normalize_points


def get_career_comparison(driver_ids: list[str]) -> pd.DataFrame:
    """Get career stats for multiple drivers side by side."""
    with get_db() as conn:
        placeholders = ",".join("?" for _ in driver_ids)
        rows = conn.execute(
            f"""
            SELECT d.driver_id, d.given_name, d.family_name, d.code,
                   COUNT(*) as races,
                   SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN res.position <= 3 AND res.position IS NOT NULL THEN 1 ELSE 0 END) as podiums,
                   SUM(CASE WHEN res.grid = 1 THEN 1 ELSE 0 END) as poles,
                   SUM(res.points) as total_points,
                   SUM(CASE WHEN res.position IS NULL THEN 1 ELSE 0 END) as dnfs,
                   ROUND(100.0 * SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_pct,
                   ROUND(100.0 * SUM(CASE WHEN res.position <= 3 AND res.position IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as podium_pct,
                   ROUND(SUM(res.points) / COUNT(*), 2) as points_per_race
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            WHERE res.driver_id IN ({placeholders})
            GROUP BY res.driver_id
            """,
            driver_ids,
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_normalized_season_points(driver_id: str, target_system: str = "2010-present") -> pd.DataFrame:
    """Recalculate a driver's career points under a different point system."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, res.position, res.points as actual_points
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            WHERE res.driver_id=?
            ORDER BY r.season, r.round
            """,
            (driver_id,),
        ).fetchall()

    data = []
    for row in rows:
        d = dict(row)
        d["normalized_points"] = normalize_points(d["position"], target_system)
        data.append(d)

    df = pd.DataFrame(data)
    if df.empty:
        return df
    return df.groupby("season").agg(
        actual_points=("actual_points", "sum"),
        normalized_points=("normalized_points", "sum"),
        races=("position", "count"),
    ).reset_index()


def get_records(record_type: str) -> pd.DataFrame:
    """Get various F1 records."""
    queries = {
        "most_wins": """
            SELECT d.given_name, d.family_name, d.code,
                   SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) as value
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            GROUP BY res.driver_id
            HAVING value > 0
            ORDER BY value DESC
            LIMIT 20
        """,
        "most_podiums": """
            SELECT d.given_name, d.family_name, d.code,
                   SUM(CASE WHEN res.position <= 3 AND res.position IS NOT NULL THEN 1 ELSE 0 END) as value
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            GROUP BY res.driver_id
            HAVING value > 0
            ORDER BY value DESC
            LIMIT 20
        """,
        "most_poles": """
            SELECT d.given_name, d.family_name, d.code,
                   SUM(CASE WHEN res.grid = 1 THEN 1 ELSE 0 END) as value
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            GROUP BY res.driver_id
            HAVING value > 0
            ORDER BY value DESC
            LIMIT 20
        """,
        "most_points": """
            SELECT d.given_name, d.family_name, d.code,
                   SUM(res.points) as value
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            GROUP BY res.driver_id
            HAVING value > 0
            ORDER BY value DESC
            LIMIT 20
        """,
        "most_races": """
            SELECT d.given_name, d.family_name, d.code,
                   COUNT(*) as value
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            GROUP BY res.driver_id
            ORDER BY value DESC
            LIMIT 20
        """,
        "highest_win_rate": """
            SELECT d.given_name, d.family_name, d.code,
                   ROUND(100.0 * SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as value
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            GROUP BY res.driver_id
            HAVING COUNT(*) >= 20
            ORDER BY value DESC
            LIMIT 20
        """,
    }
    query = queries.get(record_type)
    if not query:
        return pd.DataFrame()

    with get_db() as conn:
        rows = conn.execute(query).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_championship_wins() -> pd.DataFrame:
    """Count championship wins (P1 in final driver standings) per driver."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.given_name, d.family_name, d.code, d.driver_id,
                   COUNT(*) as championships
            FROM driver_standings ds
            JOIN drivers d ON ds.driver_id = d.driver_id
            WHERE ds.position = 1
              AND ds.round = (
                  SELECT MAX(ds2.round)
                  FROM driver_standings ds2
                  WHERE ds2.season = ds.season
              )
            GROUP BY ds.driver_id
            ORDER BY championships DESC
            LIMIT 20
            """
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])

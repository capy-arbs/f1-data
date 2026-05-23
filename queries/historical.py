"""SQL queries for historical records and era comparisons."""

import pandas as pd
from db.connection import get_db
from data.normalizer import normalize_points


def get_career_comparison(driver_ids: list[str]) -> pd.DataFrame:
    """Get career stats for multiple drivers side by side.

    ``total_points`` and ``points_per_race`` include sprint points.
    """
    with get_db() as conn:
        placeholders = ",".join("?" for _ in driver_ids)
        rows = conn.execute(
            f"""
            SELECT d.driver_id, d.given_name, d.family_name, d.code,
                   COUNT(*) as races,
                   SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN res.position <= 3 AND res.position IS NOT NULL THEN 1 ELSE 0 END) as podiums,
                   SUM(CASE WHEN res.grid = 1 THEN 1 ELSE 0 END) as poles,
                   SUM(res.points) as race_points,
                   SUM(CASE WHEN res.position IS NULL THEN 1 ELSE 0 END) as dnfs,
                   ROUND(100.0 * SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_pct,
                   ROUND(100.0 * SUM(CASE WHEN res.position <= 3 AND res.position IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as podium_pct
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            WHERE res.driver_id IN ({placeholders})
            GROUP BY res.driver_id
            """,
            driver_ids,
        ).fetchall()
        sprint_rows = conn.execute(
            f"""
            SELECT driver_id, COALESCE(SUM(points), 0) AS p
            FROM sprint_results
            WHERE driver_id IN ({placeholders})
            GROUP BY driver_id
            """,
            driver_ids,
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    sprint_map = {r["driver_id"]: r["p"] for r in sprint_rows}
    df["sprint_points"] = df["driver_id"].map(sprint_map).fillna(0)
    df["total_points"] = df["race_points"].fillna(0) + df["sprint_points"]
    df["points_per_race"] = (df["total_points"] / df["races"]).round(2)
    df = df.drop(columns=["race_points", "sprint_points"])
    return df


def get_normalized_season_points(driver_id: str, target_system: str = "2010-present") -> pd.DataFrame:
    """Recalculate a driver's career points under a different point system.

    Includes sprint races (2021+). For both the actual and normalized totals,
    each finishing position — main race or sprint — gets re-mapped through
    the target system's points table. The ``actual_points`` total matches
    the official championship standings.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT season, position, actual_points FROM (
                SELECT r.season, res.position, res.points AS actual_points
                FROM results res
                JOIN races r ON res.race_id = r.race_id
                WHERE res.driver_id=?
                UNION ALL
                SELECT r.season, sr.position, sr.points AS actual_points
                FROM sprint_results sr
                JOIN races r ON sr.race_id = r.race_id
                WHERE sr.driver_id=?
            )
            """,
            (driver_id, driver_id),
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
            SELECT d.given_name, d.family_name, d.code, SUM(p.pts) AS value
            FROM (
                SELECT driver_id, points AS pts FROM results
                UNION ALL
                SELECT driver_id, points AS pts FROM sprint_results
            ) p
            JOIN drivers d ON p.driver_id = d.driver_id
            GROUP BY p.driver_id
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


def get_fastest_pit_stops(season: int | None = None, limit: int = 50) -> pd.DataFrame:
    """All-time (or per-season) fastest pit stops, ordered ascending by duration_s.

    Pit stop data only exists from 2011 onwards in the source feed; rows with a
    null duration_s (older races / DNF stops) are excluded.
    """
    where = "ps.duration_s IS NOT NULL AND ps.duration_s > 0"
    params: list = []
    if season is not None:
        where += " AND r.season = ?"
        params.append(season)
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(
            f"""
            SELECT r.season, r.round, r.race_name, r.date,
                   d.given_name || ' ' || d.family_name AS driver,
                   d.code AS code,
                   c.name AS constructor,
                   ps.lap, ps.duration, ps.duration_s
            FROM pit_stops ps
            JOIN races r ON ps.race_id = r.race_id
            JOIN drivers d ON ps.driver_id = d.driver_id
            JOIN results res ON res.race_id = ps.race_id AND res.driver_id = ps.driver_id
            JOIN constructors c ON res.constructor_id = c.constructor_id
            WHERE {where}
            ORDER BY ps.duration_s ASC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_championship_momentum(season: int, window: int = 3) -> pd.DataFrame:
    """For each round, sum each driver's points over the trailing ``window`` races.

    Includes sprint-race points (which live in a separate table) — Kimi's
    season-total here would otherwise differ from the official standings by
    his sprint contribution.

    Tells the "who's hot right now" story — a leader with declining momentum vs.
    a chaser surging into form is the classic championship narrative.
    """
    with get_db() as conn:
        # Main-race points + sprint points per (round, driver). UNION ALL
        # then GROUP so a driver who scored in both at the same round gets
        # one summed row.
        rows = conn.execute(
            """
            SELECT round, race_name, driver_id, code, family_name,
                   constructor_id, constructor, SUM(points) AS points
            FROM (
                SELECT r.round, r.race_name,
                       d.driver_id, d.code, d.family_name,
                       c.constructor_id, c.name AS constructor,
                       res.points AS points
                FROM results res
                JOIN races r ON res.race_id = r.race_id
                JOIN drivers d ON res.driver_id = d.driver_id
                JOIN constructors c ON res.constructor_id = c.constructor_id
                WHERE r.season = ?
                UNION ALL
                SELECT r.round, r.race_name,
                       d.driver_id, d.code, d.family_name,
                       c.constructor_id, c.name AS constructor,
                       sr.points AS points
                FROM sprint_results sr
                JOIN races r ON sr.race_id = r.race_id
                JOIN drivers d ON sr.driver_id = d.driver_id
                JOIN constructors c ON sr.constructor_id = c.constructor_id
                WHERE r.season = ?
            )
            GROUP BY round, driver_id
            ORDER BY round, family_name
            """,
            (season, season),
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df

    df = df.sort_values(["family_name", "round"]).reset_index(drop=True)
    df["rolling_points"] = (
        df.groupby("family_name")["points"]
        .transform(lambda s: s.rolling(window=window, min_periods=1).sum())
    )
    df["season_total"] = df.groupby("family_name")["points"].transform("cumsum")
    return df


def get_lap_time_evolution(circuit_id: str) -> pd.DataFrame:
    """Year-by-year fastest race lap at one circuit — pace evolution over time.

    ``fastest_lap_time`` is stored as "M:SS.mmm" text in the schema so we
    parse it client-side. Drivers without a recorded fastest lap (early eras)
    are simply absent from the output.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, r.race_name, r.date,
                   res.fastest_lap_time, res.fastest_lap_speed,
                   d.given_name || ' ' || d.family_name AS driver,
                   d.code AS code,
                   c.name AS constructor
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            JOIN drivers d ON res.driver_id = d.driver_id
            JOIN constructors c ON res.constructor_id = c.constructor_id
            WHERE r.circuit_id = ?
              AND res.fastest_lap_time IS NOT NULL
              AND res.fastest_lap_rank = 1
            ORDER BY r.season, r.round
            """,
            (circuit_id,),
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df

    def _to_seconds(t: str) -> float | None:
        try:
            mins, rest = t.split(":", 1)
            return int(mins) * 60 + float(rest)
        except (ValueError, AttributeError):
            return None

    df["lap_seconds"] = df["fastest_lap_time"].apply(_to_seconds)
    df = df.dropna(subset=["lap_seconds"])
    return df


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

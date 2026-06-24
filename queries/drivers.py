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


def get_latest_constructor(driver_id: str) -> str | None:
    """Constructor a driver most recently raced for. Used for team-aware
    coloring on head-to-head charts so each driver's bar uses their actual
    team's livery instead of a fixed red/blue palette.
    """
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT res.constructor_id
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            WHERE res.driver_id = ?
            ORDER BY r.season DESC, r.round DESC
            LIMIT 1
            """,
            (driver_id,),
        ).fetchone()
    return row["constructor_id"] if row else None


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
    """Get races where both drivers competed, with their results side by side.

    ``d1_points`` / ``d2_points`` are championship totals per race —
    main-race points UNION sprint points where applicable (LEFT JOIN with
    sprint_results, coalescing to 0 for non-sprint weekends).
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, r.round, r.race_name,
                   r1.position as d1_pos, r1.grid as d1_grid,
                   r1.points + COALESCE(sr1.points, 0) as d1_points,
                   r2.position as d2_pos, r2.grid as d2_grid,
                   r2.points + COALESCE(sr2.points, 0) as d2_points
            FROM results r1
            JOIN results r2 ON r1.race_id = r2.race_id
            JOIN races r ON r1.race_id = r.race_id
            LEFT JOIN sprint_results sr1
                   ON sr1.race_id = r1.race_id AND sr1.driver_id = r1.driver_id
            LEFT JOIN sprint_results sr2
                   ON sr2.race_id = r2.race_id AND sr2.driver_id = r2.driver_id
            WHERE r1.driver_id=? AND r2.driver_id=?
            ORDER BY r.season, r.round
            """,
            (d1, d2),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_season_supplements(driver_id: str) -> pd.DataFrame:
    """Per-season championship position + team for a driver, in one query.

    Replaces a previous N+1 loop in ``views/driver_profile.py`` that ran
    two queries per season (Schumacher's profile fired ~40 queries). The
    rewrite collapses both lookups into a single statement using a CTE
    for the per-season final-round map.

    Returns a DataFrame with ``season``, ``champ_pos``, ``team``.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            WITH season_last_round AS (
                SELECT season, MAX(round) AS final_round
                FROM driver_standings
                GROUP BY season
            ),
            driver_team_per_season AS (
                -- DISTINCT picks one team per season; matches the original
                -- code's `SELECT DISTINCT ... LIMIT 1` behaviour when a
                -- driver changed teams mid-season.
                SELECT DISTINCT r.season, c.name AS team
                FROM results res
                JOIN constructors c ON res.constructor_id = c.constructor_id
                JOIN races r ON res.race_id = r.race_id
                WHERE res.driver_id = ?
            )
            SELECT ds.season,
                   ds.position AS champ_pos,
                   COALESCE(t.team, '') AS team
            FROM driver_standings ds
            JOIN season_last_round slr
              ON ds.season = slr.season AND ds.round = slr.final_round
            LEFT JOIN driver_team_per_season t ON t.season = ds.season
            WHERE ds.driver_id = ?
            ORDER BY ds.season
            """,
            (driver_id, driver_id),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_teammate_seasons(d1: str, d2: str) -> pd.DataFrame:
    """Find seasons where two drivers were teammates (same constructor).

    ``d1_points`` / ``d2_points`` UNION sprint points per race for the
    same reason as ``get_head_to_head`` — the teammate-comparison table
    in the UI sums these per season and must match the official totals.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.season, r.round, r.race_name,
                   r1.position as d1_pos, r1.grid as d1_grid,
                   r1.points + COALESCE(sr1.points, 0) as d1_points,
                   r2.position as d2_pos, r2.grid as d2_grid,
                   r2.points + COALESCE(sr2.points, 0) as d2_points,
                   c.name as constructor
            FROM results r1
            JOIN results r2 ON r1.race_id = r2.race_id
            JOIN races r ON r1.race_id = r.race_id
            JOIN constructors c ON r1.constructor_id = c.constructor_id
            LEFT JOIN sprint_results sr1
                   ON sr1.race_id = r1.race_id AND sr1.driver_id = r1.driver_id
            LEFT JOIN sprint_results sr2
                   ON sr2.race_id = r2.race_id AND sr2.driver_id = r2.driver_id
            WHERE r1.driver_id=? AND r2.driver_id=?
              AND r1.constructor_id = r2.constructor_id
            ORDER BY r.season, r.round
            """,
            (d1, d2),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])

"""Queries + compute helpers for the Sprint Analysis page.

Sprint points live in ``sprint_results.points`` (separate from main-race
``results.points`` — see CLAUDE.md). The leaderboard here is sprint-only by
design; anywhere a *championship* total is summed it must union both tables.
"""

from __future__ import annotations

import pandas as pd

from db.connection import get_db


def get_sprint_seasons() -> list[int]:
    """Seasons that have any sprint results, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT r.season
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            ORDER BY r.season DESC
            """
        ).fetchall()
    return [r["season"] for r in rows]


def get_sprint_races(season: int) -> list[dict]:
    """Rounds in ``season`` that held a sprint."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT r.round, r.race_name
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            WHERE r.season = ?
            ORDER BY r.round
            """,
            (season,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_sprint_results(season: int, round_num: int) -> pd.DataFrame:
    """Full classification for one sprint, retirements sorted to the back."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT sr.grid, sr.position, sr.position_text, sr.points,
                   sr.laps, sr.status, sr.time_text,
                   d.code, d.given_name, d.family_name,
                   c.name as constructor, c.constructor_id
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            JOIN drivers d ON sr.driver_id = d.driver_id
            JOIN constructors c ON sr.constructor_id = c.constructor_id
            WHERE r.season = ? AND r.round = ?
            ORDER BY CASE WHEN sr.position IS NOT NULL THEN sr.position ELSE 999 END
            """,
            (season, round_num),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_sprint_points_by_driver(season: int) -> pd.DataFrame:
    """Sprint-only points/wins per driver for a season (sprint leaderboard)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT d.given_name || ' ' || d.family_name as driver,
                   d.code, SUM(sr.points) as sprint_points,
                   COUNT(*) as sprint_races,
                   SUM(CASE WHEN sr.position = 1 THEN 1 ELSE 0 END) as sprint_wins
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            JOIN drivers d ON sr.driver_id = d.driver_id
            WHERE r.season = ?
            GROUP BY sr.driver_id
            HAVING sprint_points > 0
            ORDER BY sprint_points DESC
            """,
            (season,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_sprint_vs_race(season: int) -> pd.DataFrame:
    """Per-driver sprint vs main-race grid/finish for a season (raw rows)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.round, r.race_name,
                   d.code, d.given_name || ' ' || d.family_name as driver,
                   sr.position as sprint_pos, sr.grid as sprint_grid,
                   res.position as race_pos, res.grid as race_grid
            FROM sprint_results sr
            JOIN races r ON sr.race_id = r.race_id
            JOIN drivers d ON sr.driver_id = d.driver_id
            LEFT JOIN results res ON sr.race_id = res.race_id AND sr.driver_id = res.driver_id
            WHERE r.season = ?
            ORDER BY r.round, sr.position
            """,
            (season,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def sprint_vs_race_summary(comparison: pd.DataFrame) -> pd.DataFrame:
    """Average sprint-vs-race position delta per driver.

    Takes the raw frame from ``get_sprint_vs_race`` and returns one row per
    driver with mean sprint/race positions and ``diff = race_pos - sprint_pos``
    (positive = finishes better in sprints), sorted by ``diff`` desc. Empty when
    no driver has both a sprint and a race result.
    """
    cols = ["driver", "code", "avg_sprint", "avg_race", "diff"]
    if comparison.empty:
        return pd.DataFrame(columns=cols)
    valid = comparison[comparison["sprint_pos"].notna() & comparison["race_pos"].notna()].copy()
    if valid.empty:
        return pd.DataFrame(columns=cols)
    valid["sprint_better"] = valid["race_pos"] - valid["sprint_pos"]
    return (
        valid.groupby(["driver", "code"])
        .agg(avg_sprint=("sprint_pos", "mean"),
             avg_race=("race_pos", "mean"),
             diff=("sprint_better", "mean"))
        .reset_index()
        .sort_values("diff", ascending=False)
    )

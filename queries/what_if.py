"""Queries + compute helpers for the What-If Simulator.

Extracted from ``pages/8_What_If.py`` on 2026-05-23. Keeps SQL out of the
page and lets these helpers be unit-tested independently.

``points`` on ``get_season_results`` includes sprint contributions via a
LEFT JOIN on ``sprint_results`` (otherwise totals diverge from official
standings for 2021+ seasons — see CLAUDE.md sprint-points invariant).
"""

from __future__ import annotations

import pandas as pd

from db.connection import get_db


def get_season_results(season: int) -> pd.DataFrame:
    """Per-race results for a season.

    ``points`` is the championship total per race — main-race points plus
    sprint points, coalesced to 0 for non-sprint weekends. Required so
    the Driver Swap and Alternative Points System tabs match official
    standings.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.round, r.race_name, res.driver_id,
                   d.given_name || ' ' || d.family_name as driver_name,
                   d.code, res.position,
                   res.points + COALESCE(sr.points, 0) as points,
                   res.grid,
                   c.name as constructor
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            JOIN drivers d ON res.driver_id = d.driver_id
            JOIN constructors c ON res.constructor_id = c.constructor_id
            LEFT JOIN sprint_results sr
                   ON sr.race_id = res.race_id AND sr.driver_id = res.driver_id
            WHERE r.season = ?
            ORDER BY r.round, res.position
            """,
            (season,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_season_drivers(season: int) -> list[dict]:
    """Drivers who raced in a given season."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT d.driver_id,
                   d.given_name || ' ' || d.family_name as name,
                   d.code
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            JOIN races r ON res.race_id = r.race_id
            WHERE r.season = ?
            ORDER BY d.family_name
            """,
            (season,),
        ).fetchall()
    return [dict(r) for r in rows]


def calculate_standings(results: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-race results into a season standings table.

    Sorts by total points desc, then wins desc as tiebreaker. Index is
    1-based with name "Pos" so Streamlit's dataframe renderer surfaces it
    as the position column.
    """
    standings = (
        results.groupby(["driver_id", "driver_name", "code"])
        .agg(
            total_points=("points", "sum"),
            wins=("position", lambda x: (x == 1).sum()),
            podiums=("position", lambda x: ((x >= 1) & (x <= 3)).sum()),
            races=("position", "count"),
        )
        .reset_index()
    )
    standings = standings.sort_values(
        ["total_points", "wins"], ascending=[False, False]
    ).reset_index(drop=True)
    standings.index = standings.index + 1
    standings.index.name = "Pos"
    return standings

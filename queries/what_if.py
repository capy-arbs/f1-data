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


# -- Pure simulation transforms (extracted from pages/8_What_If.py) ----------
# These take a per-race results frame (the shape get_season_results returns) and
# return a modified copy. No Streamlit, no DB — so they're unit-testable and the
# page stays a thin renderer.

def apply_points_system(results: pd.DataFrame, points_map: dict[int, float]) -> pd.DataFrame:
    """Recompute ``points`` from finishing ``position`` under ``points_map``.

    Positions outside the map (or DNFs) score 0. Sprint/fastest-lap bonuses
    baked into the original points are intentionally dropped — this answers
    "what if only the base finish-points scale changed?".
    """
    out = results.copy()
    out["points"] = out["position"].apply(
        lambda p: float(points_map.get(int(p), 0)) if pd.notna(p) else 0.0
    )
    return out


def apply_driver_swap(results: pd.DataFrame, replace_id: str, with_id: str) -> pd.DataFrame:
    """Give ``replace_id`` the race-by-race results of ``with_id``.

    Asymmetric transplant: ``with_id`` keeps their own results. Returns an
    unmodified copy when the two ids match.
    """
    modified = results.copy()
    if replace_id == with_id:
        return modified
    source = results[results["driver_id"] == with_id]
    for _, src in source.iterrows():
        mask = (modified["driver_id"] == replace_id) & (modified["round"] == src["round"])
        if mask.any():
            modified.loc[mask, "position"] = src["position"]
            modified.loc[mask, "points"] = src["points"]
    return modified


def apply_overrides(
    results: pd.DataFrame,
    overrides: list[dict],
    points_map: dict[int, float],
) -> pd.DataFrame:
    """Apply single-race position overrides with cascade insertion.

    Each override is ``{"round", "driver_id", "orig_pos", "new_pos"}`` where
    positions are 1-based ints and ``None`` means DNF. For each one we vacate
    the driver's old slot (cars below shift up), then insert them at the new
    slot (cars at/below shift down), and recompute that race's points under
    ``points_map``. Stacking multiple overrides compounds them.
    """
    modified = results.copy()
    for ov in overrides:
        race_mask = modified["round"] == ov["round"]
        if not race_mask.any():
            continue
        race_slice = modified[race_mask].copy().sort_values("position", na_position="last")
        d_mask = race_slice["driver_id"] == ov["driver_id"]
        if not d_mask.any():
            continue

        old_p, new_p = ov["orig_pos"], ov["new_pos"]

        # Step 1: vacate the old slot — drivers below shift up one.
        if old_p is not None:
            shift_up = race_slice["position"].notna() & (race_slice["position"] > old_p)
            race_slice.loc[shift_up, "position"] = race_slice.loc[shift_up, "position"] - 1

        # Step 2: insert at the new slot — drivers at/below shift down one.
        if new_p is not None:
            shift_down = (
                race_slice["position"].notna()
                & (race_slice["position"] >= new_p)
                & (~d_mask)
            )
            race_slice.loc[shift_down, "position"] = race_slice.loc[shift_down, "position"] + 1
            race_slice.loc[d_mask, "position"] = new_p
        else:
            race_slice.loc[d_mask, "position"] = None  # became a DNF

        race_slice = apply_points_system(race_slice, points_map)
        modified = pd.concat([modified[~race_mask], race_slice], ignore_index=True)

    return modified.sort_values(["round", "position"], na_position="last").reset_index(drop=True)


def standings_rank_changes(
    original: pd.DataFrame,
    modified: pd.DataFrame,
) -> pd.DataFrame:
    """Championship-rank movement between two standings tables.

    Rank is row order (1-based) in each ``calculate_standings`` result.
    Returns one row per driver who moved, columns ``Driver``, ``Original``,
    ``New``, ``Change`` (positive = moved up), sorted by ``Change`` desc.
    """
    orig_rank = {row["driver_name"]: i + 1 for i, (_, row) in enumerate(original.iterrows())}
    mod_rank = {row["driver_name"]: i + 1 for i, (_, row) in enumerate(modified.iterrows())}
    changes = [
        {"Driver": driver, "Original": op, "New": mod_rank.get(driver, op),
         "Change": op - mod_rank.get(driver, op)}
        for driver, op in orig_rank.items()
        if op - mod_rank.get(driver, op) != 0
    ]
    return (
        pd.DataFrame(changes, columns=["Driver", "Original", "New", "Change"])
        .sort_values("Change", ascending=False)
        .reset_index(drop=True)
    )

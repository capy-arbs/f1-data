"""Invariant test: sprint_results.points must UNION into championship totals.

The dashboard's own CLAUDE.md documents this as a critical convention.
We've shipped at least three regressions of it (caught 2026-05-23 in
get_head_to_head, get_teammate_seasons, and What-If's get_season_results).
This test pins the invariant for the methods that surface totals.

Strategy: build a tiny in-memory SQLite from the production schema,
insert a fixture driver with both main-race points and sprint points
in a single race, then call each documented points-summing method and
assert the result equals main + sprint, not main only.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from db.schema import SCHEMA_SQL


def _make_db():
    """Build an in-memory DB with the production schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def _seed_minimal_fixture(conn):
    """Driver SCO with 10 main-race points + 3 sprint points at one race."""
    conn.executescript("""
        INSERT INTO seasons (year) VALUES (2026);
        INSERT INTO circuits (circuit_id, name) VALUES ('miami', 'Miami International Autodrome');
        INSERT INTO races (race_id, season, round, race_name, circuit_id, date)
            VALUES (1, 2026, 4, 'Miami Grand Prix', 'miami', '2026-05-04');
        INSERT INTO drivers (driver_id, code, given_name, family_name)
            VALUES ('test_driver', 'SCO', 'Test', 'Scorer');
        INSERT INTO constructors (constructor_id, name)
            VALUES ('test_team', 'Test Team');
        -- Main race: P3 with 10 points
        INSERT INTO results
            (race_id, driver_id, constructor_id, grid, position, position_text, points, laps, status)
            VALUES (1, 'test_driver', 'test_team', 5, 3, '3', 10.0, 57, 'Finished');
        -- Sprint: P5 with 3 points
        INSERT INTO sprint_results
            (race_id, driver_id, constructor_id, grid, position, position_text, points, laps, status)
            VALUES (1, 'test_driver', 'test_team', 4, 5, '5', 3.0, 19, 'Finished');
    """)
    conn.commit()


@pytest.fixture
def db_with_fixture(monkeypatch):
    """Patch get_db so query functions see our in-memory DB instead of the file."""
    conn = _make_db()
    _seed_minimal_fixture(conn)

    from contextlib import contextmanager

    @contextmanager
    def fake_get_db():
        try:
            yield conn
        finally:
            pass  # Keep the connection alive across multiple calls within a test.

    # Patch every module that imports get_db locally.
    import queries.drivers as q_drivers
    monkeypatch.setattr(q_drivers, "get_db", fake_get_db)

    yield conn
    conn.close()


def test_get_career_stats_includes_sprint_points(db_with_fixture):
    """get_career_stats must report total_points = 10 + 3 = 13, not 10."""
    from queries.drivers import get_career_stats
    stats = get_career_stats("test_driver")
    assert stats["total_points"] == pytest.approx(13.0)


def test_get_season_stats_includes_sprint_points(db_with_fixture):
    """get_season_stats per-row points must include sprint contributions."""
    from queries.drivers import get_season_stats
    df = get_season_stats("test_driver")
    assert not df.empty
    assert df["points"].iloc[0] == pytest.approx(13.0)


def test_get_head_to_head_includes_sprint_points(db_with_fixture):
    """The fix from 2026-05-23: per-race d1_points must UNION sprint."""
    from queries.drivers import get_head_to_head
    # Add a second driver in the same race so the join produces rows.
    conn = db_with_fixture
    conn.executescript("""
        INSERT INTO drivers (driver_id, code, given_name, family_name)
            VALUES ('rival_driver', 'RIV', 'The', 'Rival');
        INSERT INTO results
            (race_id, driver_id, constructor_id, grid, position, position_text, points, laps, status)
            VALUES (1, 'rival_driver', 'test_team', 6, 4, '4', 8.0, 57, 'Finished');
        INSERT INTO sprint_results
            (race_id, driver_id, constructor_id, grid, position, position_text, points, laps, status)
            VALUES (1, 'rival_driver', 'test_team', 5, 6, '6', 2.0, 19, 'Finished');
    """)
    conn.commit()

    df = get_head_to_head("test_driver", "rival_driver")
    assert not df.empty
    # Test driver: 10 (main) + 3 (sprint) = 13
    assert df["d1_points"].iloc[0] == pytest.approx(13.0)
    # Rival: 8 (main) + 2 (sprint) = 10
    assert df["d2_points"].iloc[0] == pytest.approx(10.0)


def test_get_teammate_seasons_includes_sprint_points(db_with_fixture):
    """Same shape, teammate variant — both drivers in the same constructor."""
    from queries.drivers import get_teammate_seasons
    conn = db_with_fixture
    conn.executescript("""
        INSERT INTO drivers (driver_id, code, given_name, family_name)
            VALUES ('teammate_driver', 'TMT', 'Team', 'Mate');
        INSERT INTO results
            (race_id, driver_id, constructor_id, grid, position, position_text, points, laps, status)
            VALUES (1, 'teammate_driver', 'test_team', 7, 6, '6', 5.0, 57, 'Finished');
        INSERT INTO sprint_results
            (race_id, driver_id, constructor_id, grid, position, position_text, points, laps, status)
            VALUES (1, 'teammate_driver', 'test_team', 6, 7, '7', 1.0, 19, 'Finished');
    """)
    conn.commit()

    df = get_teammate_seasons("test_driver", "teammate_driver")
    assert not df.empty
    assert df["d1_points"].iloc[0] == pytest.approx(13.0)
    assert df["d2_points"].iloc[0] == pytest.approx(6.0)

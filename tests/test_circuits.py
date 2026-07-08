"""Circuit Explorer stats: all-time winners archive, not loaded-seasons slice.

The stats regression this pins (caught 2026-07-07): with only a few seasons
loaded, get_all_circuits reported those as all-time circuit stats — Spa showed
11 races / first race 1950 despite ~58 championship races — and race_count
counted current-season races that hadn't run yet. Stats must come from the
complete circuit_race_winners archive (completed races only), while the
Current/Past split still comes from the current season's calendar.
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from db.schema import SCHEMA_SQL


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def _seed(conn):
    """Two circuits: Spa with a long winners archive but only the current
    season in races (race not yet run), and a brand-new circuit that's on the
    current calendar with no completed race."""
    conn.executescript("""
        INSERT INTO circuits (circuit_id, name, locality, country)
            VALUES ('spa', 'Circuit de Spa-Francorchamps', 'Spa', 'Belgium'),
                   ('madring', 'Madring', 'Madrid', 'Spain'),
                   ('adelaide', 'Adelaide Street Circuit', 'Adelaide', 'Australia');
        -- races: only the current (partially-run) season is loaded.
        INSERT INTO races (race_id, season, round, race_name, circuit_id, date) VALUES
            (1, 2026, 13, 'Belgian Grand Prix', 'spa', '2026-07-26'),
            (2, 2026, 16, 'Spanish Grand Prix', 'madring', '2026-09-13');
        -- winners archive: complete history, completed races only.
        INSERT INTO circuit_race_winners
            (season, round, circuit_id, race_name, date, winner_name, winner_id, constructor_name)
        VALUES
            (1950, 5, 'spa', 'Belgian Grand Prix', '1950-06-18', 'Juan Fangio', 'fangio', 'Alfa Romeo'),
            (1995, 11, 'spa', 'Belgian Grand Prix', '1995-08-27', 'Michael Schumacher', 'michael_schumacher', 'Benetton'),
            (2025, 13, 'spa', 'Belgian Grand Prix', '2025-07-27', 'Oscar Piastri', 'piastri', 'McLaren'),
            (1995, 16, 'adelaide', 'Australian Grand Prix', '1995-11-12', 'Damon Hill', 'damon_hill', 'Williams');
    """)
    conn.commit()


@pytest.fixture
def circuits_db(monkeypatch):
    conn = _make_db()
    _seed(conn)

    @contextmanager
    def fake_get_db():
        yield conn

    import queries.circuits as q_circuits
    monkeypatch.setattr(q_circuits, "get_db", fake_get_db)
    yield conn
    conn.close()


def test_stats_come_from_winners_archive_not_loaded_races(circuits_db):
    from queries.circuits import get_all_circuits
    df = get_all_circuits().set_index("circuit_id")
    spa = df.loc["spa"]
    assert spa["race_count"] == 3  # not 1 (loaded races), not 4 (incl. unrun 2026)
    assert spa["first_race"] == 1950
    assert spa["last_race"] == 2025  # 2026 race hasn't run


def test_current_past_split_uses_calendar_not_last_winner(circuits_db):
    from queries.circuits import get_all_circuits
    df = get_all_circuits().set_index("circuit_id")
    # Spa's latest completed race is 2025, but it's on the 2026 calendar.
    assert df.loc["spa"]["on_current_calendar"] == 1
    # New circuit with no completed race still counts as current.
    madring = df.loc["madring"]
    assert madring["on_current_calendar"] == 1
    assert madring["race_count"] == 0
    assert pd.isna(madring["first_race"])
    assert df.loc["adelaide"]["on_current_calendar"] == 0


def test_history_reads_winners_archive(circuits_db):
    from queries.circuits import get_circuit_history
    history = get_circuit_history("spa")
    assert list(history["season"]) == [2025, 1995, 1950]
    assert history.iloc[1]["winner"] == "Michael Schumacher"
    assert history.iloc[1]["constructor"] == "Benetton"


class TestLoadRaceWinners:
    def _load(self, monkeypatch, payload):
        import data.loader as loader
        conn = _make_db()
        monkeypatch.setattr(loader, "fetch_race_winners", lambda year: payload)
        monkeypatch.setattr(loader.time, "sleep", lambda s: None)
        loader.load_race_winners(conn, 1950)
        return conn

    def test_inserts_winner_rows_and_circuits(self, monkeypatch):
        payload = [{
            "season": "1950", "round": "5", "raceName": "Belgian Grand Prix",
            "date": "1950-06-18",
            "Circuit": {
                "circuitId": "spa", "circuitName": "Circuit de Spa-Francorchamps",
                "Location": {"locality": "Spa", "country": "Belgium",
                             "lat": "50.4372", "long": "5.9714"},
            },
            "Results": [{
                "position": "1",
                "Driver": {"driverId": "fangio", "givenName": "Juan",
                           "familyName": "Fangio"},
                "Constructor": {"constructorId": "alfa", "name": "Alfa Romeo"},
            }],
        }]
        conn = self._load(monkeypatch, payload)
        row = conn.execute("SELECT * FROM circuit_race_winners").fetchone()
        assert (row["season"], row["round"], row["circuit_id"]) == (1950, 5, "spa")
        assert row["winner_name"] == "Juan Fangio"
        assert row["constructor_name"] == "Alfa Romeo"
        # The circuit itself is upserted so archive-only circuits appear too.
        assert conn.execute(
            "SELECT COUNT(*) FROM circuits WHERE circuit_id='spa'"
        ).fetchone()[0] == 1

    def test_race_without_results_is_skipped(self, monkeypatch):
        payload = [{
            "season": "1950", "round": "5", "raceName": "Belgian Grand Prix",
            "date": "1950-06-18",
            "Circuit": {"circuitId": "spa", "circuitName": "Spa",
                        "Location": {}},
            "Results": [],
        }]
        conn = self._load(monkeypatch, payload)
        assert conn.execute(
            "SELECT COUNT(*) FROM circuit_race_winners"
        ).fetchone()[0] == 0

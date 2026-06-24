"""Unit tests for the F1 live-timing client's pure parsing/shaping logic.

These functions parse the raw ``.jsonStream`` feed and are the most
regression-prone code in the live path — CLAUDE.md flags gap parsing and
stint-boundary math as repeatedly bitten. They're pure (no HTTP), so we pin
them directly; ``get_classification`` is exercised by monkeypatching the one
network call so the retired-driver reorder logic is covered without a feed.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data.f1_live_client as flc


class TestParseGap:
    def test_plus_seconds(self):
        assert flc._parse_gap("+1.234") == 1.234

    def test_bare_seconds(self):
        assert flc._parse_gap("5.0") == 5.0

    def test_empty_string_is_none(self):
        assert flc._parse_gap("") is None

    def test_none_is_none(self):
        assert flc._parse_gap(None) is None

    def test_unparseable_is_none(self):
        assert flc._parse_gap("garbage") is None

    def test_lap_down_variants_are_nan(self):
        # All the lapped-car spellings the feed uses must collapse to NaN so
        # downstream gap math (Time-to-Strike) treats them as "no comparable gap".
        for v in ("1L", "1 L", "LAP 1", "+2 LAPS"):
            assert math.isnan(flc._parse_gap(v)), v


class TestNormalizeStints:
    def test_list_becomes_index_keyed_dict(self):
        assert flc._normalize_stints([{"Compound": "SOFT"}]) == {"0": {"Compound": "SOFT"}}

    def test_dict_passthrough(self):
        d = {"0": {"Compound": "HARD"}}
        assert flc._normalize_stints(d) == d

    def test_list_skips_non_dicts_but_keeps_index(self):
        assert flc._normalize_stints(["junk", {"a": 1}]) == {"1": {"a": 1}}

    def test_other_is_empty(self):
        assert flc._normalize_stints(None) == {}


class TestStintBoundaries:
    def test_two_stints_with_running_last_stint(self):
        # Stint 0: 15 laps of wear (laps 1-15). Stint 1 is the current/last stint
        # and should extend to the driver's current lap, not its TotalLaps math.
        drv_stints = {
            "44": {
                "0": {"Compound": "SOFT", "StartLaps": 0, "TotalLaps": 15},
                "1": {"Compound": "HARD", "StartLaps": 0, "TotalLaps": 5},
            }
        }
        cur_laps = {"44": 44}
        b = flc._stint_boundaries(drv_stints, cur_laps)["44"]

        assert b[0] == {"stint": 0, "compound": "SOFT",
                        "lap_start": 1, "lap_end": 15, "start_laps": 0}
        assert b[1]["lap_start"] == 16
        # computed end = 16 + 5 - 1 = 20, but the current lap (44) is later, so
        # an in-progress final stint extends to the current lap.
        assert b[1]["lap_end"] == 44

    def test_used_tyre_start_laps_offsets_length(self):
        # A stint started on tyres with 3 laps already on them: 10 total wear
        # means only 7 laps run in this stint.
        drv_stints = {"1": {"0": {"Compound": "MEDIUM", "StartLaps": 3, "TotalLaps": 10}}}
        b = flc._stint_boundaries(drv_stints, {"1": 7})["1"]
        assert b[0]["start_laps"] == 3
        assert b[0]["lap_start"] == 1


def _timing(lines):
    """One TimingData stream entry wrapping a {driver: state} dict."""
    return [("2026-06-21T13:00:00.0Z", {"Lines": lines})]


class TestGetClassification:
    def test_retired_cars_sorted_to_back(self, monkeypatch):
        # #16 holds a stale Position 2 (it was running 2nd when it stopped) — the
        # whole point of get_classification is that it must NOT stay ahead of the
        # cars still circulating.
        timing = _timing({
            "44": {"Position": "1", "NumberOfLaps": 10},
            "63": {"Position": "2", "NumberOfLaps": 10},
            "16": {"Position": "2", "NumberOfLaps": 5, "Retired": True},
        })
        monkeypatch.setattr(flc, "_fetch_stream", lambda key, topic: timing)

        df = flc.get_classification("2026|Spain|R").set_index("driver_number")
        assert df.loc[44, "position"] == 1
        assert df.loc[63, "position"] == 2
        assert df.loc[16, "position"] == 3
        assert bool(df.loc[16, "retired"]) is True
        assert df.loc[16, "status"] == "Retired"
        assert df.loc[44, "status"] == "Running"

    def test_retired_cars_ordered_among_themselves_by_laps(self, monkeypatch):
        timing = _timing({
            "44": {"Position": "1", "NumberOfLaps": 20},
            "16": {"Position": "5", "NumberOfLaps": 5, "Retired": True},
            "5": {"Position": "6", "NumberOfLaps": 8, "Stopped": True},
        })
        monkeypatch.setattr(flc, "_fetch_stream", lambda key, topic: timing)

        df = flc.get_classification("2026|Spain|R").set_index("driver_number")
        # Running car first; then the retiree that completed more laps (#5, 8 laps)
        # ahead of the one that completed fewer (#16, 5 laps).
        assert df.loc[44, "position"] == 1
        assert df.loc[5, "position"] == 2
        assert df.loc[16, "position"] == 3

    def test_empty_feed_returns_empty_frame(self, monkeypatch):
        monkeypatch.setattr(flc, "_fetch_stream", lambda key, topic: [])
        df = flc.get_classification("2026|Spain|R")
        assert df.empty
        assert list(df.columns) == ["driver_number", "position", "status", "retired"]

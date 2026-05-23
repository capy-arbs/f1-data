"""Tests for queries/strike.py — the Time-to-Strike math.

These tests focus on the pure helpers (_laps_to_catch, _pace_and_deg,
_clean_laps, _gap_between) because that's where a silent regression
would produce wrong race-time predictions without anything visibly
crashing. The orchestrator (compute_strike) gets coverage through
those helpers plus one end-to-end smoke test.

Run from the repo root: `pytest tests/` (system pytest works; pytest
isn't in requirements.txt because it's a dev-only dependency).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable so `from queries.strike import ...` works
# whether pytest is run from the repo root or the tests/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

from queries.strike import (
    StrikeResult,
    _clean_laps,
    _gap_between,
    _laps_to_catch,
    _pace_and_deg,
    compute_strike,
)


# -- Fixtures helpers -------------------------------------------------

def _laps_frame(driver, durations, pit_out=None):
    """Build a minimal laps DataFrame for one driver."""
    pit_out = pit_out or {}
    rows = [
        {
            "driver_number": driver,
            "lap_number": i,
            "lap_duration": d,
            "is_pit_out_lap": pit_out.get(i, False),
        }
        for i, d in enumerate(durations, start=1)
    ]
    return pd.DataFrame(rows)


def _intervals_frame(rows):
    """Build a minimal intervals DataFrame from (driver, gap, date) tuples."""
    return pd.DataFrame(rows, columns=["driver_number", "gap_to_leader", "date"])


# -- _laps_to_catch ---------------------------------------------------

class TestLapsToCatch:
    def test_flat_pace_collapses_to_ceil_formula(self):
        # 5.0s gap, target 0.5s/lap slower -> ceil(5/0.5) = 10 laps
        assert _laps_to_catch(
            gap=5.0, chaser_pace=80.0, target_pace=80.5,
            chaser_deg=0.0, target_deg=0.0,
        ) == 10

    def test_one_lap_when_pace_advantage_covers_gap(self):
        # 0.5s gap, 0.5s/lap advantage -> closes on lap 1
        assert _laps_to_catch(
            gap=0.5, chaser_pace=80.0, target_pace=80.5,
            chaser_deg=0.0, target_deg=0.0,
        ) == 1

    def test_chaser_slower_than_target_returns_none(self):
        # Pace delta is negative — cumulative advantage never grows, can't close
        assert _laps_to_catch(
            gap=5.0, chaser_pace=81.0, target_pace=80.0,
            chaser_deg=0.0, target_deg=0.0,
        ) is None

    def test_exceeds_max_laps_returns_none(self):
        # 100s gap at 0.5s/lap = 200 laps, but max_laps=80
        assert _laps_to_catch(
            gap=100.0, chaser_pace=80.0, target_pace=80.5,
            chaser_deg=0.0, target_deg=0.0, max_laps=80,
        ) is None

    def test_target_degrading_faster_closes_sooner(self):
        # 10s gap, 0.2s/lap base advantage. Target degrading 0.05s/lap faster
        # should reduce the catch by at least a few laps.
        flat = _laps_to_catch(
            gap=10.0, chaser_pace=80.0, target_pace=80.2,
            chaser_deg=0.0, target_deg=0.0,
        )
        with_deg = _laps_to_catch(
            gap=10.0, chaser_pace=80.0, target_pace=80.2,
            chaser_deg=0.0, target_deg=0.05,
        )
        assert flat is not None and with_deg is not None
        assert with_deg < flat

    def test_chaser_degrading_faster_extends_or_blocks_catch(self):
        # If the chaser is faster now but degrades harder than the target,
        # the catch should take longer than the flat case (or never happen).
        flat = _laps_to_catch(
            gap=5.0, chaser_pace=80.0, target_pace=80.5,
            chaser_deg=0.0, target_deg=0.0,
        )
        chaser_falling = _laps_to_catch(
            gap=5.0, chaser_pace=80.0, target_pace=80.5,
            chaser_deg=0.05, target_deg=0.0,
        )
        if chaser_falling is None:
            return  # Acceptable — chaser fell off enough that it can't close
        assert chaser_falling >= flat


# -- _clean_laps ------------------------------------------------------

class TestCleanLaps:
    def test_drops_pit_out_laps(self):
        df = _laps_frame(1, [80, 79, 95, 79, 80], pit_out={3: True})
        cleaned = _clean_laps(df, driver_number=1, window=5)
        assert 95 not in cleaned["lap_duration"].values

    def test_drops_outlier_slow_laps(self):
        # Median of [80, 79, 81, 90, 80, 79] sorted = 79.5. Outlier cutoff
        # is median * 1.05 ≈ 83.5. The 90 should drop; the 81 should stay.
        df = _laps_frame(1, [80, 79, 81, 90, 80, 79])
        cleaned = _clean_laps(df, driver_number=1, window=5)
        assert 90 not in cleaned["lap_duration"].values
        assert 81 in cleaned["lap_duration"].values

    def test_returns_at_most_window_rows(self):
        df = _laps_frame(1, [80] * 20)
        cleaned = _clean_laps(df, driver_number=1, window=5)
        assert len(cleaned) <= 5

    def test_empty_input_returns_empty(self):
        df = pd.DataFrame(columns=["driver_number", "lap_number", "lap_duration"])
        assert _clean_laps(df, driver_number=1).empty

    def test_filters_to_requested_driver(self):
        df = pd.concat([
            _laps_frame(1, [80, 79, 80]),
            _laps_frame(2, [70, 69, 70]),
        ], ignore_index=True)
        cleaned = _clean_laps(df, driver_number=1)
        assert (cleaned["driver_number"] == 1).all()


# -- _pace_and_deg ----------------------------------------------------

class TestPaceAndDeg:
    def test_too_few_clean_laps_returns_none(self):
        df = _laps_frame(1, [80])
        pace, slope = _pace_and_deg(df, driver_number=1, current_lap=1)
        assert pace is None and slope is None

    def test_two_clean_laps_returns_mean_and_zero_slope(self):
        # 2 clean laps -> not enough to fit, return (mean, 0.0)
        df = _laps_frame(1, [80.0, 80.5])
        pace, slope = _pace_and_deg(df, driver_number=1, current_lap=2)
        assert pace == pytest.approx(80.25)
        assert slope == 0.0

    def test_three_or_more_clean_laps_fits_a_line(self):
        # Perfect linear ramp: lap 1=80, 2=80.5, 3=81. Slope must be 0.5.
        df = _laps_frame(1, [80.0, 80.5, 81.0])
        pace, slope = _pace_and_deg(df, driver_number=1, current_lap=3)
        assert slope == pytest.approx(0.5, abs=1e-6)
        assert pace == pytest.approx(81.0, abs=1e-6)

    def test_fit_projects_future_lap_pace(self):
        # Linear fit on (1, 80.0), (2, 80.5), (3, 81.0): slope=0.5, intercept=79.5
        # At lap 5 the line projects to 79.5 + 0.5*5 = 82.0
        df = _laps_frame(1, [80.0, 80.5, 81.0])
        pace, _ = _pace_and_deg(df, driver_number=1, current_lap=5)
        assert pace == pytest.approx(82.0, abs=1e-6)


# -- _gap_between -----------------------------------------------------

class TestGapBetween:
    def test_positive_when_chaser_further_back(self):
        df = _intervals_frame([
            (1, 2.0, "2026-05-22T13:00:00"),   # target, closer to leader
            (4, 5.5, "2026-05-22T13:00:00"),   # chaser, further back
        ])
        # Chaser is 3.5s further from the leader than target -> 3.5s gap.
        assert _gap_between(df, chaser=4, target=1) == pytest.approx(3.5)

    def test_returns_none_when_either_driver_missing(self):
        df = _intervals_frame([(1, 2.0, "2026-05-22T13:00:00")])
        assert _gap_between(df, chaser=4, target=1) is None

    def test_returns_none_when_either_gap_is_nan(self):
        # Lapped cars come back as NaN — should bail rather than crash.
        df = _intervals_frame([
            (1, 2.0, "2026-05-22T13:00:00"),
            (4, float("nan"), "2026-05-22T13:00:00"),
        ])
        assert _gap_between(df, chaser=4, target=1) is None

    def test_uses_latest_snapshot_per_driver(self):
        df = _intervals_frame([
            (1, 2.0, "2026-05-22T13:00:00"),
            (1, 1.5, "2026-05-22T13:00:30"),   # newer snapshot for driver 1
            (4, 5.0, "2026-05-22T13:00:30"),
        ])
        # With newer values: chaser 5.0 - target 1.5 = 3.5
        assert _gap_between(df, chaser=4, target=1) == pytest.approx(3.5)

    def test_empty_frame_returns_none(self):
        assert _gap_between(pd.DataFrame(), chaser=1, target=4) is None


# -- compute_strike: end-to-end smoke --------------------------------

def test_compute_strike_returns_cant_close_when_chaser_is_slower():
    """End-to-end: chaser slower than target -> 'can't close' verdict."""
    intervals = _intervals_frame([
        (1, 0.0, "2026-05-22T13:00:00"),
        (4, 3.0, "2026-05-22T13:00:00"),
    ])
    # Driver 4 (chaser) is genuinely slower than driver 1 (target).
    chaser_laps = _laps_frame(4, [81.0, 81.1, 81.0, 81.2, 81.0])
    target_laps = _laps_frame(1, [80.0, 80.1, 80.0, 80.1, 80.0])
    laps = pd.concat([chaser_laps, target_laps], ignore_index=True)
    stints = pd.DataFrame(
        columns=["driver_number", "stint_number", "lap_start",
                 "tyre_age_at_start", "compound"]
    )
    drivers = pd.DataFrame(columns=["driver_number", "name_acronym"])

    result = compute_strike(
        chaser_number=4, target_number=1,
        intervals_df=intervals, laps_df=laps,
        stints_df=stints, drivers_df=drivers,
    )

    assert isinstance(result, StrikeResult)
    assert result.laps_to_catch is None
    assert "can't close" in result.verdict.lower()

"""Tests for the What-If simulation transforms.

The cascade-insertion logic (apply_overrides) is the most intricate compute in
the app and used to live inline in the page where it couldn't be tested. These
pin its position-shuffling and points-recompute behaviour, plus the simpler
driver-swap / points-system / rank-diff helpers.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from config import POINT_SYSTEMS
from queries.what_if import (
    apply_driver_swap,
    apply_overrides,
    apply_points_system,
    calculate_standings,
    standings_rank_changes,
)

PTS = POINT_SYSTEMS["2010-present"]


def _race(round_num, ordering, dnfs=()):
    """Build a per-race results frame. ``ordering`` is driver_ids P1..Pn;
    ``dnfs`` are driver_ids with no position."""
    rows = []
    for pos, did in enumerate(ordering, start=1):
        rows.append({"round": round_num, "race_name": f"R{round_num}", "driver_id": did,
                     "driver_name": did.upper(), "code": did.upper(), "position": pos,
                     "points": 0.0, "grid": pos, "constructor": "team"})
    for did in dnfs:
        rows.append({"round": round_num, "race_name": f"R{round_num}", "driver_id": did,
                     "driver_name": did.upper(), "code": did.upper(), "position": None,
                     "points": 0.0, "grid": 20, "constructor": "team"})
    return pd.DataFrame(rows)


def _pos_by_driver(df, round_num=1):
    r = df[df["round"] == round_num]
    return {row["driver_id"]: (None if pd.isna(row["position"]) else int(row["position"]))
            for _, row in r.iterrows()}


class TestApplyPointsSystem:
    def test_positions_map_to_points_dnf_zero(self):
        df = _race(1, ["a", "b"], dnfs=["c"])
        out = apply_points_system(df, PTS)
        pts = dict(zip(out["driver_id"], out["points"]))
        assert pts["a"] == 25.0
        assert pts["b"] == 18.0
        assert pts["c"] == 0.0

    def test_does_not_mutate_input(self):
        df = _race(1, ["a", "b"])
        before = df["points"].tolist()
        apply_points_system(df, PTS)
        assert df["points"].tolist() == before


class TestApplyOverrides:
    def test_dnf_promoted_to_p3_cascades_down(self):
        # E was DNF; promote to P3 → C,D shift down one, A/B unchanged.
        df = _race(1, ["a", "b", "c", "d"], dnfs=["e"])
        out = apply_overrides(
            df, [{"round": 1, "driver_id": "e", "orig_pos": None, "new_pos": 3}], PTS
        )
        assert _pos_by_driver(out) == {"a": 1, "b": 2, "e": 3, "c": 4, "d": 5}
        # Points recomputed under the system.
        pts = dict(zip(out["driver_id"], out["points"]))
        assert pts["e"] == 15.0 and pts["c"] == 12.0 and pts["d"] == 10.0

    def test_winner_to_dnf_promotes_everyone(self):
        df = _race(1, ["a", "b", "c", "d"], dnfs=["e"])
        out = apply_overrides(
            df, [{"round": 1, "driver_id": "a", "orig_pos": 1, "new_pos": None}], PTS
        )
        assert _pos_by_driver(out) == {"b": 1, "c": 2, "d": 3, "a": None, "e": None}

    def test_midfield_move_up_reshuffles_between(self):
        # C from P3 to P1: D fills the vacated P3 slot, then A,B,D push down.
        df = _race(1, ["a", "b", "c", "d"])
        out = apply_overrides(
            df, [{"round": 1, "driver_id": "c", "orig_pos": 3, "new_pos": 1}], PTS
        )
        assert _pos_by_driver(out) == {"c": 1, "a": 2, "b": 3, "d": 4}

    def test_override_on_missing_round_is_noop(self):
        df = _race(1, ["a", "b"])
        out = apply_overrides(
            df, [{"round": 99, "driver_id": "a", "orig_pos": 1, "new_pos": 2}], PTS
        )
        assert _pos_by_driver(out) == {"a": 1, "b": 2}

    def test_stacked_overrides_compound(self):
        df = _race(1, ["a", "b", "c"], dnfs=["d"])
        out = apply_overrides(df, [
            {"round": 1, "driver_id": "d", "orig_pos": None, "new_pos": 1},
            {"round": 1, "driver_id": "c", "orig_pos": 4, "new_pos": 2},
        ], PTS)
        # d wins (everyone down one), then c (now P4) jumps to P2.
        assert _pos_by_driver(out) == {"d": 1, "c": 2, "a": 3, "b": 4}


class TestApplyDriverSwap:
    def test_transplant_is_asymmetric(self):
        df = pd.concat([_race(1, ["a", "b"]), _race(2, ["b", "a"])], ignore_index=True)
        df = apply_points_system(df, PTS)
        out = apply_driver_swap(df, "a", "b")
        # a now gets b's positions each round; b keeps its own.
        assert _pos_by_driver(out, 1)["a"] == 2  # b was P2 in R1
        assert _pos_by_driver(out, 2)["a"] == 1  # b was P1 in R2
        assert _pos_by_driver(out, 1)["b"] == 2
        assert _pos_by_driver(out, 2)["b"] == 1

    def test_same_driver_is_noop_copy(self):
        df = apply_points_system(_race(1, ["a", "b"]), PTS)
        out = apply_driver_swap(df, "a", "a")
        assert out.equals(df)


class TestStandingsRankChanges:
    def test_reports_only_movers_sorted_by_change(self):
        before = calculate_standings(apply_points_system(_race(1, ["a", "b", "c"]), PTS))
        # Flip a and c so both move; b stays.
        after = calculate_standings(apply_points_system(_race(1, ["c", "b", "a"]), PTS))
        ch = standings_rank_changes(before, after)
        movers = dict(zip(ch["Driver"], ch["Change"]))
        assert movers == {"C": 2, "A": -2}
        assert "B" not in movers
        # Sorted descending by Change.
        assert ch["Change"].tolist() == sorted(ch["Change"].tolist(), reverse=True)

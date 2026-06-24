"""Tests for the Sprint Analysis compute helper (pure, no DB)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from queries.sprint import sprint_vs_race_summary


def _cmp(rows):
    return pd.DataFrame(rows, columns=["driver", "code", "sprint_pos", "race_pos"])


def test_empty_input_returns_empty_with_schema():
    out = sprint_vs_race_summary(_cmp([]))
    assert out.empty
    assert list(out.columns) == ["driver", "code", "avg_sprint", "avg_race", "diff"]


def test_rows_missing_either_position_are_dropped():
    out = sprint_vs_race_summary(_cmp([
        {"driver": "A", "code": "A", "sprint_pos": 2, "race_pos": None},
        {"driver": "A", "code": "A", "sprint_pos": None, "race_pos": 5},
    ]))
    assert out.empty


def test_diff_is_race_minus_sprint_and_sorted_desc():
    out = sprint_vs_race_summary(_cmp([
        # B finishes much better in sprints (race P10, sprint P2 -> +8).
        {"driver": "B", "code": "B", "sprint_pos": 2, "race_pos": 10},
        # C finishes worse in sprints (race P3, sprint P6 -> -3).
        {"driver": "C", "code": "C", "sprint_pos": 6, "race_pos": 3},
    ]))
    diffs = dict(zip(out["code"], out["diff"]))
    assert diffs["B"] == 8
    assert diffs["C"] == -3
    # Sorted by diff descending: B before C.
    assert out["code"].tolist() == ["B", "C"]

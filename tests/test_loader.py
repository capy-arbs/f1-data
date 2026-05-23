"""Tests for data/loader.py helpers.

Covers _parse_pit_duration because it handles two genuinely different
input formats (seconds "22.630" and M:SS.mmm "18:01.553") plus the
malformed edge cases that Jolpica occasionally emits.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from data.loader import _parse_pit_duration


class TestParsePitDuration:
    def test_normal_seconds_string(self):
        assert _parse_pit_duration("22.630") == pytest.approx(22.63)

    def test_minutes_seconds_string(self):
        # Long red-flag / repair stops come back as M:SS.mmm.
        assert _parse_pit_duration("18:01.553") == pytest.approx(1081.553, abs=1e-3)

    def test_integer_seconds_string(self):
        assert _parse_pit_duration("3") == 3.0

    def test_strips_whitespace(self):
        assert _parse_pit_duration("  22.630  ") == pytest.approx(22.63)

    def test_none_returns_none(self):
        assert _parse_pit_duration(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_pit_duration("") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_pit_duration("   ") is None

    def test_unparseable_garbage_returns_none(self):
        assert _parse_pit_duration("not-a-number") is None

    def test_malformed_minutes_returns_none(self):
        # "1:2:3" — split(":", 1) → ("1", "2:3"); float("2:3") raises.
        assert _parse_pit_duration("1:2:3") is None

    def test_minute_part_must_be_int(self):
        # "abc:30.5" — int("abc") raises → None.
        assert _parse_pit_duration("abc:30.5") is None

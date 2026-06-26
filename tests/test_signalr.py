"""Unit tests for the SignalR live-timing path.

F1's static ``.jsonStream`` archive isn't published until a session finishes
archiving, so genuinely-live data comes from the SignalR Core websocket
(``data/f1_signalr.py``). These tests cover the record parsing and the replay
through ``data/f1_live_client.py``'s existing shaping functions, pinned against
a real captured sample of Austrian GP 2026 Practice 2 (no network, no threads).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data.f1_live_client as flc
import data.f1_signalr as sg

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "signalr_p2_sample.txt"


class TestParseLine:
    def test_snapshot_line_json_string_payload(self):
        # Initial-state records carry the payload as a JSON *string*.
        line = "['Heartbeat', '{\"Utc\": \"2026-06-26T15:14:51Z\", \"_kf\": true}', '']"
        topic, ts, data = sg._parse_line(line)
        assert topic == "Heartbeat"
        assert ts == ""
        assert data == {"Utc": "2026-06-26T15:14:51Z", "_kf": True}

    def test_delta_line_dict_payload(self):
        # Feed deltas carry the payload as an already-parsed dict + ISO ts.
        line = "['TimingData', {'Lines': {'1': {'NumberOfLaps': 7}}}, '2026-06-26T15:15:00.5Z']"
        topic, ts, data = sg._parse_line(line)
        assert topic == "TimingData"
        assert ts == "2026-06-26T15:15:00.5Z"
        assert data == {"Lines": {"1": {"NumberOfLaps": 7}}}

    def test_blank_and_partial_lines_are_none(self):
        assert sg._parse_line("") is None
        assert sg._parse_line("   ") is None
        # A truncated last line (recorder mid-write) must not raise.
        assert sg._parse_line("['TimingData', {'Lines': {'1': {'Num") is None

    def test_non_list_record_is_none(self):
        assert sg._parse_line("{'not': 'a list'}") is None

    def test_unparseable_payload_is_none(self):
        assert sg._parse_line("['Heartbeat', '{not valid json', '']") is None


class TestReadEntries:
    def test_filters_to_requested_topic(self):
        td = sg._read_entries(str(FIXTURE), "TimingData")
        wx = sg._read_entries(str(FIXTURE), "WeatherData")
        assert len(td) > len(wx) > 0
        # Every returned entry is a (ts, dict) pair.
        for ts, data in td:
            assert isinstance(ts, str)
            assert isinstance(data, dict)

    def test_unknown_topic_is_empty(self):
        assert sg._read_entries(str(FIXTURE), "DefinitelyNotATopic") == []


class TestTopicEntriesFreshness:
    def test_missing_file_no_recorder_returns_none(self, tmp_path, monkeypatch):
        # No file and no active recorder -> defer to the static archive.
        monkeypatch.setattr(sg, "_RECORDING_DIR", str(tmp_path))
        monkeypatch.setattr(sg, "is_recording", lambda key: False)
        assert sg.topic_entries("2026|Nowhere|R", "TimingData.jsonStream") is None

    def test_missing_file_while_recorder_warming_up_returns_empty(self, tmp_path, monkeypatch):
        # Recorder just started but hasn't opened the file yet -> [] (live but
        # empty), so the caller doesn't hit the static archive's mid-session 403.
        monkeypatch.setattr(sg, "_RECORDING_DIR", str(tmp_path))
        monkeypatch.setattr(sg, "is_recording", lambda key: True)
        assert sg.topic_entries("2026|Nowhere|R", "TimingData.jsonStream") == []

    def test_fresh_file_is_read(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sg, "_RECORDING_DIR", str(tmp_path))
        key = "2026|Austrian Grand Prix|Practice 2"
        dst = Path(sg._recording_path(key))
        dst.write_text(FIXTURE.read_text())
        ents = sg.topic_entries(key, "TimingData.jsonStream")
        assert ents is not None and len(ents) > 0

    def test_stale_file_returns_none(self, tmp_path, monkeypatch):
        # A leftover recording from an ended session must defer to the static
        # archive instead of replaying partial live data.
        monkeypatch.setattr(sg, "_RECORDING_DIR", str(tmp_path))
        monkeypatch.setattr(sg, "_STALE_AFTER_S", -1)  # force "stale"
        key = "2026|Austrian Grand Prix|Practice 2"
        Path(sg._recording_path(key)).write_text(FIXTURE.read_text())
        assert sg.topic_entries(key, "TimingData.jsonStream") is None


class TestParseTsIso:
    def test_iso_timestamp_absolute(self):
        # SignalR stamps absolute ISO times; session_start is irrelevant.
        ts = flc._parse_ts("2026-06-26T15:15:01.298Z", None)
        assert ts.year == 2026 and ts.hour == 15 and ts.minute == 15
        assert ts.tzinfo is None  # normalised to naive UTC

    def test_relative_timestamp_still_works(self):
        import pandas as pd
        start = pd.Timestamp("2026-06-26 15:00:00")
        ts = flc._parse_ts("00:05:30.000", start)
        assert ts == pd.Timestamp("2026-06-26 15:05:30")

    def test_empty_is_nat(self):
        import pandas as pd
        assert flc._parse_ts("", None) is pd.NaT


class TestNormalizeTimingLine:
    def test_sectors_list_becomes_index_dict(self):
        upd = {"Sectors": [{"Value": "17.1"}, {"Value": "52.7"}, {"Value": "40.4"}]}
        out = flc._normalize_timing_line(upd)
        assert out["Sectors"] == {"0": {"Value": "17.1"},
                                  "1": {"Value": "52.7"},
                                  "2": {"Value": "40.4"}}

    def test_sectors_dict_passthrough(self):
        upd = {"Sectors": {"2": {"Value": "40.4"}}}
        assert flc._normalize_timing_line(upd)["Sectors"] == {"2": {"Value": "40.4"}}

    def test_does_not_mutate_source(self):
        upd = {"Sectors": [{"Value": "17.1"}], "NumberOfLaps": 5}
        flc._normalize_timing_line(upd)
        assert isinstance(upd["Sectors"], list)  # original untouched


def _patch_fixture(monkeypatch):
    """Route the live-client parsers at the captured fixture, no network."""
    monkeypatch.setattr(
        flc, "_fetch_stream",
        lambda key, topic: sg._read_entries(str(FIXTURE), topic.split(".")[0]),
    )
    monkeypatch.setattr(flc, "_get_session_info", lambda key: (None, None))


class TestReplayThroughParsers:
    def test_drivers(self, monkeypatch):
        _patch_fixture(monkeypatch)
        df = flc.get_drivers("2026|Austrian Grand Prix|Practice 2")
        assert len(df) == 22
        nor = df[df["driver_number"] == 1].iloc[0]
        assert nor["name_acronym"] == "NOR"
        assert nor["team_name"] == "McLaren"

    def test_classification_orders_by_position(self, monkeypatch):
        _patch_fixture(monkeypatch)
        df = flc.get_classification("2026|Austrian Grand Prix|Practice 2")
        assert len(df) == 22
        assert df.iloc[0]["position"] == 1
        # Positions are a dense 1..N ranking.
        assert list(df["position"]) == list(range(1, 23))

    def test_laps_have_sector_times(self, monkeypatch):
        _patch_fixture(monkeypatch)
        laps = flc.get_laps("2026|Austrian Grand Prix|Practice 2")
        assert not laps.empty
        # Car 3 completed a lap 5 with three real sector times in the sample.
        row = laps[(laps["driver_number"] == 3) & (laps["lap_number"] == 5)].iloc[0]
        assert math.isclose(row["duration_sector_1"], 17.120, abs_tol=0.01)
        assert math.isclose(row["lap_duration"], 110.359, abs_tol=0.01)
        assert row["compound"] == "MEDIUM"

    def test_weather_parsed(self, monkeypatch):
        _patch_fixture(monkeypatch)
        w = flc.get_weather("2026|Austrian Grand Prix|Practice 2")
        assert not w.empty
        assert 25 <= w["air_temperature"].iloc[0] <= 45
        assert w["track_temperature"].iloc[0] > w["air_temperature"].iloc[0]

    def test_intervals_leader_zero(self, monkeypatch):
        _patch_fixture(monkeypatch)
        iv = flc.get_intervals("2026|Austrian Grand Prix|Practice 2")
        assert not iv.empty
        # The session leader's gap_to_leader is 0.
        assert (iv["gap_to_leader"] == 0.0).any()

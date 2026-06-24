"""Tests for data/fetcher.py — the Jolpica pagination logic.

Focus on the bug that bit on 2026-05-07: Jolpica silently caps page size
at 100 regardless of the requested limit, and we used to advance `offset`
by the requested limit instead of the served limit, exiting after one page
and silently dropping rows. These tests guard against regressing into that
shape.

Run from repo root: pytest tests/
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from data import fetcher


class _StubResponse:
    """Minimal Response stand-in for monkeypatching requests.get."""

    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _page(total, served_limit, items):
    """Build a Jolpica-shaped page response."""
    return {
        "MRData": {
            "total": str(total),
            "limit": str(served_limit),
            "RaceTable": {
                "Races": items,
            },
        }
    }


def test_clamps_requested_limit_to_100(monkeypatch):
    """Even when we ask for limit=1000, the URL we hit should request 100."""
    requested_urls = []

    def fake_get(url, timeout=None):
        requested_urls.append(url)
        return _StubResponse(_page(total=1, served_limit=100, items=[{"id": "x"}]))

    monkeypatch.setattr(fetcher.requests, "get", fake_get)
    monkeypatch.setattr(fetcher.time, "sleep", lambda _: None)

    fetcher._get("races", limit=1000)

    assert "limit=100" in requested_urls[0]


def test_advances_offset_by_served_limit_not_requested(monkeypatch):
    """3 pages of 100 records with total=250 must produce all 250 rows.

    Regression: if offset advances by requested-limit instead of served-limit,
    pagination exits after one page (offset 1000 >= total 250) and silently
    drops 150 rows.
    """
    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        if "offset=0" in url:
            items = [{"i": i} for i in range(100)]
        elif "offset=100" in url:
            items = [{"i": i + 100} for i in range(100)]
        elif "offset=200" in url:
            items = [{"i": i + 200} for i in range(50)]
        else:
            raise AssertionError(f"unexpected offset in {url}")
        return _StubResponse(_page(total=250, served_limit=100, items=items))

    monkeypatch.setattr(fetcher.requests, "get", fake_get)
    monkeypatch.setattr(fetcher.time, "sleep", lambda _: None)

    result = fetcher._get("races", limit=1000)

    assert len(result) == 250
    assert len(calls) == 3
    assert any("offset=0" in u for u in calls)
    assert any("offset=100" in u for u in calls)
    assert any("offset=200" in u for u in calls)


def test_single_page_when_total_fits_in_one_request(monkeypatch):
    def fake_get(url, timeout=None):
        return _StubResponse(_page(total=5, served_limit=100,
                                    items=[{"i": i} for i in range(5)]))

    monkeypatch.setattr(fetcher.requests, "get", fake_get)
    monkeypatch.setattr(fetcher.time, "sleep", lambda _: None)

    result = fetcher._get("races", limit=100)
    assert len(result) == 5


def test_429_retry_then_success(monkeypatch):
    """A 429 with Retry-After should sleep then retry the same offset."""
    call_count = {"n": 0}
    sleeps = []

    def fake_get(url, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _StubResponse({}, status_code=429,
                                  headers={"Retry-After": "0.01"})
        return _StubResponse(_page(total=1, served_limit=100, items=[{"i": 1}]))

    monkeypatch.setattr(fetcher.requests, "get", fake_get)
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: sleeps.append(s))

    result = fetcher._get("races")

    assert call_count["n"] == 2
    assert len(result) == 1
    # The 0.01s Retry-After should have shown up in sleeps.
    assert 0.01 in sleeps


def test_falls_back_to_default_backoff_when_no_retry_after_header(monkeypatch):
    call_count = {"n": 0}
    sleeps = []

    def fake_get(url, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _StubResponse({}, status_code=429, headers={})
        return _StubResponse(_page(total=1, served_limit=100, items=[{"i": 1}]))

    monkeypatch.setattr(fetcher.requests, "get", fake_get)
    monkeypatch.setattr(fetcher.time, "sleep", lambda s: sleeps.append(s))

    fetcher._get("races")

    # Default backoff is 2.0s per the code.
    assert 2.0 in sleeps

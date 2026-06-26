"""Genuinely-live F1 timing via the SignalR Core websocket feed.

F1's static ``.jsonStream`` archive files (polled by ``data/f1_live_client.py``)
are **not written until a session finishes archiving** — during a live session
``SessionInfo.json`` reports ``ArchiveStatus: "Generating"`` and every data
topic returns HTTP 403 (the S3 object key doesn't exist yet). So static-file
polling can only ever serve *replay* of a completed session, never live data.

The genuinely-live feed is the SignalR Core websocket at
``wss://livetiming.formula1.com/signalrcore`` — the same stream the broadcast
graphics use. FastF1 ships a client for it but (a) defaults to requiring an
F1TV subscription token and (b) its ``no_auth=True`` path is broken in 3.8.3:
it passes ``access_token_factory=None`` where signalrcore requires a callable,
raising ``TypeError: access_token_factory is not function``. We subclass it to
connect with an empty-string token factory, which the core timing topics
(TimingData, DriverList, TimingAppData, WeatherData, ...) accept without auth.

**Streamlit integration.** A websocket can't live inside a single stateless
Streamlit rerun, so a process-singleton background thread streams the feed to a
local file and each rerun reads + replays that file. The recorded format
matches FastF1's ``SignalRClient`` output — one ``[topic, payload, ts]``
Python-repr record per line — so ``topic_entries`` can reshape it into the
``(timestamp, delta)`` pairs that ``data/f1_live_client.py``'s parsers already
consume. The recorder is the live source; the static archive remains the
post-session fallback.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import tempfile
import threading
import time as _time

import requests
from fastf1.livetiming.client import SignalRClient
from signalrcore.hub_connection_builder import HubConnectionBuilder

logger = logging.getLogger(__name__)

# Self-terminate after this many seconds with no message, so a recorder doesn't
# linger forever once a session ends (or during a long red-flag lull). Within
# the live window a page rerun calls ``ensure_recording`` again and revives it.
_IDLE_TIMEOUT_S = int(os.environ.get("F1_LIVE_IDLE_TIMEOUT", "120"))
# A live feed touches the file every few seconds (heartbeats + timing). If the
# recording hasn't been written to in this long, the session is over (or the
# recorder died) and the per-session file left behind in temp is stale — callers
# should fall back to the now-complete static archive rather than replay it.
_STALE_AFTER_S = _IDLE_TIMEOUT_S + 60
_RECORDING_DIR = os.environ.get(
    "F1_LIVE_RECORDING_DIR", os.path.join(tempfile.gettempdir(), "f1_live")
)

_LOCK = threading.Lock()
_RECORDERS: dict[str, _Recorder] = {}


class FreeSignalRClient(SignalRClient):
    """FastF1's ``SignalRClient`` with the broken ``no_auth`` path fixed.

    signalrcore requires ``access_token_factory`` to be callable; FastF1 passes
    ``None`` when ``no_auth=True``, which raises ``TypeError`` before the socket
    even opens. We pass a lambda returning an empty string instead — the core
    timing topics stream without a valid F1TV token.
    """

    def _run(self):
        self._output_file = open(self.filename, self.filemode)

        # Pre-negotiate for the AWSALBCORS load-balancer cookie (same as FastF1).
        r = requests.options(self._negotiate_url, headers=self.headers)
        try:
            self.headers.update({"Cookie": f"AWSALBCORS={r.cookies['AWSALBCORS']}"})
        except KeyError:
            logger.warning("No AWSALBCORS cookie returned by negotiate")

        options = {
            "verify_ssl": True,
            "access_token_factory": lambda: "",
            "headers": self.headers,
        }
        self._connection = (
            HubConnectionBuilder()
            .with_url(self._connection_url, options=options)
            .configure_logging(logging.WARNING)
            .build()
        )
        self._connection.on_open(self._on_connect)
        self._connection.on_close(self._on_close)
        self._connection.on("feed", self._on_message)
        self._connection.start()

        while not self._is_connected:
            _time.sleep(0.1)

        self._connection.send(
            "Subscribe", [self.topics], on_invocation=self._on_message
        )


class _Recorder:
    def __init__(self, session_key: str, filepath: str):
        self.session_key = session_key
        self.filepath = filepath
        self._client = FreeSignalRClient(
            filename=filepath, filemode="w", timeout=_IDLE_TIMEOUT_S
        )
        self._thread = threading.Thread(
            target=self._run, name=f"f1-signalr-{session_key}", daemon=True
        )

    def start(self):
        self._thread.start()

    def _run(self):
        try:
            self._client.start()
        except Exception:
            logger.exception("SignalR recorder for %s crashed", self.session_key)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()


# -- Recorder lifecycle ----------------------------------------------------

def _recording_path(session_key: str) -> str:
    safe = "".join(c if c.isalnum() else "_" for c in str(session_key))
    return os.path.join(_RECORDING_DIR, f"{safe}.txt")


def ensure_recording(session_key: str) -> str:
    """Start (or revive) the background recorder for ``session_key``.

    Idempotent and cheap to call on every page rerun: returns immediately with
    the recording file path. A first call spins up the websocket thread; the
    file fills in over the next few seconds.
    """
    os.makedirs(_RECORDING_DIR, exist_ok=True)
    path = _recording_path(session_key)
    with _LOCK:
        rec = _RECORDERS.get(session_key)
        if rec is not None and rec.alive:
            return path
        rec = _Recorder(session_key, path)
        _RECORDERS[session_key] = rec
        rec.start()
        logger.info("Started SignalR recorder for %s -> %s", session_key, path)
    return path


def is_recording(session_key: str) -> bool:
    rec = _RECORDERS.get(session_key)
    return rec is not None and rec.alive


# -- Reading the recorded feed ---------------------------------------------

def _parse_line(line: str):
    """Parse one recorded record into ``(topic, ts, data_dict)`` or ``None``.

    Two line shapes (both valid Python literals):
    - snapshot: ``['Topic', '<json string>', '']`` — payload is a JSON string
    - delta:    ``['Topic', {dict}, 'ISO-ts']``     — payload is already a dict
    """
    line = line.strip()
    if not line:
        return None
    try:
        rec = ast.literal_eval(line)
    except (ValueError, SyntaxError):
        return None  # partial last line while the recorder is mid-write
    if not isinstance(rec, list) or len(rec) < 3:
        return None
    topic, payload, ts = rec[0], rec[1], rec[2]
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
    elif isinstance(payload, dict):
        data = payload
    else:
        return None
    return topic, ts, data


def topic_entries(session_key: str, topic: str) -> list[tuple[str, dict]] | None:
    """Entries for one topic from the live recording, matching the
    ``_fetch_stream`` contract: ``[(ts, delta_dict), ...]`` in arrival order.

    Returns ``None`` when no recording file exists for the session (caller then
    falls back to the static archive). Returns ``[]`` when a recording exists
    but is still empty (websocket connected, snapshot not yet flushed).

    ``ts`` is the feed's absolute ISO timestamp (``"2026-06-26T15:13:30.843Z"``)
    or ``""`` for snapshot records; ``_live_client._parse_ts`` handles both.
    """
    path = _recording_path(session_key)
    if not os.path.exists(path):
        # The recorder may have just started and not opened the file yet. Treat
        # that as "live but empty" (return []) so the caller doesn't hammer the
        # static archive — which 403s mid-session — while the feed warms up.
        # Only None (no recorder at all) defers to the static archive.
        return [] if is_recording(session_key) else None
    # A stale file is a leftover from a session that has since ended; let the
    # caller fall through to the (now-complete) static archive instead.
    try:
        if _time.time() - os.path.getmtime(path) > _STALE_AFTER_S:
            return None
    except OSError:
        return None

    base = topic.split(".")[0]  # "TimingData.jsonStream" -> "TimingData"
    try:
        return _read_entries(path, base)
    except OSError:
        return None


def _read_entries(path: str, base_topic: str) -> list[tuple[str, dict]]:
    """Parse a recorded feed file into ``[(ts, delta), ...]`` for one topic."""
    entries: list[tuple[str, dict]] = []
    with open(path) as f:
        for line in f:
            parsed = _parse_line(line)
            if parsed is None:
                continue
            t, ts, data = parsed
            if t == base_topic:
                entries.append((ts, data))
    return entries

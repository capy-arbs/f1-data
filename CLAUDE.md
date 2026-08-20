# Box-Box (F1 Analytics Dashboard)

## What This Is
An F1 dashboard combining a complete historical archive (1950–today) with live race-weekend timing data from the official F1 feed. Marquee feature is **Time-to-Strike** — a live predictor that estimates how many laps until a chasing driver catches the car ahead, based on real-time gaps and recent pace differential.

Live at https://boxbox.playastrova.com — self-hosted on a Raspberry Pi behind a Cloudflare Tunnel (see Hosting & Deploy). Personal project, public repo. The live SignalR feed needs outbound WebSocket egress, which platform hosts block — self-hosting is load-bearing, not a preference (post-mortem in `project_notes.md`).

## Architecture

Layered: pages stay thin; `queries/` owns SQL, `charts/` owns figures, `data/` owns fetching
and caching. **Inline SQL or chart-building inside a page is a smell — push it down a layer.**
Directory listing and the data-source rundown are in `README.md`; the deployment picture is in
`project_notes.md`.

**Three timing sources, and which one applies depends on when the session is:**

1. **SignalR websocket** (`data/f1_signalr.py`) — a session that is *on track right now*. The only genuinely live path.
2. **Static `.jsonStream` archive** (`data/f1_live_client.py`, REST polling) — a session that has finished but is not yet in FastF1.
3. **FastF1** (`session.load()`) — older completed sessions.

Sources 1 and 2 both funnel through `data/f1_live_client.py`'s parsers, so a parsing fix
lands for both. Historical data comes from the committed SQLite DB; standings and results
come from Jolpica.

## Key Patterns & Conventions

### Sprint points are in a separate table
`results.points` is **main-race only**. Sprint points live in `sprint_results.points`. Anywhere we sum points for a championship total — career stats, season stats, momentum totals, head-to-head, teammate-points, What-If simulations — we have to UNION with `sprint_results` or the totals don't match the official standings. This has bitten us repeatedly (incident history in `project_notes.md`). Helpers in `queries/drivers.py`:
- `_sprint_points_total(driver_id)` — career-long sprint points
- `_sprint_points_by_season(driver_id)` — per-year dict

Wins/podiums/poles stay main-race-only by F1 convention (sprint wins are tracked separately).

### Circuit Explorer stats come from a complete winners archive
The `races`/`results` tables hold only the seasons the user has loaded (a few, typically), and `races` includes current-season races that haven't run yet — so deriving "races held / first race / most wins" from them silently reports the loaded slice as all-time. Circuit stats instead read `circuit_race_winners`: winner-only rows for **every** championship race 1950–today (one Jolpica page per season via `fetch_race_winners`, backfilled by `data/loader.py::load_all_race_winners` — button on Load Data — and kept fresh for the current year by `load_season`). Denormalized names, no FK rows forced for unloaded seasons; completed races only, so counts never include future rounds. The Current/Past scope split on the page uses `on_current_calendar` (circuit is on this season's calendar in `races`), NOT `last_race == latest season` — mid-season, a circuit whose race hasn't run yet has `last_race` = last year.

Pre-championship history (Spa's first GP was 1925, not 1950) isn't in Ergast/Jolpica at all. `data/circuit_facts.py::FIRST_GRAND_PRIX` is a Wikipedia-curated static dict (circuit_id → (year, note)) shown as the "First Grand Prix" metric when it predates the first F1 race. Static history — never needs refreshing; only add entries for new circuits with pre-F1 GP pasts.

### Pit-stop durations come in two formats
- Normal: `"22.630"` (seconds as string)
- Long incidents: `"M:SS.mmm"` like `"18:01.553"` (red flag, repair, etc.)

`data/loader.py::_parse_pit_duration` handles both. The pit-stop chart filters anything > 120s out and lists them in an annotation above the chart so they don't dwarf normal stops.

### Lapped cars become NaN gaps
Gap data can be NaN for lapped/retired drivers. The FastF1 path derives gaps from cumulative timestamps (lapped drivers have no comparable time). The live client parses F1's gap strings directly — formats include `"+1.234"` (seconds), `""` (leader → 0.0), `"LAP 1"` / `"1L"` / `"1 L"` (all → NaN). Time-to-Strike's `_gap_between` handles NaN with `pd.isna` checks — returns None rather than crashing.

### Jolpica caps `limit` at 100 silently
Requesting `limit=1000` returns only 100 rows; the API echoes `"limit": 100` in the response without erroring. `data/fetcher.py::_get` clamps the requested limit to 100 and advances `offset` by the **served** limit (read back from the response), not the requested one — otherwise the `offset >= total` exit condition trips after a single page. Paired with a 429 retry loop with exponential backoff (Jolpica rate-limits hard during long backfills) — `Retry-After` is honoured if present.

### `pd.merge_asof` chokes on NaN keys
Drop NaN dates before any time-series merge. Used in `gap_evolution_chart`.

### Custom sidebar nav
Streamlit's `st.navigation` doesn't natively collapse section groups. `app.py` uses `position="hidden"` to keep it as a router only, then renders the sidebar manually with `st.expander` per group. CSS in `app.py` hides Streamlit's auto-generated nav (`[data-testid="stSidebarNav"] { display: none }`).

### Plotly modebar is monkey-patched
`app.py` patches `st.plotly_chart` so every chart gets `displayModeBar=True` and `displaylogo=False` without touching the 37 individual call sites.

### `driver_standings.points` is already cumulative
The Jolpica `/standings` endpoint returns season-to-date championship totals, not per-round points. So `driver_standings.points[round=4]` IS the total championship points after R4, not the points scored AT R4. **Don't `cumsum` on top of it** in charts that show progression — just plot it directly.

### Team-aware Head-to-Head colours
`queries/drivers.py::get_latest_constructor(driver_id)` returns the constructor a driver most recently raced for. The H2H pages look up `TEAM_COLORS[<that id>]` and pass it through `season_comparison_bar`, `cumulative_wins_chart`, `h2h_qualifying_chart` as optional `d1_color` / `d2_color` kwargs. Falls back to the default red/blue palette if the team isn't in `TEAM_COLORS`.

### Live data caching
Every function in `data/live.py` is wrapped in `@st.cache_data(ttl=...)` with a TTL sized to how fast the underlying data changes — read the decorators there for current values. The live client (`data/f1_live_client.py`) adds a 5-second in-memory dedup cache (`_STREAM_CACHE`) so that multiple `data/live.py` functions calling the same endpoint within a single page render don't make redundant HTTP requests.

Manual "Refresh now" button on Live Race calls `fn.clear()` on each cached fetcher to bypass TTLs.

### Live client stint data quirks
F1's `TimingAppData.jsonStream` has two gotchas for tire/stint parsing (handled in `data/f1_live_client.py`):

1. **Initial stint data arrives as a list, not a dict.** The very first `Stints` update per driver is `[{...}]` (list with one element), while all subsequent updates are `{"0": {...}}` (dict keyed by stint index). `_normalize_stints()` handles both.

2. **`LapNumber` in stint data is the fastest-lap number, not the stint start.** Stint boundaries are instead computed from `TotalLaps` (cumulative tire wear including pre-race laps from `StartLaps`). Stint length = `TotalLaps − StartLaps`. The first stint starts at lap 1; each subsequent stint starts at the prior stint's end + 1. `_stint_boundaries()` centralises this logic and both `get_stints` and `get_laps` use it.

### Live data is SignalR, not static files
The static `.jsonStream` archive files are **not written during a live session** - they appear only after the session ends. Anything that reads them mid-session sees nothing.

The genuinely-live feed is the **SignalR Core websocket** at `wss://livetiming.formula1.com/signalrcore`. Key facts:
- **Auth.** F1 put the feed behind an F1TV-subscription token (`get_auth_token` launches an interactive OAuth flow). FastF1 ships a `no_auth=True` escape hatch but it's **broken in 3.8.3** — it passes `access_token_factory=None` where signalrcore requires a callable, raising `TypeError: access_token_factory is not function`. `data/f1_signalr.py::FreeSignalRClient` subclasses FastF1's client and passes `lambda: ""` instead. The core timing topics (TimingData, DriverList, TimingAppData, WeatherData, RaceControlMessages, ...) stream **without a valid token** — verified live. The legacy `/signalr` ASP.NET endpoint now 401s, so this is the only free path.
- **Streamlit integration.** A websocket can't live in a stateless rerun, so a **process-singleton background thread** (`ensure_recording`) records the stream to a per-session file in tempdir; each rerun reads + replays it. The recorded format matches FastF1's `SignalRClient` output (`[topic, payload, ts]` Python-repr lines), so `topic_entries` reshapes it into the `(ts, delta)` pairs `data/f1_live_client.py`'s existing parsers already consume — `_fetch_stream` prefers a **fresh** recording, else the static archive.
- **The feed is global, not addressable.** It always streams whichever session is on track *now* — you can't ask it for a specific session. So `ensure_recording` is gated on `_is_live_now()` (strict on-track window), not the wider 12h static-archive window, or viewing this-morning's FP1 while P2 is live would capture P2's data under FP1's key. And recordings are **freshness-gated** by file mtime (`_STALE_AFTER_S`): a leftover file from an ended session is ignored so callers fall through to the now-complete static archive.
- **Snapshot vs delta, and the Sectors list gotcha.** The Subscribe response sends a full-state snapshot (payload is a JSON *string*); subsequent messages are deltas (payload is a dict) with absolute ISO timestamps (`_parse_ts` handles both ISO and the static feed's session-relative format). Like Stints, **`Sectors` arrives as a list in the snapshot but an index-keyed dict in deltas** — `_normalize_timing_line()` converts the list form before merging so snapshot sector values survive and deltas update them in place.
- On the very first render after a session goes live there's a ~2–5s lag while the recorder connects and the snapshot flushes; the page falls back to FastF1 (empty for a live session) for that one render, then the 10s auto-refresh picks up live data. Tests pin the parsing against a real captured P2 sample in `tests/fixtures/signalr_p2_sample.txt` (`tests/test_signalr.py`) — no network or threads.
- **OPEN BUG - no watchdog for a stalled-but-alive connection.** Seen live: the websocket went *half-dead* (`ws_connected: True` but the recording file frozen) for ~5 min until the thread died and the next `ensure_recording` revived it - ~9 min of data outage, self-recovered. If the recording file mtime goes stale while the thread reports alive, the recorder should proactively kill and reconnect (candidate fix in `data/f1_signalr.py`). Race-day watcher tooling stays on the Pi for reuse: `/opt/f1-dashboard/watch_race.py`, launched as transient unit `f1-race-watch` with its own `F1_LIVE_RECORDING_DIR` so it never shares a recording file with the app; JSONL log in `/opt/f1-dashboard/watch/`. Two data quirks to expect: the P2-P1 pair often has no computable gap ("No live gap data yet"), and the `position` topic lags `intervals` slightly so adjacent-pair pickers can be one spot stale.

### Tire strategy chart ordering
`charts/live_charts.py::stint_gantt` sorts drivers by finishing position (from the grid's `position` column) so the winner appears at the top. Falls back to `lap_end` sort when position isn't available.

## Theme
Pitwall — broadcast-style dark. F1 red (#E10600) on near-black (#0A0B0F).
- `.streamlit/config.toml` for the base palette
- Custom CSS in `app.py` for typography, sidebar gradient, metric-card styling, table borders
- Per-chart `hoverlabel` styling so tooltips match the theme
- Compound colors (Pirelli) defined in `charts/live_charts.py::COMPOUND_COLOURS`
- Semantic delta colours in `config.py`: `COLOR_POSITIVE` (green, gained), `COLOR_NEGATIVE` (red, lost), `COLOR_NEUTRAL`. Use these for gain/loss bars rather than re-hardcoding `#22c55e`/`#ef4444` (they're still hardcoded in a few older charts — migrate when touched)

Page titles get an automatic red underline via the `h1` CSS rule. Section subheaders are uppercased small caps. Metric values render in monospace for that timing-board feel.

## Hosting & Deploy
Self-hosted on the **astrova Raspberry Pi**, public at **https://boxbox.playastrova.com** via a second ingress rule on the game's Cloudflare tunnel. **The Pi is shared infrastructure — the tunnel, SSH access, and the resource caps that keep the game ahead of this app are documented in the global `~/.claude/CLAUDE.md`. Verify the SSH user against the tailnet ACL; do not copy an ssh command from a project file.** F1-specific operational facts:
- The app runs as user `f1dash` from `/opt/f1-dashboard` (venv `.venv`); git/venv ops via `runuser -u f1dash -- …`.
- **App service:** `systemd` unit `f1-dashboard.service` runs `streamlit run app.py` on `0.0.0.0:8501`. Unit files + runbook committed in `deploy/` (`deploy/pi-setup.md`). Deploy problems: `journalctl -u f1-dashboard`, `systemctl restart f1-dashboard`.
- **Deploy on push:** `f1-dashboard-update.timer` pulls `main` every ~30 min and, only if HEAD moved, pip-installs + restarts the app (f1dash restarts it via a narrow sudoers rule). So `git push` still ≈ deploys, just on a ≤30-min lag instead of instant. Private admin view over the tailnet: `http://astrova-pi:8501`.
- **Single branch** workflow: push to `main`. **Public repo** on GitHub.
- **Database is committed** (`f1_data.db`, ~1.1MB) so a fresh clone ships with full historical data immediately.
- **Don't move to a platform host without checking WebSocket egress.** Streamlit Cloud is retired — it blocked the outbound SignalR socket at the network layer (post-mortem in `project_notes.md`). `.streamlit/config.toml` (theme) and the `streamlit` dep still matter; the Cloud platform doesn't.

### Auto-refresh action
`.github/workflows/refresh-data.yml` runs Mondays + Wednesdays at **06:13 UTC** (deliberately off the hour — top-of-the-hour cron times collide with GitHub's shared-runner pool and frequently fail with "could not acquire runner" or get delayed 30-90 minutes). Calls `load_season(conn, current_year)`, commits any DB changes as `f1-data-refresh-bot`, pushes to `main` — which the Pi's `f1-dashboard-update.timer` pulls within ~30 min. Manually triggerable from the Actions tab.

The Mon refresh catches Sunday race results once they've settled. The Wed refresh catches mid-week steward decisions, DSQs, post-race penalty changes that retroactively shift positions.

The Live Race page shows a stale-data warning if the most-recent race in the DB is more than 14 days old.

## Page → File Map

`app.py`'s `GROUPS` dict is the single source of truth for routing - read it rather than a
table here. Two things it will not tell you: sidebar **labels are not filenames**, and the
numeric prefixes on page files **do not route**.

## Drivers split: current vs historical
- **Drivers** group in the nav: filtered to the most-recent season's grid via `queries/drivers.py::get_current_drivers()`.
- **Records & History** group: full archive via `get_all_drivers()`. Same rendering, different filter.

## Development & CI
- **Tests:** `pytest` (config in `pyproject.toml`, `testpaths = ["tests"]`). Suite covers the sprint-points invariant (incl. `what_if.get_season_results` and `historical.get_normalized_season_points`), the Time-to-Strike solver, the Jolpica fetcher pagination, and the live-client parsing (`_parse_gap`, `_normalize_stints`, `_stint_boundaries`, `get_classification` retired-driver reorder), and the SignalR live path (`tests/test_signalr.py`: record parsing, snapshot-vs-delta, freshness gating, ISO-timestamp parsing, and full replay through the shaping functions against a real captured P2 sample). The live client's pure helpers are tested by monkeypatching `_fetch_stream` — no network needed.
- **Lint:** `ruff check .` — rule selection and deliberate ignores live in `pyproject.toml`. `ruff check --fix .` auto-fixes most issues.
- **CI:** `.github/workflows/test.yml` runs ruff + pytest on every push/PR (Python 3.11). The Pi auto-deploys `main` within ~30 min of a push, so this gate is the only thing between a bad commit and prod — keep it green. Dev tooling is in `requirements-dev.txt` (not installed on the Pi).
- **Dependency pinning:** `requirements.txt` floors stay, with upper bounds capped at the next major (the Pi resolves fresh with no lockfile on each update, prebuilt aarch64 wheels only). Bump caps deliberately after testing a new major locally.

## Verification
- `streamlit run app.py` then click each section
- For the Time-to-Strike feature: defaults to the latest FastF1-loaded session; will fall back to the most recent completed race when no live race is running, so the page is never empty
- For sprint-point parity: any driver's dashboard total for a season must equal their main-race points (`results.points`) **plus** sprint points (`sprint_results.points`) — the two live in separate tables. Cross-check a driver's dashboard total against the official F1 standings for whatever rounds are currently loaded; a mismatch means a sprint-UNION was missed somewhere. (The DB loads the current season progressively via the Mon/Wed refresh, so the exact round count moves through the year.)
- For pit-stop outlier handling: Australia 2026 should show Stroll's stops 1, 2, 4 stacked, with stops 3 + Alonso's stop 2 listed in the annotation above the chart

## Don't
- Don't add docstrings or comments that re-state what well-named code already says
- Don't add fallback paths for things that can't happen (frameworks have invariants — trust them)
- Don't drop the `legendgroup` / `legendgrouptitle_text` from multi-driver charts — they keep teammates grouped in the legend
- Don't switch to `hovermode="x unified"` on the Standings charts — 22 drivers don't fit; we use the driver+teammate model instead

## Future ideas

Tracked in `FUTURE.md`. This section used to restate it near-verbatim; it no longer does.

# Box-Box (F1 Analytics Dashboard)

## What This Is
An F1 dashboard combining a complete historical archive (1950–today) with live race-weekend timing data from the official F1 feed. Marquee feature is **Time-to-Strike** — a live predictor that estimates how many laps until a chasing driver catches the car ahead, based on real-time gaps and recent pace differential.

Live at https://box-box.streamlit.app. Personal project, public repo, free Streamlit Community Cloud deploy.

## Architecture
- **Streamlit** multi-page app via `st.navigation` (custom sidebar with collapsible groups, see `app.py`)
- **SQLite** (`f1_data.db`, ~544KB, committed in repo) for historical data
- **Jolpica API** for historical (`api.jolpi.ca/ergast/f1`)
- **F1 Live Timing — three sources, in order of freshness:**
  1. **SignalR websocket** (`data/f1_signalr.py`) for a session that is *on track right now*. This is the genuinely-live feed (`wss://livetiming.formula1.com/signalrcore`) the broadcast graphics use. A process-singleton background thread records the stream to a local file; each Streamlit rerun replays that file. See the "Live data is SignalR, not static files" section below — this is a correction to the long-held (wrong) belief that the static `.jsonStream` poll was the live source.
  2. **Static `.jsonStream` archive** (`data/f1_live_client.py`, REST polling of `livetiming.formula1.com/static/`) for *recently-completed* sessions. These files are written only **after** a session finishes archiving, so they're the post-session replay, not live.
  3. **FastF1** (`session.load()`) for older completed sessions.

  Both 1 and 2 funnel through `data/f1_live_client.py`'s parsers (the SignalR recording and the static `.jsonStream` files share the same delta-replay shaping — `_fetch_stream` reads the live recording when fresh, the static archive otherwise). Routing is automatic in `data/live.py` via `_has_live_timing()` (static-archive eligibility, 12h window) and `_is_live_now()` (strict on-track check that gates the SignalR recorder). Previously used OpenF1 (swapped 2026-05-23, paid tier), then FastF1-only (swapped 2026-05-24 because `session.load()` returns nothing during live races), then static-`.jsonStream`-only (which, we discovered 2026-06-26, *also* returns nothing live — those files don't exist until the session archives), then added the SignalR feed for true live data.
- **bacinger/f1-circuits** GeoJSON for track outlines

Layered code structure:
- `data/` — fetch + persistence
- `queries/` — pure SQL/compute helpers, no Streamlit
- `charts/` — Plotly figure builders, take DataFrames return Figures
- `views/` — shared page renderers used by more than one page (e.g. the current-grid + historical Driver Profiles / Head-to-Head pairs both call into one renderer here). When you find yourself copying a whole page to make a "historical" or "alternate-filter" variant, put the body in `views/` and let each page be a thin shim.
- `pages/` — Streamlit pages. Pages should stay thin: `init_db()`, fetch the input set (e.g. drivers list), call into a `views/` renderer with title/caption/data. Inline SQL or chart-building inside a page is a smell — push it down a layer.

The What-If and Sprint Analysis pages are worked examples of this: the What-If simulation transforms (`apply_driver_swap`, `apply_points_system`, `apply_overrides` cascade insertion, `standings_rank_changes`) live in `queries/what_if.py` with charts in `charts/what_if_charts.py`; sprint queries + the sprint-vs-race compute live in `queries/sprint.py` with charts in `charts/sprint_charts.py`. The pages just wire inputs → transform → render. The pure transforms are unit-tested (`tests/test_what_if.py`, `tests/test_sprint.py`) without a DB.

## Key Patterns & Conventions

### Sprint points are in a separate table
`results.points` is **main-race only**. Sprint points live in `sprint_results.points`. Anywhere we sum points for a championship total — career stats, season stats, momentum totals, head-to-head, teammate-points, What-If simulations — we have to UNION with `sprint_results` or the totals don't match the official standings. This has bitten us repeatedly; the audit on 2026-05-23 caught three lingering violations (`queries/drivers.py::get_head_to_head`, `queries/drivers.py::get_teammate_seasons`, `pages/8_What_If.py::get_season_results`) that have since been fixed. Helpers in `queries/drivers.py`:
- `_sprint_points_total(driver_id)` — career-long sprint points
- `_sprint_points_by_season(driver_id)` — per-year dict

Wins/podiums/poles stay main-race-only by F1 convention (sprint wins are tracked separately).

### Pit-stop durations come in two formats
- Normal: `"22.630"` (seconds as string)
- Long incidents: `"M:SS.mmm"` like `"18:01.553"` (red flag, repair, etc.)

`data/loader.py::_parse_pit_duration` handles both. The pit-stop chart filters anything > 120s out and lists them in an annotation above the chart so they don't dwarf normal stops.

### Lapped cars become NaN gaps
Gap data can be NaN for lapped/retired drivers. The FastF1 path derives gaps from cumulative timestamps (lapped drivers have no comparable time). The live client parses F1's gap strings directly — formats include `"+1.234"` (seconds), `""` (leader → 0.0), `"LAP 1"` / `"1L"` / `"1 L"` (all → NaN). Time-to-Strike's `_gap_between` handles NaN with `pd.isna` checks — returns None rather than crashing.

### Jolpica caps `limit` at 100 silently
Requesting `limit=1000` returns only 100 rows; the API echoes `"limit": 100` in the response without erroring. `data/fetcher.py::_get` clamps the requested limit to 100 and advances `offset` by the **served** limit (read back from the response), not the requested one — otherwise the `offset >= total` exit condition trips after a single page. Hit on 2026-05-07: every 2022–2025 season was stuck at ~5 rounds of `results`/`qualifying`/`sprint_results` because the loop quit early. The fix is paired with a 429 retry loop with exponential backoff (Jolpica rate-limits hard during long backfills) — `Retry-After` is honoured if present.

### `pd.merge_asof` chokes on NaN keys
Drop NaN dates before any time-series merge. Used in `gap_evolution_chart`.

### Custom sidebar nav
Streamlit's `st.navigation` doesn't natively collapse section groups. `app.py` uses `position="hidden"` to keep it as a router only, then renders the sidebar manually with `st.expander` per group. CSS in `app.py` hides Streamlit's auto-generated nav (`[data-testid="stSidebarNav"] { display: none }`).

### Plotly modebar is monkey-patched
`app.py` patches `st.plotly_chart` so every chart gets `displayModeBar=True` and `displaylogo=False` without touching the 37 individual call sites.

### `driver_standings.points` is already cumulative
The Jolpica `/standings` endpoint returns season-to-date championship totals, not per-round points. So `driver_standings.points[round=4]` IS the total championship points after R4, not the points scored AT R4. **Don't `cumsum` on top of it** in charts that show progression — just plot it directly. (We hit this bug once on the Standings → Points Accumulation chart; Antonelli was reading 237 at R4 instead of his real 100.)

### Sprint points must be unioned everywhere totals are summed
Already covered above for career stats, but worth restating for normalized-points work: `get_normalized_season_points` UNIONs `results` + `sprint_results` and applies the target points system to BOTH sets of finishing positions, so both the actual and normalized totals match official championship behaviour.

### Team-aware Head-to-Head colours
`queries/drivers.py::get_latest_constructor(driver_id)` returns the constructor a driver most recently raced for. The H2H pages look up `TEAM_COLORS[<that id>]` and pass it through `season_comparison_bar`, `cumulative_wins_chart`, `h2h_qualifying_chart` as optional `d1_color` / `d2_color` kwargs. Falls back to the default red/blue palette if the team isn't in `TEAM_COLORS`.

### Live data caching
Every function in `data/live.py` is wrapped in `@st.cache_data(ttl=...)` with a TTL sized to how fast the underlying data changes:
- `intervals`, `position`: 10s (live race rate)
- `laps`: 15s
- `stints`, `pit`: 30s
- `weather`: 20s
- `race_control`: 15s
- `drivers`: 600s (static per session)
- `sessions`: 300s

The live client (`data/f1_live_client.py`) adds a 5-second in-memory dedup cache (`_STREAM_CACHE`) so that multiple `data/live.py` functions calling the same endpoint within a single page render don't make redundant HTTP requests.

Manual "Refresh now" button on Live Race calls `fn.clear()` on each cached fetcher to bypass TTLs.

### Live client stint data quirks
F1's `TimingAppData.jsonStream` has two gotchas for tire/stint parsing (handled in `data/f1_live_client.py`):

1. **Initial stint data arrives as a list, not a dict.** The very first `Stints` update per driver is `[{...}]` (list with one element), while all subsequent updates are `{"0": {...}}` (dict keyed by stint index). `_normalize_stints()` handles both.

2. **`LapNumber` in stint data is the fastest-lap number, not the stint start.** Stint boundaries are instead computed from `TotalLaps` (cumulative tire wear including pre-race laps from `StartLaps`). Stint length = `TotalLaps − StartLaps`. The first stint starts at lap 1; each subsequent stint starts at the prior stint's end + 1. `_stint_boundaries()` centralises this logic and both `get_stints` and `get_laps` use it.

### Live data is SignalR, not static files
Discovered 2026-06-26 during Austrian GP P2. The static `.jsonStream` archive files are **not written during a live session** — F1's `SessionInfo.json` reports `ArchiveStatus: "Generating"` and every data topic returns **HTTP 403 `AccessDenied`** (the S3 key doesn't exist yet) until the session finishes and archives. So polling `livetiming.formula1.com/static/.../TimingData.jsonStream` can only ever serve a completed session's replay; during a live session it returns nothing and the page is blank. (It *looked* live in testing only because those sessions had already archived by the time we tested.)

The genuinely-live feed is the **SignalR Core websocket** at `wss://livetiming.formula1.com/signalrcore`. Key facts:
- **Auth.** F1 put the feed behind an F1TV-subscription token (`get_auth_token` launches an interactive OAuth flow). FastF1 ships a `no_auth=True` escape hatch but it's **broken in 3.8.3** — it passes `access_token_factory=None` where signalrcore requires a callable, raising `TypeError: access_token_factory is not function`. `data/f1_signalr.py::FreeSignalRClient` subclasses FastF1's client and passes `lambda: ""` instead. The core timing topics (TimingData, DriverList, TimingAppData, WeatherData, RaceControlMessages, ...) stream **without a valid token** — verified live. The legacy `/signalr` ASP.NET endpoint now 401s, so this is the only free path.
- **Streamlit integration.** A websocket can't live in a stateless rerun, so a **process-singleton background thread** (`ensure_recording`) records the stream to a per-session file in tempdir; each rerun reads + replays it. The recorded format matches FastF1's `SignalRClient` output (`[topic, payload, ts]` Python-repr lines), so `topic_entries` reshapes it into the `(ts, delta)` pairs `data/f1_live_client.py`'s existing parsers already consume — `_fetch_stream` prefers a **fresh** recording, else the static archive.
- **The feed is global, not addressable.** It always streams whichever session is on track *now* — you can't ask it for a specific session. So `ensure_recording` is gated on `_is_live_now()` (strict on-track window), not the wider 12h static-archive window, or viewing this-morning's FP1 while P2 is live would capture P2's data under FP1's key. And recordings are **freshness-gated** by file mtime (`_STALE_AFTER_S`): a leftover file from an ended session is ignored so callers fall through to the now-complete static archive.
- **Snapshot vs delta, and the Sectors list gotcha.** The Subscribe response sends a full-state snapshot (payload is a JSON *string*); subsequent messages are deltas (payload is a dict) with absolute ISO timestamps (`_parse_ts` handles both ISO and the static feed's session-relative format). Like Stints, **`Sectors` arrives as a list in the snapshot but an index-keyed dict in deltas** — `_normalize_timing_line()` converts the list form before merging so snapshot sector values survive and deltas update them in place.
- On the very first render after a session goes live there's a ~2–5s lag while the recorder connects and the snapshot flushes; the page falls back to FastF1 (empty for a live session) for that one render, then the 10s auto-refresh picks up live data. Tests pin the parsing against a real captured P2 sample in `tests/fixtures/signalr_p2_sample.txt` (`tests/test_signalr.py`) — no network or threads.

### Tire strategy chart ordering
`charts/live_charts.py::stint_gantt` sorts drivers by finishing position (from the grid's `position` column) so the winner appears at the top. Falls back to `lap_end` sort when position isn't available.

### Time-to-Strike formula
Implemented in `queries/strike.py` as a pure function returning `StrikeResult`. The solver walks forward lap by lap, accumulating per-lap pace advantage until it covers the current gap:
```
catches on smallest k such that
  Σ_{i=1..k} (target_pace_i − chaser_pace_i) >= gap_seconds
where pace_i for each driver = base_pace + deg_slope * i
```
- `gap_seconds` = chaser's `gap_to_leader` − target's `gap_to_leader`
- `base_pace` and `deg_slope` come from a linear fit on the last 5 clean laps (pit-out and outlier-slow laps stripped). With <3 clean laps the slope falls back to 0 and the math collapses to the old flat-pace `ceil(gap / Δpace)`.
- Returns `None` (→ "can't close") when the cumulative advantage never covers the gap within 80 projected laps. This handles the case where current pace_delta is small but degradation closes the gap — and the inverse, where the chaser is currently faster but is degrading harder.

Confidence label (high/medium/low) is heuristic from pace-delta magnitude, lap-time stdev, tire-age delta, **deg-slope gap** (target degrading faster widens the window), and close proximity (sub-second gaps). The function fills `result.notes[]` so the UI can show *why* a verdict was given.

**2026 reg note:** DRS no longer exists; overtaking uses manual override mode (electrical boost) plus active aero. There's no "within 1 second" technical trigger anymore, but a sub-second gap still indicates "overtake imminent" because slipstream + override windows favour the chaser at that range. The constant in `strike.py` is named `PROXIMITY_THRESHOLD_S`, not the legacy `DRS_THRESHOLD_S`.

## Theme
Pitwall — broadcast-style dark. F1 red (#E10600) on near-black (#0A0B0F).
- `.streamlit/config.toml` for the base palette
- Custom CSS in `app.py` for typography, sidebar gradient, metric-card styling, table borders
- Per-chart `hoverlabel` styling so tooltips match the theme
- Compound colors (Pirelli) defined in `charts/live_charts.py::COMPOUND_COLOURS`
- Semantic delta colours in `config.py`: `COLOR_POSITIVE` (green, gained), `COLOR_NEGATIVE` (red, lost), `COLOR_NEUTRAL`. Use these for gain/loss bars rather than re-hardcoding `#22c55e`/`#ef4444` (they're still hardcoded in a few older charts — migrate when touched)

Page titles get an automatic red underline via the `h1` CSS rule. Section subheaders are uppercased small caps. Metric values render in monospace for that timing-board feel.

## Hosting & Deploy
- **Streamlit Community Cloud** at https://box-box.streamlit.app — auto-redeploys ~30s after any push to `main`.
- **Single branch** workflow: `git push` deploys.
- **Public repo** on GitHub (free-tier Streamlit Cloud requirement).
- **Database is committed** (`f1_data.db`, ~544KB) so deploys ship with full historical data immediately.

### Auto-refresh action
`.github/workflows/refresh-data.yml` runs Mondays + Wednesdays at **06:13 UTC** (deliberately off the hour — top-of-the-hour cron times collide with GitHub's shared-runner pool and frequently fail with "could not acquire runner" or get delayed 30-90 minutes). Calls `load_season(conn, current_year)`, commits any DB changes as `f1-data-refresh-bot`, pushes — which triggers a Streamlit Cloud redeploy. Manually triggerable from the Actions tab.

The Mon refresh catches Sunday race results once they've settled. The Wed refresh catches mid-week steward decisions, DSQs, post-race penalty changes that retroactively shift positions.

The Live Race page shows a stale-data warning if the most-recent race in the DB is more than 14 days old.

### Stale-deploy ImportError pattern
If a page suddenly fails on the cloud with `ImportError` (message redacted) but imports cleanly locally and `git log origin/main..main` is empty, the most likely cause is that Streamlit Cloud cached a partial deploy — new page code referencing a name that the *old* helper module didn't have. **Reboot the app from share.streamlit.io → Manage app → Reboot** before debugging code. This usually clears it. Hit on 2026-05-06 right after the QA-pass commit added `get_latest_constructor` to both H2H pages and `queries/drivers.py` in the same commit; only the page side was loaded, so the import blew up.

## Page → File Map
The sidebar labels and page titles don't always match the file names because we've renamed pages without renumbering the files:

| Sidebar / URL                | File                                  |
|------------------------------|---------------------------------------|
| Live Session (default)       | pages/14_Live_Race.py                 |
| Standings                    | pages/1_Season_Tracker.py             |
| Race Calendar                | pages/9_Race_Calendar.py              |
| Race Breakdown               | pages/2_Race_Breakdown.py             |
| Sprint Analysis              | pages/11_Sprint_Analysis.py           |
| Championship Momentum        | pages/16_Championship_Momentum.py     |
| Driver Profiles (current)    | pages/6_Driver_Profiles.py            |
| Head-to-Head (current)       | pages/3_Head_to_Head.py               |
| Circuit Map                  | pages/5_Circuit_Map.py                |
| What-If Simulator            | pages/8_What_If.py                    |
| Historical Driver Profiles   | pages/18_Driver_Profiles_Historical.py|
| Historical Head-to-Head      | pages/19_Head_to_Head_Historical.py   |
| Era Comparison               | pages/4_Historical.py                 |
| Pit Stop Records             | pages/15_Pit_Stop_Records.py          |
| Lap Time Evolution           | pages/17_Lap_Time_Evolution.py        |
| Load Data                    | pages/0_Load_Data.py                  |

The numeric prefixes on the files no longer affect routing or order — `app.py`'s `GROUPS` dict is the single source of truth. The numbers are kept for compatibility / file-tree readability.

## Drivers split: current vs historical
- **Drivers** group in the nav: filtered to the most-recent season's grid via `queries/drivers.py::get_current_drivers()`.
- **Records & History** group: full archive via `get_all_drivers()`. Same rendering, different filter.

## Live Session page conventions

The page (`pages/14_Live_Race.py`, sidebar label "Live Session") works for any session type — practice, qualifying, sprint, race — so there's live or recent data every day of a weekend. `_is_race_session(sess)` classifies Race/Sprint as the only sessions where **Time-to-Strike** is meaningful (its gap-closing model assumes on-track running order). For other sessions the widget stays usable for data inspection but renders an `st.info` note that the verdict isn't a real overtake prediction.

### Standings position = classification, not last lap
`get_position` is a per-lap time series, so the *last* row for a retired driver is frozen at the on-track position they held when they stopped — a car that drops out while running P2 stayed "P2" in the standings forever, duplicating whoever's really P2 (hit 2026-06-22: Antonelli showed P2 in the Spain GP despite a mid-race DNF). The fix is `get_classification(session_key)` — authoritative running order with retirements sorted to the back: FastF1's `session.results` (`Position` + `Status`) for completed sessions, the live feed's `Retired`/`Stopped` flags (re-ranked, since F1 leaves the retired car's last position in the feed) for live ones. `build_live_grid(..., classification_df)` prefers it for the `position` column, blanks `gap_to_leader`/`interval` for retired drivers, and the page shows their Gap as "DNF". Falls back to lap-derived `get_position` only when no classification exists yet (early in a live session before FastF1 ingests). `_is_finisher_status` treats `Finished`/`Lapped`/`+N Lap` as classified, everything else as retired.

### Live session detection
FastF1's schedule doesn't expose session end times (`date_end == date_start`). `pages/14_Live_Race.py::_is_live(sess)` estimates duration from a `_SESSION_DURATIONS` dict (Race = 3h, Qualifying/Practice = 1.5h, Sprint = 1.5h) and checks `date_start <= now <= date_start + duration`. Used to:
- Show a red "LIVE" badge in the header
- Default the auto-refresh checkbox to ON
- Pre-select the 10s refresh interval (vs 15s for archived sessions)

`_time_since_end(sess)` uses the same estimated end time for "ended 2h ago" / "ended 3d ago" suffixes.

### Sector colours on standings
S1/S2/S3 columns coloured via pandas `Styler.apply`:
- Purple (`rgba(139, 92, 246, 0.45)`) = session-best for that sector
- Green (`rgba(34, 197, 94, 0.35)`) = personal-best for that driver/sector
- Default = no colour

Bests are computed once from the full `laps` frame: session-best is `laps["duration_sector_N"].min()`, personal-best is per-driver `min()`. Comparisons round to 3dp because the live timing source sometimes returns extra trailing precision.

### Standings table + click-to-fill
The main standings table is rendered with pandas `Styler` (sector colours) **without** `selection_mode`, because Streamlit strips Styler backgrounds when selection is active. Click-to-fill for Time-to-Strike lives in a separate expander below the styled table, using a minimal `st.dataframe` with `selection_mode="single-row"` + `on_select="rerun"`. Clicking a row there populates the chaser picker and defaults the target to whoever is one position ahead. The selectboxes still allow override.

The Time-to-Strike block rebuilds the selectbox `key` based on the clicked row index — this forces Streamlit to re-render with the new default rather than keeping the user's previous selection sticky.

### Position movement strip
"Up: VER +3 (P12→P9)" / "Down: ALO -2 (P5→P7)" computed over the last 5 minutes of `position` events. Uses the data's own max timestamp as "now" rather than wall-clock time so the widget works on archived sessions too. Empty when nothing has changed in the window.

## Development & CI
- **Tests:** `pytest` (config in `pyproject.toml`, `testpaths = ["tests"]`). Suite covers the sprint-points invariant (incl. `what_if.get_season_results` and `historical.get_normalized_season_points`), the Time-to-Strike solver, the Jolpica fetcher pagination, and the live-client parsing (`_parse_gap`, `_normalize_stints`, `_stint_boundaries`, `get_classification` retired-driver reorder), and the SignalR live path (`tests/test_signalr.py`: record parsing, snapshot-vs-delta, freshness gating, ISO-timestamp parsing, and full replay through the shaping functions against a real captured P2 sample). The live client's pure helpers are tested by monkeypatching `_fetch_stream` — no network needed.
- **Lint:** `ruff check .` (config in `pyproject.toml`). Rule set is `E,F,W,I,B,UP`; `E501` (line length) and `B905` (zip strict) are intentionally ignored. Imports are isort-ordered (stdlib / third-party / first-party). `ruff check --fix .` auto-fixes most issues.
- **CI:** `.github/workflows/test.yml` runs ruff + pytest on every push/PR (Python 3.11). Streamlit Cloud auto-deploys `main`, so this gate is the only thing between a bad commit and prod — keep it green. Dev tooling is in `requirements-dev.txt` (not installed on Streamlit Cloud).
- **Dependency pinning:** `requirements.txt` floors stay, with upper bounds capped at the next major (Cloud resolves fresh with no lockfile). Bump caps deliberately after testing a new major locally.

## Verification
- `streamlit run app.py` then click each section
- For the Time-to-Strike feature: defaults to the latest FastF1-loaded session; will fall back to the most recent completed race when no live race is running, so the page is never empty
- For sprint-point parity: Antonelli's 2026 total should be 100 (93 main + 7 sprint as of R4 Miami). DB has results through R4; R5 Canada will load at the next Mon/Wed auto-refresh.
- For pit-stop outlier handling: Australia 2026 should show Stroll's stops 1, 2, 4 stacked, with stops 3 + Alonso's stop 2 listed in the annotation above the chart

## Don't
- Don't add docstrings or comments that re-state what well-named code already says
- Don't add fallback paths for things that can't happen (frameworks have invariants — trust them)
- Don't drop the `legendgroup` / `legendgrouptitle_text` from multi-driver charts — they keep teammates grouped in the legend
- Don't switch to `hovermode="x unified"` on the Standings charts — 22 drivers don't fit; we use the driver+teammate model instead

## Future ideas (not started)
- **Live track map** — driver dots on the racing line via FastF1's `session.pos_data`. Phased plan in `project_notes.md`.
- Pit-window predictor (best lap to pit given tire age + traffic)
- Undercut/overcut calculator
- Equal-area projection for track outlines (Mercator-squash at high latitude)
- Per-circuit rotation table to match F1.com's stylized track diagrams
- Accurate start/finish marker on track outlines (bacinger GeoJSON doesn't encode the line — would need hand-curated index per circuit or FastF1 position data)
- Team radio playback — FastF1 doesn't expose team radio directly; would need to scrape F1's audio archive or wait for FastF1 to add it

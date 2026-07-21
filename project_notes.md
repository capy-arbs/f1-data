# Box-Box (F1 Analytics Dashboard) — Project Notes

## Project Overview
Interactive Formula 1 dashboard that combines a complete historical archive (1950 to today) with live race-weekend timing data from the official F1 feed. Built as a personal project; the marquee feature is **Time-to-Strike**, a live predictor that estimates how many laps until a chasing driver catches the car ahead.

## Product Name
Box-Box
Live URL: https://boxbox.playastrova.com
GitHub: https://github.com/capy-arbs/f1-data
Branch: `main` (single branch — the Pi's update timer pulls every ~30 min)

## Hosting / Infrastructure
Self-hosted since 2026-07-08 (moved off Streamlit Community Cloud — Cloud blocks the outbound SignalR WebSocket the live feed needs; see Known Issues). Full runbook: `deploy/pi-setup.md`.
- **Host** — astrova Raspberry Pi (Pi 4, 8GB, Debian 13, aarch64). `ssh root@astrova-pi` over the tailnet (Tailscale SSH; ACL blocks the `capybearhug` user). App runs as user `f1dash` from `/opt/f1-dashboard`.
- **App service** — `systemd` unit `f1-dashboard.service` (`streamlit run app.py` on `0.0.0.0:8501`), capped `CPUQuota=200%` + `MemoryMax=1500M` so the co-located astrova game always wins.
- **Public URL** — a 2nd ingress rule on the game's existing Cloudflare Tunnel `astrova-mp` routes `boxbox.playastrova.com → localhost:8501`. One `cloudflared`, two hostnames, $0. No open inbound ports; the tunnel is the only public path.
- **Deploy on push** — `f1-dashboard-update.timer` pulls `main` every ~30 min and restarts on change (f1dash restarts via a narrow sudoers rule). Private admin view over tailnet: `http://astrova-pi:8501`.
- **GitHub Actions** — `.github/workflows/refresh-data.yml` runs Mon + Wed 06:13 UTC, refreshes the season via Jolpica, pushes the updated `f1_data.db`; the Pi's timer pulls it. Manually triggerable.

## Live URLs / Resources
- App: https://boxbox.playastrova.com
- Repo: https://github.com/capy-arbs/f1-data
- Auto-refresh action: https://github.com/capy-arbs/f1-data/actions/workflows/refresh-data.yml

## Useful Commands

```bash
# Run locally
streamlit run app.py

# Manual data refresh for the current year (rare — auto-refresh covers Mon/Wed)
python3 -c "from db.connection import get_db; from data.loader import load_season; \
  c = get_db().__enter__(); load_season(c, 2026)"

# Refresh just one round's pit-stop data (lazy-loaded by the Race Breakdown page,
# not in the season loader)
python3 -c "from db.connection import get_db; from data.loader import load_pit_stops_for_race; \
  c = get_db().__enter__(); load_pit_stops_for_race(c, 2026, 4)"

# Trigger the GitHub Action manually (gh CLI; can also click "Run workflow" in browser)
gh workflow run refresh-data.yml -R capy-arbs/f1-data

# Compile-check every page module without running streamlit
python3 -c "import py_compile, glob; [py_compile.compile(p, doraise=True) for p in glob.glob('pages/*.py') + glob.glob('charts/*.py') + glob.glob('queries/*.py') + glob.glob('data/*.py') + ['app.py']]"

# Headless smoke test — boots streamlit, hits routes, kills it
python3 -m streamlit run app.py --server.headless true --server.port 8511 > /tmp/sl.log 2>&1 &
sleep 6 && curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8511/Live_Race"
pkill -f 'streamlit run app.py'
```

## Git Workflow
Single branch (`main`). Every push to `main` triggers a Streamlit Cloud redeploy.

```bash
# Standard flow
git add <files>
git commit -m "your message"
git push                  # auto-deploys in ~30s
```

Streamlit Cloud sometimes pushes an automated commit back to the repo (`Added Dev Container Folder`, etc.) — pull before pushing if that's just happened.

The auto-refresh GitHub Action also pushes commits as `f1-data-refresh-bot` on Mon/Wed mornings; pull before starting work after those days.

## Data Refresh Schedule
- **Monday 06:13 UTC** — catches Sunday race results once they've settled
- **Wednesday 06:13 UTC** — catches mid-week steward decisions, DSQs, post-race penalty changes that retroactively shift positions

(Deliberately off-the-hour — the original `0 6 * * 1,3` cron hit a runner-acquisition failure on 2026-05-06 because GitHub's shared-runner pool is heavily oversubscribed at top-of-the-hour. Moved to `:13` which picks up cleanly almost always.)

The action calls `load_season(conn, current_year)`, which uses `INSERT OR IGNORE` for existing rows so re-runs are idempotent — only new races and changed standings get added.

The Home/Live Race page shows a "data may be stale" warning if the most-recent race in the DB is more than 14 days old.

## Tech Stack
- **Python 3.10+** (3.11 in CI via `actions/setup-python@v5`)
- **Streamlit 1.30+** (1.56 confirmed in dev) — multi-page app via `st.navigation`
- **Plotly** — every chart, with a monkey-patched modebar so reset-axes is always visible
- **SQLite** — local file `f1_data.db` (~1.1MB), shipped in the repo
- **Pandas** — DataFrame work everywhere
- **Requests** — HTTP for both data feeds
- **NumPy** — explicit dependency for `queries/strike.py`'s linear-fit pace solver
- **Jolpica API** — historical F1 data (Ergast successor; 1950–present)
- **FastF1** — Python library that taps F1's own SignalR timing feed (same source the broadcast uses). Free, community-maintained. Swapped in 2026-05-23 after OpenF1 gated live-session data behind a paid tier.
- **bacinger/f1-circuits** (MIT) — GeoJSON track outlines for the Circuit Explorer

## Architecture

Layered, one job each:

```
data/      raw fetch + persistence (Jolpica REST + FastF1 live + GeoJSON)
queries/   pure SQL/compute helpers — no Streamlit, no I/O beyond the DB
charts/    Plotly figure builders — take DataFrames in, return Figures out
views/     shared page renderers used by more than one page (e.g. Driver Profiles and Historical Driver Profiles both call into views/driver_profile.py with different driver lists + titles)
pages/     Streamlit pages — thin shims: init the DB, fetch the input set, call a views/ renderer. Inline SQL or chart-building in a page is a smell.
```

Two distinct data feeds:
- `data/fetcher.py` + `data/loader.py` — pulls historical data from Jolpica into local SQLite. One-time on first launch, then refreshed by the auto-refresh action.
- `data/live.py` — wraps FastF1's session model with `@st.cache_data` per endpoint (TTLs 10–600s). Shapes DataFrames to match the previous OpenF1 column contracts so downstream consumers (queries/strike.py, pages/14_Live_Race.py) didn't need changes.

Time-to-Strike compute lives in `queries/strike.py` as a pure function returning a `StrikeResult` dataclass. The Live Race page renders the dataclass; nothing in the math layer knows about Streamlit. The solver is degradation-aware — it fits a line over recent clean laps to recover each driver's base pace + per-lap deg slope, then walks forward lap by lap until cumulative pace advantage covers the gap. Collapses to the old flat `ceil(gap/Δpace)` when slopes are 0.

Track outlines live in `data/track_geojson.py` — fetches from the bacinger repo at runtime, cached.

Custom sidebar nav in `app.py` — uses `st.navigation(..., position="hidden")` for routing only, then renders the actual sidebar with `st.expander` per group so groups can collapse. CSS layered on top hides Streamlit's auto-rendered nav and applies the Pitwall theme.

## Pages

```
pages/
  0_Load_Data.py                       Settings — manual data load
  1_Season_Tracker.py                  Standings (renamed in nav)
  2_Race_Breakdown.py                  Race Breakdown
  3_Head_to_Head.py                    Head-to-Head (current grid only)
  4_Historical.py                      Era Comparison (renamed in nav)
  5_Circuit_Map.py                     Circuit Explorer
  6_Driver_Profiles.py                 Driver Profiles (current grid only)
  8_What_If.py                         What-If Simulator (3 tabs)
  9_Race_Calendar.py                   Race Calendar
  11_Sprint_Analysis.py                Sprint Analysis
  14_Live_Race.py                      Live Race (default landing page)
  15_Pit_Stop_Records.py               Pit Stop Records
  16_Championship_Momentum.py          Championship Momentum
  17_Lap_Time_Evolution.py             Lap Time Evolution
  18_Driver_Profiles_Historical.py     Historical Driver Profiles
  19_Head_to_Head_Historical.py        Historical Head-to-Head
```

Sidebar groups (defined in app.py):
- **Live**: Live Race
- **This Season**: Standings, Race Calendar, Race Breakdown, Sprint Analysis, Championship Momentum
- **Drivers**: Driver Profiles, Head-to-Head
- **Circuits**: Circuit Map
- **Play**: What-If Simulator
- **Records & History**: Historical Driver Profiles, Historical Head-to-Head, Era Comparison, Pit Stop Records, Lap Time Evolution
- **Settings**: Load Data

## Files

```
app.py                         Entry point — page config, theme CSS, custom nav, plotly modebar patch
config.py                      API URLs, team colors (incl. Audi/Cadillac for 2026), point systems
requirements.txt               streamlit, plotly, requests, pandas, numpy
f1_data.db                     SQLite (committed, ~1.1MB) — full seasons for the loaded years + all-time race winners 1950–2026

.streamlit/config.toml         Pitwall theme palette (F1 red on near-black)
.github/workflows/refresh-data.yml   Mon/Wed 06:00 UTC auto-refresh

db/
  connection.py                SQLite context manager (WAL mode, foreign keys on)
  schema.py                    Schema (13 tables) and idempotent init

data/
  fetcher.py                   Jolpica API calls with pagination
  loader.py                    Fetch -> transform -> insert orchestration; _parse_pit_duration handles M:SS.mmm
  normalizer.py                Cross-era point system recalculation
  live.py                      FastF1 live-timing wrapper (cached per endpoint)
  track_geojson.py             bacinger/f1-circuits track outline fetcher

queries/
  standings.py                 Season standings & progression
  races.py                     Race results, qualifying, pit stops
  drivers.py                   Career stats, head-to-head, teammates; sprint-points helpers
  historical.py                Records, normalized stats, momentum, lap evolution; sprint-aware
  circuits.py                  Circuit data and race history
  strike.py                    Time-to-Strike compute (pure, framework-free)

charts/
  season_charts.py             Position progression, points accumulation; team-grouped hovers
  race_charts.py               Grid vs finish, gap-to-fastest, stacked pit stops with outlier filter
  comparison_charts.py         H2H bars, cumulative wins, radar charts
  live_charts.py               Stint Gantt, pace trace, gap evolution

views/
  driver_profile.py            Shared renderer for Driver Profiles + Historical Driver Profiles
  head_to_head.py              Shared renderer for Head-to-Head + Historical Head-to-Head

pages/                         16 Streamlit pages (see Pages section)
```

## Data Sources
- **Jolpica** (`api.jolpi.ca/ergast/f1`) — historical F1 data, REST + JSON. Ergast API successor; same response shape. 1950–present, all rounds, qualifying, sprint, results, pit stops, standings.
- **FastF1** (https://github.com/theOehrly/Fast-F1) — Python library for F1 timing/telemetry. Free, no API key, community-maintained. Loaded via `fastf1.get_session(year, gp, identifier).load()`, which reads F1's **post-session** data (it returns nothing useful mid-session). Disk-cached locally under `$FASTF1_CACHE` (default `/tmp/fastf1_cache`). Used as the fallback for older completed sessions. We also reuse its `SignalRClient` (subclassed) for the live feed below.
- **F1 live timing — two endpoints, both `livetiming.formula1.com`:**
  - **SignalR Core websocket** (`wss://.../signalrcore`) — the genuinely-live feed, used during an on-track session via `data/f1_signalr.py`. Streams unauthenticated for the core timing topics (see the 2026-06-26/28 Completed entry).
  - **Static `.jsonStream` archive** (`/static/...`) — per-session delta logs, polled by `data/f1_live_client.py`. **Only published after a session finishes archiving**, so this is the post-session replay, not live.
- **bacinger/f1-circuits** (GitHub) — MIT-licensed GeoJSON track outlines. Files named `{country_code}-{year}.geojson`. Mapped from our `circuit_id` via a hardcoded table in `data/track_geojson.py`, with a lat/lng nearest-neighbor fallback for unmapped IDs.

Both feeds are unaffiliated with Formula 1.

## Schema (SQLite)
13 tables, defined in `db/schema.py`:
- `seasons`, `circuits`, `drivers`, `constructors` — reference tables
- `races` — one row per race (season, round, circuit, date)
- `results` — main-race finish per (race, driver), incl. fastest lap rank/time
- `sprint_results` — sprint finish per (race, driver) — **separate table; sprint points are NOT in `results.points`**
- `qualifying` — Q1/Q2/Q3 times per (race, driver)
- `pit_stops` — per-stop (race, driver, stop number)
- `driver_standings`, `constructor_standings` — championship standings per round
- `circuit_race_winners` — winner-only rows for every championship race 1950–today (denormalized); powers the Circuit Explorer's all-time stats independently of which full seasons are loaded
- `fetch_log` — when each endpoint was last fetched (drives 24h re-fetch on current year)

## Critical gotchas
- **Sprint points are in a separate table.** `results.points` is main-race only. Anywhere we sum points for a championship total, we have to UNION with `sprint_results.points` or join — otherwise totals don't match the official standings. Bug fixed twice (Championship Momentum, then Driver Profiles + Head-to-Head + GOAT + Era Comparison).
- **Pit-stop durations come in two formats.** Normal stops are seconds (`"22.630"`); long incidents (red flags, repairs) come back as `"M:SS.mmm"` like `"18:01.553"`. `_parse_pit_duration()` in `data/loader.py` handles both. The pit-stop chart filters anything > 120s out and lists them in an annotation above the chart so they don't dwarf normal stops.
- **Lapped cars don't have a comparable cumulative time at the leader's lap count.** `data/live.py::get_intervals` derives gap-to-leader from per-lap cumulative timestamps; a lapped driver ends up NaN. Time-to-Strike's `_gap_between` handles this with `pd.isna` checks.
- **`pd.merge_asof` chokes on NaN keys.** Drop NaN dates before any time-series merge (used in `gap_evolution_chart`).
- **Streamlit's `st.navigation` doesn't natively collapse section groups.** That's why `app.py` uses `position="hidden"` for routing only and renders the sidebar manually with `st.expander`.
- **`st.plotly_chart` is monkey-patched in `app.py`** so every chart gets `displayModeBar=True` + `displaylogo=False` without touching all 37 call sites.
- **Streamlit Cloud sleeps free-tier apps after ~7 days idle.** First visit after a long idle has a cold start.

## Theme
Pitwall — broadcast-style dark mode. F1 red (#E10600) accent on near-black (#0A0B0F).
- `.streamlit/config.toml` for the palette
- Custom CSS in `app.py` for typography (uppercase headings with red underline, monospace metric values, condensed all-caps section labels), sidebar styling, table borders
- Per-chart Plotly `hoverlabel` styling for consistent tooltips

## Completed
- [x] Repo structure, GitHub
- [x] SQLite schema + auto-init
- [x] Jolpica API loader with pagination + idempotent inserts
- [x] OpenF1 wrapper with per-endpoint caching
- [x] All 16 dashboard pages
- [x] Time-to-Strike predictor (formula + confidence model + UI)
- [x] Self-hosted deploy at boxbox.playastrova.com (Pi + Cloudflare Tunnel; was Streamlit Cloud until 2026-07-08)
- [x] Live SignalR production acceptance — full Belgian GP race streamed on the Pi, Time-to-Strike clean on live data (2026-07-19)
- [x] GitHub Actions auto-refresh (Mon/Wed)
- [x] Pitwall theme + custom collapsible sidebar
- [x] Track outlines via bacinger/f1-circuits
- [x] Predictions in browser localStorage
- [x] Sprint points fixed everywhere
- [x] Pit-stop M:SS duration parser
- [x] Driver Profiles + Head-to-Head split into current vs historical
- [x] What-If Single-Race-Override with cascade insertion
- [x] Gap-to-fastest chart instead of rank-bar chart
- [x] Stacked pit-stop chart with outlier filtering
- [x] Audi + Cadillac team colors for 2026
- [x] Live session detection — red LIVE badge in header, auto-refresh defaults ON during a live session, 10s interval pre-selected (2026-05-05)
- [x] Driver + teammate hover model on Standings/Momentum charts (replaced unified-hover that clipped 22 entries off-screen)
- [x] Sector colours on Live standings — purple = session best, green = personal best (2026-05-06)
- [x] Click-to-fill Time-to-Strike — clicking any standings row sets that driver as the chaser and the driver one position ahead as the target (2026-05-06)
- [x] Position movement strip — "Up: VER +3 (P12→P9)" / "Down: ALO -2 (P5→P7)" over the last 5 minutes (2026-05-06)
- [x] DRS naming retired — under 2026 regs DRS is replaced by manual override mode + active aero. Constant renamed `DRS_THRESHOLD_S` → `PROXIMITY_THRESHOLD_S`; verdict text updated. (2026-05-06)
- [x] Removed misleading start/finish marker from circuit outlines — bacinger GeoJSON doesn't encode start/finish, so the marker on coords[0] was random per circuit (2026-05-05)
- [x] Documentation refresh — README + CLAUDE.md (project-local) + project_notes.md created/updated
- [x] Cron shift to 06:13 UTC after the Mon-of-week-of-2026-05-06 GitHub runner-pool flake (top-of-hour cron contention)
- [x] **QA punch list (2026-05-06):**
  - Fixed Standings → Points Accumulation double-cumsum bug (was showing 237 for Antonelli at R4 instead of 100). `driver_standings.points` is already a season-to-date total; chart now plots it directly.
  - Era Comparison normalized chart now includes sprint points on both the actual and normalized sides via UNION + position re-mapping.
  - Page H1s aligned with sidebar labels: "Historical Comparison" → "Era Comparison"; "Safety & DNF Statistics" → "DNF Analysis".
  - Pitwall theme cleanup — replaced legacy `#E8002D` red with the new `#E10600` across `comparison_charts.py`, `12_Safety_Stats.py`, `7_GOAT_Calculator.py`, `6_Driver_Profiles.py`, `18_Driver_Profiles_Historical.py` (plus matching rgba fillcolors).
  - Head-to-Head charts now use each driver's actual team colour instead of fixed red/blue. New helper `queries.drivers.get_latest_constructor()` resolves the latest team per driver; the comparison_charts functions accept optional `d1_color` / `d2_color` kwargs threaded through both H2H pages.
  - Removed unused `PLOTLY_TEMPLATE` import from `pages/9_Race_Calendar.py`.
- [x] **Trivia subject exclusion (2026-05-06)** — `pages/10_Trivia.py` was picking each question via `ORDER BY RANDOM() LIMIT 1` with no exclusion list, so the same race / driver / circuit could come up multiple times in a 10-question session. Now tracks subjects (race_id / driver_id / circuit_id) per session in `st.session_state.trivia_seen` and adds `NOT IN` clauses on each pick query. Exclusion is cross-type, so a driver picked for `first_win_year` won't reappear as the subject of `win_count`. Reset on Play Again.
- [x] **Tire degradation in Time-to-Strike (2026-05-06)** — replaced the flat `ceil(gap / pace_delta)` with a lap-by-lap cumulative-advantage solver. New helpers in `queries/strike.py`: `_pace_and_deg` fits a line on the last 5 clean laps to recover (base_pace, deg_slope); `_laps_to_catch` walks forward, accumulating `(target_pace_k − chaser_pace_k)` until it covers the gap. With both slopes at 0 the math collapses to the old formula. Confidence layer factors in the deg-slope gap (`>= 0.05 s/lap²` widens the window, the inverse trims confidence) and adds an explanatory note. Live Race UI shows each driver's deg slope on the tire row. Returns `None` ("can't close") if the solver can't cover the gap within 80 projected laps — handles both the case where current pace is too thin AND the case where the chaser's own degradation will eat its advantage.
- [x] **Stale-deploy reboot fix (2026-05-06)** — H2H page broke on the cloud with a redacted ImportError after the QA-pass commit. Code was correct locally and `origin/main` was in sync; cause was Streamlit Cloud cached a partial deploy where the new page imports loaded but the updated `queries/drivers.py` (with `get_latest_constructor`) didn't. Manual reboot from the dashboard fixed it. Documented the pattern in `CLAUDE.md` under "Stale-deploy ImportError pattern".
- [x] **Driver Profiles + Head-to-Head dedupe (2026-05-07)** — the current/historical page pairs (`pages/6` ↔ `pages/18`, `pages/3` ↔ `pages/19`) were ~99% byte-identical, differing only in title/caption and `get_current_drivers` vs `get_all_drivers`. Extracted the shared bodies to a new `views/` layer (`views/driver_profile.py`, `views/head_to_head.py`) and reduced each of the four pages to a 13-line shim that calls `render(drivers, title, caption)`. Net: ~670 lines collapsed to ~351 with zero behaviour change. Stat additions or chart tweaks now touch one renderer instead of two pages, killing the drift risk that contributed to the 2026-05-06 ImportError.
- [x] **2026-05-23 — swap OpenF1 → FastF1 for live data** — OpenF1 changed its policy to gate all live-session data (including past sessions during a live event) behind a paid Stripe checkout, breaking the dashboard's marquee feature mid-race weekend. Swapped to FastF1, which taps F1's own SignalR feed (the source the broadcast uses) — free, community-maintained, no auth. New `data/live.py` reshapes FastF1's session-object model into the OpenF1-compatible DataFrame contracts the rest of the codebase expected, so `pages/14_Live_Race.py`, `queries/strike.py`, and the chart builders needed zero changes. `session_key` is now a `"year|gp|identifier"` string (e.g. `"2026|Monaco|R"`) instead of an int. Live integration test against Miami 2026 race confirmed Time-to-Strike still produces the correct verdict (NOR can't close on ANT, gap=3.24s, pace_delta=-0.29s/lap).
- [x] **2026-05-23 — architectural review pass** — deep code review surfaced three sprint-points UNION violations (`queries/drivers.py::get_head_to_head`, `queries/drivers.py::get_teammate_seasons`, `pages/8_What_If.py::get_season_results`), all fixed via LEFT JOIN on `sprint_results`. Also added explicit `numpy` to `requirements.txt` (was transitively pulled by pandas) and reworked loader failure handling: `load_qualifying` / `load_sprint_results` / `load_pit_stops_for_race` previously caught Exception then `_log_fetch(..., 0)` which marked the fetch complete forever — they now warn to stderr and let the next refresh retry. Round-level failures in `load_driver_standings` / `load_constructor_standings` now log + skip the final `_log_fetch` if any round failed. Added 21 strike-math unit tests in `tests/test_strike.py` covering `_laps_to_catch`, `_clean_laps`, `_pace_and_deg`, `_gap_between` + a `compute_strike` end-to-end smoke. **Scope cut:** removed GOAT Calculator, DNF Analysis, Trivia, Prediction Tracker (878 LOC) to focus on a polished current-season + historical-archive core; dropped `streamlit-local-storage` (Predictions was the only consumer). Page count: 18 → 14. Earlier Completed entries that mention removed files (Trivia subject exclusion, Pitwall theme cleanup citing `7_GOAT_Calculator.py` / `12_Safety_Stats.py`) describe past work and are kept as history.
- [x] **2026-06-26/28 — genuinely-live SignalR feed** — discovered the long-standing belief that polling F1's static `.jsonStream` files gave live data was **wrong**: those files 403 during a live session (`SessionInfo.json` → `ArchiveStatus: "Generating"`) and are only published *after* the session archives. Every "live" test that worked was actually a just-completed session's archive. The genuinely-live feed is F1's SignalR Core websocket (`wss://livetiming.formula1.com/signalrcore`). Built `data/f1_signalr.py`: `FreeSignalRClient` subclasses FastF1's client and connects with an **empty-string token factory** (FastF1's `no_auth=True` is broken in 3.8.3 — passes `None` where signalrcore needs a callable; the core timing topics stream without an F1TV token). A process-singleton background thread records the stream to a tempfile; `topic_entries` replays it through the existing `data/f1_live_client.py` parsers (`_fetch_stream` prefers a fresh recording, else the static archive). Added `_parse_ts` ISO handling, `_normalize_timing_line` (Sectors arrive list-in-snapshot / dict-in-delta, like Stints), `_is_live_now` gating (the feed is global, not addressable by session) + mtime freshness, a warm-up path (returns the empty live frame instead of a rate-limited FastF1 call while connecting), and a `get_drivers` no-cache-empty fix (its 600s TTL was pinning a warm-up empty and blanking the grid). 22-test suite pinned against a captured P2 sample (`tests/fixtures/signalr_p2_sample.txt`). **Verified working locally** against live P2 *and* the live Austrian GP race (lap 67, 22 cars). Cloud could never run it (network-layer WSS block — see Known Issues); **production-verified on the Pi during the 2026-07-19 Belgian GP race** (see the 2026-07-19 entry).
- [x] **2026-07-19 — Belgian GP race-day acceptance test (PASSED)** — first full live race since the Pi migration, monitored end-to-end by an autonomous watcher (`/opt/f1-dashboard/watch_race.py`, transient systemd unit `f1-race-watch`, own `F1_LIVE_RECORDING_DIR` so its in-process recorder never shares a file with the app's; JSONL log at `/opt/f1-dashboard/watch/watch.jsonl`). Results: recorder connected ~30s after the session went live and streamed the whole race (~4.6MB, 19k+ interval rows, 342 lap rows, 51 stint updates, all 22 drivers, `source: live` throughout); `compute_strike` ran every 60s on the top-10 adjacent pairs — 54 checks, zero exceptions, all verdict branches exercised with real data (full predictions with lap targets, "can't close", sub-second "overtake imminent", null-gap handling). **One real finding** (filed under Known Issues): a ~9-min mid-race feed stall from a half-dead websocket, self-recovered. Two cosmetic quirks: the P2→P1 pair often has no computable gap ("No live gap data yet"), and the `position` topic lags `intervals` slightly, so adjacent-pair selection can be one spot stale (absorbed by the "already ahead" branch).
- [x] **Jolpica pagination cap fix + 2022–2025 backfill (2026-05-07)** — discovered while spot-checking Max's career stats in the refactored Driver Profiles page: every modern season had only 5–6 rounds of `results`/`qualifying`/`sprint_results` populated. Two compounding bugs in `data/fetcher.py::_get`: (1) we requested `limit=1000` per page, but Jolpica silently caps page size at 100, so each fetch returned only ~5 races' worth of result rows; (2) the loop incremented `offset += limit` (the requested 1000) instead of the served limit (100), so the `offset >= total` exit condition tripped after one page. Fix: clamp the requested limit to 100 and advance offset by the API-echoed `served_limit`. Also added a 429 retry loop with exponential backoff after Jolpica rate-limited the backfill mid-stream. Backfilled 2022–2025 by deleting the stale `fetch_log` rows and re-running `load_season()` for each year — `INSERT OR IGNORE` filled in the missing rounds without disturbing the rows already there. Result counts went from 5–6 rounds/season to full coverage (22/22, 22/22, 24/24, 24/24). DB grew from ~544KB → ~944KB. Note: the durable `_already_fetched()` fix (so past years re-check their round counts instead of trusting fetch_log forever) is still pending.

## In Progress / Next Steps
- [ ] Unify pages still using "Season Tracker" / "Historical Comparison" / "Safety Stats" naming inside the page bodies (sidebar nav already renamed)
- [ ] Standings → points accumulation chart still reads from `driver_standings.points` — needs verification that those numbers actually include sprints
- [ ] Track outline rotation per circuit — F1.com diagrams are stylized rotations that don't match true North; would need a hand-curated rotation table per circuit.
- [ ] Equal-area projection for track outlines — currently uses raw lng/lat, which Mercator-squashes high-latitude tracks (Silverstone, Spa, Zandvoort) horizontally by ~30-40%. Easy fix: multiply X by `cos(latitude)`.
- [ ] **Live track map** — show driver positions on the track in real time, like F1's broadcast graphics. FastF1's `session.pos_data` provides X/Y/Z coordinates per driver at ~3-4 Hz. Phased approach:
  - Phase 1: snapshot map. Read pos_data after each refresh, plot dots per driver. Track outline derived from accumulated location points (the racing line traces it). ~80 LoC.
  - Phase 2: smooth animation between samples (Plotly animation frames or fast refresh loop).
  - Phase 3: calibrated overlay on the bacinger track outline. Requires per-circuit transformation matrix to map FastF1's local meters → bacinger's lat/lng. Could also be derived automatically by bounding-box alignment.
- [ ] Start/finish marker on track outlines — bacinger GeoJSON doesn't encode where start/finish is, so we can't reliably mark it. Removed the misleading marker from coords[0] for now. To put it back accurately we'd need either: (a) hand-curated index per circuit, or (b) use FastF1 position data to find the actual timing line.
- [ ] More live-race widgets: pit-window predictor, undercut/overcut calculator. (Note: under 2026 regs DRS is gone — overtaking uses manual override mode + active aero. No technical "within 1 second" trigger anymore.)
- [ ] Team radio playback — FastF1 doesn't expose team radio directly; would need to scrape F1's audio archive or wait for FastF1 to add it
- [ ] Speed trap mini-leaderboard — top 5 by `i1_speed`/`st_speed` from the laps payload

## Known Issues / To Fix
- **✅ RESOLVED (2026-07-08): self-hosted on the astrova Pi behind Cloudflare Tunnel** — live at https://boxbox.playastrova.com. The Fly.io plan below was superseded by the cheaper same-architecture route (whole app on hardware we already own). See Hosting / Infrastructure above and `deploy/pi-setup.md`. **Acceptance test PASSED 2026-07-19** during the Belgian GP race — recorder connected and streamed the full race from the Pi; see the dated entry under Completed. (Egress had been pre-verified: from the Pi, `livetiming.formula1.com` responds — signalrcore negotiate 405, TLS verifies — the exact path Cloud blocked is open.)

  **Root cause (kept for the record) — why Cloud never worked:** CONFIRMED 2026-07-05 during a live session, the `Recorder —` line read **`thread alive: True · ws connected: False · file: 0 bytes`** with no `last_error`. The handshake **never completes** — `_is_connected` never flips and the recorder sits in its connect-wait loop. This corrected the 2026-06-28 hypothesis (that Cloud let the handshake through and only dropped frames): the socket doesn't even open. Streamlit Community Cloud blocks outbound WSS to `livetiming.formula1.com` at the network layer. The feed streamed fine locally the same day (~2 KB/s, all 22 drivers) — purely a Cloud egress restriction, not F1-side or a code bug. No app change could fix it; the fix was moving hosts. No F1TV token needed — the free-token path (`lambda: ""`) is unchanged.

  **Prior plan (NOT taken — Fly.io):** a deep-research run ranked Fly.io top and a $5–7/mo VPS as runner-up. We went with the astrova Pi instead: $0, hardware on hand, and the game's existing Cloudflare Tunnel gave a public URL for one extra ingress line. Fly remains the fallback if the Pi is ever retired — `deploy/pi-setup.md` documents the portable systemd setup, and the same Docker-less approach maps onto a VPS.
- **No watchdog for a stalled-but-alive SignalR connection (found 2026-07-19, Belgian GP race)** — mid-race the websocket went half-dead: `ws_connected: True` but the recording file frozen at its last byte for ~5 min, so the mtime freshness gate marked the recording stale and parsed rows dropped to zero (the page would look frozen/empty). Recovery only happened because the thread eventually died and the next `ensure_recording` call started a fresh recorder (~9 min total outage, self-recovered). Fix idea for `data/f1_signalr.py`: if the recording file mtime goes stale while the thread still reports alive, proactively kill the client and reconnect. Also worth a look: the P2→P1 pair's gap often isn't computable live ("No live gap data yet") and `position` lags `intervals` slightly.
- **Track outline rotations** — orientations are geographically correct (North up) but don't match F1.com's stylized diagrams. Deferred — would need per-circuit rotation table.
- **Track outline aspect at high latitudes** — Mercator squash. See above.
- **Auto-refresh action** doesn't refresh `pit_stops` for new races. Pit stops are lazy-loaded by the Race Breakdown page on first visit per race (Jolpica returns them per round, not per season). Cold-start visitors hit a small delay.
- **Past race breakdowns load slowly** the first time — they hit Jolpica synchronously to lazy-fetch pit stops. Subsequent visits are instant.

## Notes / Gotchas
- `f1_data.db` IS committed (was originally gitignored — change made so the deploy ships with full historical data without needing a Load Data run on each container restart)
- `__pycache__/`, `.venv/`, `venv/`, `.env` all gitignored
- The `.devcontainer/` folder was auto-created by Streamlit Cloud — useful for one-click GitHub Codespaces editing
- Streamlit Cloud serves apps via SPA — static HTML probes won't show theme changes; need a real browser to verify visual updates
- Hard-reload (Ctrl+Shift+R) in the browser is necessary after theme/CSS changes — Streamlit's React bundle cache is aggressive
- The repo had to be made public on GitHub for free-tier Streamlit Cloud deploys — private repos require a paid plan
- The Streamlit Cloud "Workflows" PAT permission is separate from "Contents" — pushing `.github/workflows/*.yml` requires both

## Environment
- Ubuntu Linux (MacBook Pro hardware)
- Python via system `python3` (~3.12)
- Local `f1_data.db` shared with the deployed copy (committed in repo)
- Single GitHub account (`capy-arbs`); deploy is on the same account's Streamlit Cloud login

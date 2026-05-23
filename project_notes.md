# Box-Box (F1 Analytics Dashboard) — Project Notes

## Project Overview
Interactive Formula 1 dashboard that combines a complete historical archive (1950 to today) with live race-weekend timing data from the official F1 feed. Built as a personal project; the marquee feature is **Time-to-Strike**, a live predictor that estimates how many laps until a chasing driver catches the car ahead.

## Product Name
Box-Box
Live URL: https://box-box.streamlit.app
GitHub: https://github.com/capy-arbs/f1-data
Branch: `main` (single branch — every push redeploys to production)

## Hosting / Infrastructure
- **Streamlit Community Cloud** — free tier. Auto-redeploys within ~30 seconds of any push to `main`.
- **GitHub Actions** — `.github/workflows/refresh-data.yml` runs Mondays + Wednesdays at 06:00 UTC, refreshes the current season's data via Jolpica, and pushes the updated `f1_data.db` back to the repo. Manually triggerable from the Actions tab.
- **No backend / no auth** — Streamlit Cloud handles everything. App is public, listed as searchable on the platform.
- **No domain** — using the default `*.streamlit.app` subdomain (free).

## Live URLs / Resources
- App: https://box-box.streamlit.app
- Repo: https://github.com/capy-arbs/f1-data
- Streamlit Cloud admin: https://share.streamlit.io
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
- **SQLite** — local file `f1_data.db` (~544KB), shipped in the repo
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
f1_data.db                     SQLite (committed, ~544KB) — historical data 2015–present + 2026 ongoing

.streamlit/config.toml         Pitwall theme palette (F1 red on near-black)
.github/workflows/refresh-data.yml   Mon/Wed 06:00 UTC auto-refresh

db/
  connection.py                SQLite context manager (WAL mode, foreign keys on)
  schema.py                    Schema (12 tables) and idempotent init

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

pages/                         18 Streamlit pages (see Pages section)
```

## Data Sources
- **Jolpica** (`api.jolpi.ca/ergast/f1`) — historical F1 data, REST + JSON. Ergast API successor; same response shape. 1950–present, all rounds, qualifying, sprint, results, pit stops, standings.
- **FastF1** (https://github.com/theOehrly/Fast-F1) — Python library tapping F1's own SignalR live timing feed. Free, no API key, community-maintained. Loaded via `fastf1.get_session(year, gp, identifier).load()`. Disk-cached locally under `$FASTF1_CACHE` (default `/tmp/fastf1_cache`).
- **bacinger/f1-circuits** (GitHub) — MIT-licensed GeoJSON track outlines. Files named `{country_code}-{year}.geojson`. Mapped from our `circuit_id` via a hardcoded table in `data/track_geojson.py`, with a lat/lng nearest-neighbor fallback for unmapped IDs.

Both feeds are unaffiliated with Formula 1.

## Schema (SQLite)
12 tables, defined in `db/schema.py`:
- `seasons`, `circuits`, `drivers`, `constructors` — reference tables
- `races` — one row per race (season, round, circuit, date)
- `results` — main-race finish per (race, driver), incl. fastest lap rank/time
- `sprint_results` — sprint finish per (race, driver) — **separate table; sprint points are NOT in `results.points`**
- `qualifying` — Q1/Q2/Q3 times per (race, driver)
- `pit_stops` — per-stop (race, driver, stop number)
- `driver_standings`, `constructor_standings` — championship standings per round
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
- [x] All 18 dashboard pages
- [x] Time-to-Strike predictor (formula + confidence model + UI)
- [x] Streamlit Community Cloud deploy at box-box.streamlit.app
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

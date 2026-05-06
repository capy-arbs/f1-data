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
- **Monday 06:00 UTC** — catches Sunday race results once they've settled
- **Wednesday 06:00 UTC** — catches mid-week steward decisions, DSQs, post-race penalty changes that retroactively shift positions

The action calls `load_season(conn, current_year)`, which uses `INSERT OR IGNORE` for existing rows so re-runs are idempotent — only new races and changed standings get added.

The Home/Live Race page shows a "data may be stale" warning if the most-recent race in the DB is more than 14 days old.

## Tech Stack
- **Python 3.10+** (3.11 in CI via `actions/setup-python@v5`)
- **Streamlit 1.30+** (1.56 confirmed in dev) — multi-page app via `st.navigation`
- **Plotly** — every chart, with a monkey-patched modebar so reset-axes is always visible
- **SQLite** — local file `f1_data.db` (~544KB), shipped in the repo
- **Pandas** — DataFrame work everywhere
- **Requests** — HTTP for both data feeds
- **streamlit-local-storage** — browser localStorage component for predictions
- **Jolpica API** — historical F1 data (Ergast successor; 1950–present)
- **OpenF1 API** — live timing data (real-time gaps, intervals, sectors, stints, weather, race control). Free tier: 3 req/s, 30 req/min.
- **bacinger/f1-circuits** (MIT) — GeoJSON track outlines for the Circuit Explorer

## Architecture

Three layers, one job each:

```
data/      raw fetch + persistence (Jolpica REST + OpenF1 REST + GeoJSON)
queries/   pure SQL/compute helpers — no Streamlit, no I/O beyond the DB
charts/    Plotly figure builders — take DataFrames in, return Figures out
pages/     Streamlit views — orchestrate queries + charts, handle UI state
```

Two distinct data feeds:
- `data/fetcher.py` + `data/loader.py` — pulls historical data from Jolpica into local SQLite. One-time on first launch, then refreshed by the auto-refresh action.
- `data/live.py` — wraps OpenF1 endpoints with `@st.cache_data` per endpoint (TTLs 10–600s). Free-tier safe.

Time-to-Strike compute lives in `queries/strike.py` as a pure function returning a `StrikeResult` dataclass. The Live Race page renders the dataclass; nothing in the math layer knows about Streamlit.

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
  7_GOAT_Calculator.py                 GOAT Calculator
  8_What_If.py                         What-If Simulator (3 tabs)
  9_Race_Calendar.py                   Race Calendar
  10_Trivia.py                         Trivia
  11_Sprint_Analysis.py                Sprint Analysis
  12_Safety_Stats.py                   DNF Analysis (renamed in nav)
  13_Predictions.py                    Prediction Tracker (browser localStorage)
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
- **Play**: GOAT Calculator, What-If Simulator, Trivia, Prediction Tracker
- **Records & History**: Historical Driver Profiles, Historical Head-to-Head, Era Comparison, Pit Stop Records, Lap Time Evolution, DNF Analysis
- **Settings**: Load Data

## Files

```
app.py                         Entry point — page config, theme CSS, custom nav, plotly modebar patch
config.py                      API URLs, team colors (incl. Audi/Cadillac for 2026), point systems
requirements.txt               Pinned to streamlit, plotly, requests, pandas, streamlit-local-storage
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
  live.py                      OpenF1 live-timing wrapper (cached per endpoint)
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

pages/                         18 Streamlit pages (see Pages section)
```

## Data Sources
- **Jolpica** (`api.jolpi.ca/ergast/f1`) — historical F1 data, REST + JSON. Ergast API successor; same response shape. 1950–present, all rounds, qualifying, sprint, results, pit stops, standings.
- **OpenF1** (`api.openf1.org/v1`) — live timing feed mirrored from official F1 broadcast data. Free, no auth. Rate limit: 3 req/s, 30 req/min. Endpoints used: `sessions`, `drivers`, `intervals`, `position`, `laps`, `stints`, `pit`, `weather`, `race_control`, `team_radio`.
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
- **`gap_to_leader` from OpenF1 can be a string for lapped cars.** `"+1 LAP"` shows up where you expect a float. `data/live.py::get_intervals` coerces via `pd.to_numeric(errors="coerce")` so lapped cars become NaN.
- **`pd.merge_asof` chokes on NaN keys.** Drop NaN dates before any time-series merge (used in `gap_evolution_chart`).
- **Streamlit's `st.navigation` doesn't natively collapse section groups.** That's why `app.py` uses `position="hidden"` for routing only and renders the sidebar manually with `st.expander`.
- **`st.plotly_chart` is monkey-patched in `app.py`** so every chart gets `displayModeBar=True` + `displaylogo=False` without touching all 37 call sites.
- **Predictions are stored in browser localStorage**, not on the server. The previous `predictions.json` on the server got wiped on every Streamlit Cloud container restart and was shared across all visitors with no isolation.
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

## In Progress / Next Steps
- [ ] Unify pages still using "Season Tracker" / "Historical Comparison" / "Safety Stats" naming inside the page bodies (sidebar nav already renamed)
- [ ] Standings → points accumulation chart still reads from `driver_standings.points` — needs verification that those numbers actually include sprints
- [ ] What-If Driver Swap and Alternative Points System tabs only swap main-race results — sprint results stick with the original recipient. Either include sprints in the swap or document the asymmetry on-page.
- [ ] Track outline rotation per circuit — F1.com diagrams are stylized rotations that don't match true North; would need a hand-curated rotation table per circuit.
- [ ] Equal-area projection for track outlines — currently uses raw lng/lat, which Mercator-squashes high-latitude tracks (Silverstone, Spa, Zandvoort) horizontally by ~30-40%. Easy fix: multiply X by `cos(latitude)`.
- [ ] **Live track map** — show driver positions on the track in real time, like F1's broadcast graphics. OpenF1's `/v1/location` endpoint gives X/Y/Z coordinates at ~3-4 Hz per driver. Phased approach:
  - Phase 1: snapshot map. Poll location every few seconds, plot dots per driver. Track outline derived from accumulated location points (the racing line traces it). ~80 LoC.
  - Phase 2: smooth animation between samples (Plotly animation frames or fast refresh loop).
  - Phase 3: calibrated overlay on the bacinger track outline. Requires per-circuit transformation matrix to map OpenF1's local meters → bacinger's lat/lng. Could also be derived automatically by bounding-box alignment.
- [ ] Start/finish marker on track outlines — bacinger GeoJSON doesn't encode where start/finish is, so we can't reliably mark it. Removed the misleading marker from coords[0] for now. To put it back accurately we'd need either: (a) hand-curated index per circuit, or (b) use OpenF1 location data to find the actual timing line.
- [ ] More live-race widgets: pit-window predictor, undercut/overcut calculator. (Note: under 2026 regs DRS is gone — overtaking uses manual override mode + active aero. No technical "within 1 second" trigger anymore.)
- [ ] Tire degradation modeling for Time-to-Strike confidence

## Known Issues / To Fix
- **Track outline rotations** — orientations are geographically correct (North up) but don't match F1.com's stylized diagrams. Deferred — would need per-circuit rotation table.
- **Track outline aspect at high latitudes** — Mercator squash. See above.
- **Auto-refresh action** doesn't refresh `pit_stops` for new races. Pit stops are lazy-loaded by the Race Breakdown page on first visit per race (Jolpica returns them per round, not per season). Cold-start visitors hit a small delay.
- **Past race breakdowns load slowly** the first time — they hit Jolpica synchronously to lazy-fetch pit stops. Subsequent visits are instant.

## Notes / Gotchas
- `f1_data.db` IS committed (was originally gitignored — change made so the deploy ships with full historical data without needing a Load Data run on each container restart)
- `predictions.json` IS gitignored — predictions are now per-browser via localStorage anyway
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

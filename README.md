# Box-Box — F1 Analytics Dashboard

**Live: [box-box.streamlit.app](https://box-box.streamlit.app)**

A Formula 1 dashboard combining a complete historical archive (1950–today) with a real-time timing feed during race weekends. The marquee feature is **Time-to-Strike**, a live predictor that estimates how many laps a chasing driver needs to close on the car ahead.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/streamlit-1.30%2B-FF4B4B)
![Data](https://img.shields.io/badge/data-Jolpica%20%2B%20OpenF1-success)

---

## Time-to-Strike

The marquee feature. Pick a chaser and a target on track; the dashboard answers "how many laps until they catch up?"

The solver walks forward lap by lap, accumulating per-lap pace advantage until it covers the current gap. With both drivers' degradation slopes at zero this collapses to the simple flat formula; with real degradation it accounts for both cars' lap times trending up over the next stint.

```
Catches on smallest lap k such that
  Σ_{i=1..k} (target_pace_i − chaser_pace_i) ≥ gap_seconds
where pace_i for each driver = base_pace + deg_slope × i
```

- **gap_seconds** — chaser's `gap_to_leader` minus target's, taken from the most recent OpenF1 intervals snapshot.
- **base_pace + deg_slope** — a linear fit on the driver's last 5 clean laps. Pit-out laps and any lap more than 5% slower than the driver's own median are dropped first to reject yellow-flag noise. With fewer than 3 clean laps the slope falls back to 0 and the formula above collapses to `ceil(gap / pace_delta)`.
- **confidence** label (high / medium / low) layered on top, derived from the pace-delta magnitude, lap-time consistency, tire-age delta, degradation-slope gap, and close proximity (sub-second gaps signal overtake range). Every verdict ships with a bulleted list of *why* — so you can tell when the model is confident vs. when it's about to be wrong.

If the chaser isn't actually faster — or the cumulative advantage never covers the gap within an 80-lap projection window — the widget says so plainly ("can't close on current pace") rather than producing a meaningless number.

A "closest battles" leaderboard runs the same calculation across every adjacent pair on the grid in one shot.

## Features

### Live (during race weekends)
- **Live Race** — Real-time standings, gaps, intervals, lap times, tire stints, weather, and race control. Auto-refresh toggle; falls back to the most recent completed session when no race is running. Default landing page.
- **Time-to-Strike** widget (above) — embedded in Live Race.

### This Season
- **Standings** — Championship table with position progression and points-accumulation charts. Hover any driver line to see them and their teammate's value at that round.
- **Race Calendar** — Schedule with results filled in as races complete.
- **Race Breakdown** — Grid vs finish, gap-to-fastest lap, stacked pit stops, DNFs for any single race.
- **Sprint Analysis** — Sprint race results and sprint-vs-main-race performance (2021+).
- **Championship Momentum** — Rolling sum of points over the trailing N races; surfaces in-form drivers a leaderboard can't.

### Drivers
- **Driver Profiles** — Career summaries with season-by-season breakdowns. Filtered to the current grid.
- **Head-to-Head** — Compare two current drivers across careers, seasons, teammate stints.

### Circuits
- **Circuit Map** — F1.com-style track outlines (via the open-source bacinger/f1-circuits GeoJSON dataset), race history, and per-circuit records. Current/Past picker above the dropdown.

### Play
- **What-If Simulator** — Three thought experiments: give one driver another driver's whole season; replay a season under any historical points system; or override a single race's result and watch the standings cascade.

### Records & History
- **Historical Driver Profiles** — Full archive of every driver in the database.
- **Historical Head-to-Head** — Compare any two drivers across all eras.
- **Era Comparison** — Cross-era stats with normalized point systems and all-time records.
- **Pit Stop Records** — Fastest pit-stop leaderboard (2011+ data), filterable by season and team.
- **Lap Time Evolution** — Year-over-year fastest race lap at any circuit. Reveals regulation-era pace shifts.

### Settings
- **Load Data** — Manually pull seasons from the Jolpica API.

## Architecture

Three layers, each with one job:

```
data/      raw fetch + persistence (Jolpica REST + OpenF1 REST + GeoJSON)
queries/   pure SQL/compute helpers — no Streamlit, no I/O beyond the DB
charts/    Plotly figure builders — no I/O at all, take DataFrames in, return Figures out
pages/     Streamlit views — orchestrate queries + charts, handle UI state
```

Two distinct data feeds live in `data/`:

- **`data/fetcher.py` + `data/loader.py`** — pulls historical data from the Jolpica API into local SQLite. Loaded on first launch; refreshed by the GitHub Action.
- **`data/live.py`** — wraps OpenF1 endpoints for live timing. Each function is decorated with `@st.cache_data` and a TTL sized to how fast the underlying data changes (10 s for intervals, 30 s for stints, 600 s for the driver list, etc.). Free-tier rate limits are 3 req/s and 30 req/min — caching keeps a single user well under that ceiling.

The Time-to-Strike compute helpers live in `queries/strike.py` as a pure function returning a `StrikeResult` dataclass with verdict text, confidence label, and a `notes[]` list of factors. The Live Race page renders that dataclass; nothing in the math layer knows about Streamlit.

Track outlines come from the [bacinger/f1-circuits](https://github.com/bacinger/f1-circuits) GeoJSON repo (MIT licensed) — fetched on demand and cached.

## Data sources

- **[Jolpica API](https://api.jolpi.ca/ergast/f1)** — historical F1 data, 1950 to present. Ergast successor with the same response shape.
- **[OpenF1 API](https://openf1.org)** — live timing feed mirrored from the official F1 broadcast data. Free, no auth.
- **[bacinger/f1-circuits](https://github.com/bacinger/f1-circuits)** — MIT-licensed GeoJSON track outlines.

All three projects are unaffiliated with Formula 1.

## Local setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

The repository ships with a populated `f1_data.db` (~544 KB) so the dashboard works immediately on a fresh checkout. To rebuild from scratch (e.g. to pull a fresh season locally), open **Settings → Load Data** in the sidebar.

## Deployment

Hosted on [Streamlit Community Cloud](https://share.streamlit.io). Every push to `main` triggers a redeploy within ~30 seconds.

A GitHub Action (`.github/workflows/refresh-data.yml`) runs Mondays and Wednesdays at 06:00 UTC, refreshes the current season's data, and pushes any DB changes back to `main` — which triggers another redeploy. The Mon run catches Sunday race results once they settle; the Wed run catches mid-week steward decisions and post-race penalty changes that retroactively shift positions.

The Live Race page surfaces a "data may be stale" warning if the most-recent race in the DB is more than 14 days old.

## Project structure

```
app.py              Entry point — page config, theme CSS, custom nav, plotly modebar patch
config.py           API URLs, team colors, point systems
requirements.txt    Python dependencies
f1_data.db          SQLite (committed) — historical F1 data

.streamlit/
  config.toml       Pitwall theme palette
.github/workflows/
  refresh-data.yml  Auto-refresh data Mon/Wed 06:00 UTC

db/
  connection.py     SQLite context manager (WAL mode, foreign keys on)
  schema.py         Schema (12 tables) and idempotent init

data/
  fetcher.py        Jolpica API calls with pagination
  loader.py         Fetch -> transform -> insert orchestration
  normalizer.py     Cross-era point system recalculation
  live.py           OpenF1 live-timing wrapper (cached per endpoint)
  track_geojson.py  bacinger/f1-circuits track outline fetcher

queries/
  standings.py      Season standings & progression
  races.py          Race results, qualifying, pit stops
  drivers.py        Career stats, head-to-head, sprint-points helpers
  historical.py     Records, momentum, lap evolution
  circuits.py       Circuit data and race history
  strike.py         Time-to-Strike compute (pure, framework-free)

charts/
  season_charts.py     Position progression, points accumulation
  race_charts.py       Grid vs finish, gap-to-fastest, stacked pit stops
  comparison_charts.py H2H bars, cumulative wins, radar charts
  live_charts.py       Stint Gantt, pace trace, gap evolution

pages/              14 Streamlit pages
```

## License

Personal project, no warranty. F1, FORMULA 1, and related marks are trademarks of Formula One Licensing BV — this dashboard is unaffiliated with F1, the FIA, or any team.

# F1 Analytics Dashboard

**Live: [box-box.streamlit.app](https://box-box.streamlit.app)**

A Formula 1 dashboard that combines a complete historical archive (1950–present) with a real-time timing feed during race weekends. Built around a single distinctive feature — **Time-to-Strike**, a live predictor that estimates how many laps a chasing driver needs to close on the car ahead.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/streamlit-1.30%2B-FF4B4B)
![Data](https://img.shields.io/badge/data-Jolpica%20%2B%20OpenF1-success)

---

## Time-to-Strike

The marquee feature. Pick a chaser and a target on track; the dashboard answers "how many laps until they catch up?"

The math is intentionally transparent so the output stays interpretable:

```
laps_to_catch = ceil(gap_seconds / (target_pace - chaser_pace))
```

- **gap_seconds** — chaser's `gap_to_leader` minus target's, taken from the most recent OpenF1 intervals snapshot.
- **pace** — mean lap time over the last 5 clean laps. Pit-out laps and any lap more than 5% slower than the driver's own median are dropped to reject yellow-flag noise.
- **confidence** label (high / medium / low) layered on top, derived from the magnitude of the pace delta, lap-time consistency, tire-age delta, and DRS proximity. Every verdict ships with a bulleted list of *why* — so you can tell when the model is confident vs. when it's about to be wrong.

If the chaser isn't actually faster, the widget says so plainly ("can't close on current pace") rather than producing a meaningless number.

A "closest battles" leaderboard runs the same calculation across every adjacent pair on the grid in one shot.

## Features

### Live (during race weekends)
- **Live Race** — Real-time standings, gaps, intervals, lap times, tire stints, weather, and race control. Auto-refresh toggle; falls back to the most recent completed session when no race is running.
- **Time-to-Strike** widget (above) — embedded in Live Race.

### Season analysis
- **Season Standings** — Championship table with position progression and points accumulation charts.
- **Race Calendar** — Schedule with results filled in as races complete.
- **Race Breakdown** — Grid vs finish, fastest laps, pit stops, DNFs for any single race.
- **Sprint Analysis** — Sprint race results and sprint-vs-main-race performance (2021+).
- **Championship Momentum** — Rolling sum of points over the trailing N races; surfaces in-form drivers a leaderboard can't.

### Drivers and history
- **Driver Profiles** — Full career summaries with season-by-season breakdowns.
- **Head-to-Head** — Compare two drivers across careers, seasons, and teammate stints.
- **Era Comparison** — Cross-era stats with normalized point systems and all-time records.
- **GOAT Calculator** — Weighted ranking with adjustable sliders and radar charts.
- **Pit Stop Records** — Fastest pit stops leaderboard (2011+ data), filterable by season and team.
- **Lap Time Evolution** — Year-over-year fastest race lap at any circuit. Reveals regulation-era pace shifts at a glance.
- **Safety & DNF Stats** — Retirement trends, mechanical vs racing incidents, circuit danger rankings.
- **Circuit Explorer** — Per-circuit stats, location map, race history, and most successful drivers.

### Tools
- **What-If Simulator** — Swap driver results or apply alternate point systems to past seasons.
- **Prediction Tracker** — Log podium predictions before each race; the dashboard scores them when results land.
- **Trivia Quiz** — 10 randomly generated questions per round, drawn from the database.

## Screenshots

> Add screenshots to `docs/` and reference them here. Suggested captures: Live Race landing with the standings table, Time-to-Strike verdict card, Lap Time Evolution chart, Championship Momentum chart.

## Architecture

Three layers, each with one job:

```
data/      raw fetch + persistence (Jolpica REST + OpenF1 REST)
queries/   pure SQL/compute helpers — no Streamlit, no I/O beyond the DB
charts/    Plotly figure builders — no I/O at all, take DataFrames in, return Figures out
pages/     Streamlit views — orchestrate queries + charts, handle UI state
```

Two distinct data feeds live in `data/`:

- **`data/fetcher.py`** — pulls historical data from the Jolpica API (Ergast successor) into local SQLite. Loaded on demand from the **Load Data** page; covers 1950–present.
- **`data/live.py`** — wraps OpenF1 endpoints for live timing. Each function is decorated with `@st.cache_data` and a TTL sized to how fast the underlying data changes (10 s for intervals, 30 s for stints, 600 s for driver list, etc.). Free-tier rate limits are 3 req/s and 30 req/min — caching keeps a single user well under that ceiling.

The Time-to-Strike compute helpers live in `queries/strike.py` as a pure function returning a `StrikeResult` dataclass with verdict text, confidence label, and a `notes[]` list of factors. The Live Race page renders that dataclass; nothing in the math layer knows about Streamlit.

## Data sources

- **[Jolpica API](https://api.jolpi.ca/ergast/f1)** — historical F1 data, 1950 to present. Successor to the (deprecated) Ergast API; same response shape.
- **[OpenF1 API](https://openf1.org)** — live timing feed mirrored from the official F1 broadcast data. Free, no auth.

Both projects are unaffiliated with Formula 1.

## Local setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

The repository ships with a populated `f1_data.db` so the dashboard works immediately. To rebuild from scratch (e.g. to pull a fresh season), open **Load Data** in the sidebar and select which seasons to download.

## Deployment

Hosted on [Streamlit Community Cloud](https://share.streamlit.io). Every push to `main` triggers a redeploy within ~30 seconds. The committed SQLite database means the deployed app has full historical data immediately and doesn't need to re-fetch from Jolpica on cold start.

## Project structure

```
app.py              Main entry point — sidebar nav and landing metrics
config.py           API URLs, team colors, historical point systems
requirements.txt    Python dependencies

db/
  connection.py     SQLite context manager (WAL mode, foreign keys on)
  schema.py         Schema (12 tables) and idempotent init

data/
  fetcher.py        Jolpica API calls with pagination
  loader.py         Fetch -> transform -> insert orchestration
  normalizer.py     Cross-era point system recalculation
  live.py           OpenF1 live-timing wrapper (cached per endpoint)

queries/
  standings.py      Season standings and progression
  races.py          Race results, qualifying, pit stops
  drivers.py        Career stats, head-to-head, teammate records
  historical.py     Records, normalized stats, momentum, lap evolution
  circuits.py       Circuit data and race history
  strike.py         Time-to-Strike compute (pure, framework-free)

charts/
  season_charts.py     Position progression, points accumulation
  race_charts.py       Grid vs finish, fastest laps, pit stops
  comparison_charts.py H2H bars, cumulative wins, radar charts
  live_charts.py       Stint Gantt, pace trace, gap evolution

pages/              18 Streamlit pages, one per dashboard view
```

## License

Personal project, no warranty. F1, FORMULA 1, and related marks are trademarks of Formula One Licensing BV — this dashboard is unaffiliated with F1, the FIA, or any team.

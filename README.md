# F1 Analytics Dashboard

Interactive Formula 1 data dashboard built with Python, Streamlit, and Plotly. Covers F1 data from 1950 to present via the Jolpica API (Ergast successor).

## Features

**Live**
- **Live Race** — Real-time standings, gaps, intervals, tire strategy, weather, and race control via the OpenF1 API. Includes a **Time-to-Strike** widget that estimates how many laps until a chosen chaser catches a target, based on the current gap and recent pace differential. Auto-refreshes on a configurable interval; falls back to the most recent completed session when no race is running.

**Analysis**
- **Season Tracker** — Championship standings with position progression and points accumulation charts (team-colored)
- **Race Breakdown** — Grid vs finish positions, fastest laps, pit stops, DNF analysis
- **Head-to-Head** — Compare any two drivers across careers, seasons, and teammate stints
- **Historical Comparison** — Cross-era stats, normalized point systems, all-time records
- **Sprint Analysis** — Sprint race results, points, and sprint vs main race performance (2021+)
- **Championship Momentum** — Rolling sum of points over the trailing N races to surface in-form drivers
- **Pit Stop Records** — Fastest pit stops leaderboard, filterable by season and team (2011+ data)
- **Lap Time Evolution** — Year-over-year fastest race lap at any circuit; visualises regulation-era pace shifts

**Explore**
- **Circuit Explorer** — Circuit stats, location maps, race history, and most successful drivers per track
- **Driver Profiles** — Full career summaries with season-by-season breakdowns
- **Race Calendar** — Season schedule with results
- **Safety & DNF Stats** — Retirement trends, mechanical vs racing incidents, circuit danger rankings

**Fun**
- **GOAT Calculator** — Weighted ranking system with adjustable sliders and radar charts
- **What-If Simulator** — Swap driver results or apply alternate point systems
- **F1 Trivia Quiz** — 10 random database-generated questions
- **Prediction Tracker** — Log podium predictions and track accuracy

## Tech Stack

- **Python 3.10+**
- **Streamlit** — Dashboard framework
- **Plotly** — Interactive charts
- **SQLite** — Local data storage
- **Pandas** — Data manipulation
- **Jolpica API** — Historical F1 data source (1950–present)
- **OpenF1 API** — Live timing feed (gaps, intervals, sectors, stints, weather, race control)

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

On first launch, go to **Load Data** in the sidebar and select which seasons to download. Recommended: start with "Modern Era (2000–Now)" for the best experience.

## Project Structure

```
app.py              — Main entry point
config.py           — API URL, team colors, point systems
requirements.txt    — Dependencies

db/
  connection.py     — SQLite context manager
  schema.py         — Database schema (12 tables)

data/
  fetcher.py        — Jolpica API calls with pagination
  loader.py         — Fetch → transform → insert orchestration
  normalizer.py     — Cross-era point system recalculation
  live.py           — OpenF1 live-timing wrapper (cached per endpoint)

queries/
  standings.py      — Season standings & progression
  races.py          — Race results, qualifying, pit stops
  drivers.py        — Career stats, head-to-head, teammates
  historical.py     — Records, normalized stats, championships, momentum, lap evolution
  circuits.py       — Circuit data and race history
  strike.py         — Time-to-Strike compute helpers (live data)

charts/
  season_charts.py  — Position progression, points accumulation
  race_charts.py    — Grid vs finish, fastest laps, pit stops
  comparison_charts.py — H2H bars, cumulative wins, radar charts
  live_charts.py    — Stint Gantt, pace trace, gap-evolution

pages/              — 18 Streamlit pages
```

## How Time-to-Strike works

Given a chaser and target on track:

1. Pull the most recent `gap_to_leader` snapshot for each from OpenF1's `intervals` feed and difference them to get the live gap (s).
2. Estimate each driver's pace as the **mean of the last 5 clean laps** (pit-out laps and laps slower than 1.05× their own median are dropped — yellow-flag noise rejection).
3. `laps_to_catch = ceil(gap / (target_pace − chaser_pace))`. If the chaser isn't faster, the verdict is "can't close on current pace."
4. A confidence label (high/medium/low) is derived from the magnitude of the pace delta, the lap-time consistency of both drivers, the tire-age delta, and DRS proximity (gap ≤ 1.0s).

The output exposes its reasoning — every verdict comes with a list of factors so you can see when to trust it and when to disregard it (e.g. one driver about to pit, both on degrading tires, post-Safety-Car restart noise).

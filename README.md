# F1 Analytics Dashboard

Interactive Formula 1 data dashboard built with Python, Streamlit, and Plotly. Covers F1 data from 1950 to present via the Jolpica API (Ergast successor).

## Features

**Analysis**
- **Season Tracker** — Championship standings with position progression and points accumulation charts (team-colored)
- **Race Breakdown** — Grid vs finish positions, fastest laps, pit stops, DNF analysis
- **Head-to-Head** — Compare any two drivers across careers, seasons, and teammate stints
- **Historical Comparison** — Cross-era stats, normalized point systems, all-time records
- **Sprint Analysis** — Sprint race results, points, and sprint vs main race performance (2021+)

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
- **Jolpica API** — F1 data source (1950–present)

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

queries/
  standings.py      — Season standings & progression
  races.py          — Race results, qualifying, pit stops
  drivers.py        — Career stats, head-to-head, teammates
  historical.py     — Records, normalized stats, championships
  circuits.py       — Circuit data and race history

charts/
  season_charts.py  — Position progression, points accumulation
  race_charts.py    — Grid vs finish, fastest laps, pit stops
  comparison_charts.py — H2H bars, cumulative wins, radar charts

pages/              — 14 Streamlit pages
```

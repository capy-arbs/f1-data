# Box-Box (F1 Analytics Dashboard)

## What This Is
An F1 dashboard combining a complete historical archive (1950–today) with live race-weekend timing data from the official F1 feed. Marquee feature is **Time-to-Strike** — a live predictor that estimates how many laps until a chasing driver catches the car ahead, based on real-time gaps and recent pace differential.

Live at https://box-box.streamlit.app. Personal project, public repo, free Streamlit Community Cloud deploy.

## Architecture
- **Streamlit** multi-page app via `st.navigation` (custom sidebar with collapsible groups, see `app.py`)
- **SQLite** (`f1_data.db`, ~544KB, committed in repo) for historical data
- **Jolpica API** for historical (`api.jolpi.ca/ergast/f1`)
- **OpenF1 API** for live timing (`api.openf1.org/v1` — 3 req/s, 30 req/min free tier)
- **bacinger/f1-circuits** GeoJSON for track outlines
- **streamlit-local-storage** component for browser-side persisted predictions

Three-layer code structure:
- `data/` — fetch + persistence
- `queries/` — pure SQL/compute helpers, no Streamlit
- `charts/` — Plotly figure builders, take DataFrames return Figures
- `pages/` — Streamlit views, orchestrate the above

## Key Patterns & Conventions

### Sprint points are in a separate table
`results.points` is **main-race only**. Sprint points live in `sprint_results.points`. Anywhere we sum points for a championship total — career stats, season stats, GOAT scores, momentum totals — we have to UNION with `sprint_results` or the totals don't match the official standings. This bug has been hit twice. Helpers in `queries/drivers.py`:
- `_sprint_points_total(driver_id)` — career-long sprint points
- `_sprint_points_by_season(driver_id)` — per-year dict

Wins/podiums/poles stay main-race-only by F1 convention (sprint wins are tracked separately).

### Pit-stop durations come in two formats
- Normal: `"22.630"` (seconds as string)
- Long incidents: `"M:SS.mmm"` like `"18:01.553"` (red flag, repair, etc.)

`data/loader.py::_parse_pit_duration` handles both. The pit-stop chart filters anything > 120s out and lists them in an annotation above the chart so they don't dwarf normal stops.

### OpenF1 strings vs floats
`gap_to_leader` and `interval` come back as strings like `"+1 LAP"` for lapped cars. `data/live.py::get_intervals` coerces with `pd.to_numeric(errors="coerce")` so lapped values become NaN — handled downstream by Time-to-Strike's gap calc.

### `pd.merge_asof` chokes on NaN keys
Drop NaN dates before any time-series merge. Used in `gap_evolution_chart`.

### Custom sidebar nav
Streamlit's `st.navigation` doesn't natively collapse section groups. `app.py` uses `position="hidden"` to keep it as a router only, then renders the sidebar manually with `st.expander` per group. CSS in `app.py` hides Streamlit's auto-generated nav (`[data-testid="stSidebarNav"] { display: none }`).

### Plotly modebar is monkey-patched
`app.py` patches `st.plotly_chart` so every chart gets `displayModeBar=True` and `displaylogo=False` without touching the 37 individual call sites.

### Predictions live in the browser
`pages/13_Predictions.py` uses `streamlit-local-storage` to keep predictions per-browser. The previous `predictions.json` on the server got wiped on Streamlit Cloud container restarts and was shared across all visitors. `STORAGE_KEY = "f1_predictions_v1"`.

### Live data caching
Every function in `data/live.py` is wrapped in `@st.cache_data(ttl=...)` with a TTL sized to how fast the underlying data changes:
- `intervals`, `position`: 10s (live race rate)
- `laps`: 15s
- `stints`, `pit`: 30s
- `weather`: 20s
- `race_control`: 15s
- `drivers`: 600s (static per session)
- `sessions`: 300s

Manual "Refresh now" button on Live Race calls `fn.clear()` on each cached fetcher to bypass TTLs.

### Time-to-Strike formula
Implemented in `queries/strike.py` as a pure function returning `StrikeResult`. Core math:
```
laps_to_catch = ceil(gap_seconds / (target_pace − chaser_pace))
```
- `gap_seconds` = chaser's `gap_to_leader` − target's `gap_to_leader`
- `pace` = mean lap-time over last 5 clean laps (drops pit-out laps and laps > 1.05× the driver's median over a 10-lap window)

Confidence label (high/medium/low) is heuristic from pace-delta magnitude, lap-time stdev, tire-age delta, close proximity (sub-second gaps). The function fills `result.notes[]` so the UI can show *why* a verdict was given. Don't make the lap count itself smarter — add new signals to the confidence/notes layer instead.

**2026 reg note:** DRS no longer exists; overtaking uses manual override mode (electrical boost) plus active aero. There's no "within 1 second" technical trigger anymore, but a sub-second gap still indicates "overtake imminent" because slipstream + override windows favour the chaser at that range. The constant in `strike.py` is named `PROXIMITY_THRESHOLD_S`, not the legacy `DRS_THRESHOLD_S`.

## Theme
Pitwall — broadcast-style dark. F1 red (#E10600) on near-black (#0A0B0F).
- `.streamlit/config.toml` for the base palette
- Custom CSS in `app.py` for typography, sidebar gradient, metric-card styling, table borders
- Per-chart `hoverlabel` styling so tooltips match the theme
- Compound colors (Pirelli) defined in `charts/live_charts.py::COMPOUND_COLOURS`

Page titles get an automatic red underline via the `h1` CSS rule. Section subheaders are uppercased small caps. Metric values render in monospace for that timing-board feel.

## Hosting & Deploy
- **Streamlit Community Cloud** at https://box-box.streamlit.app — auto-redeploys ~30s after any push to `main`.
- **Single branch** workflow: `git push` deploys.
- **Public repo** on GitHub (free-tier Streamlit Cloud requirement).
- **Database is committed** (`f1_data.db`, ~544KB) so deploys ship with full historical data immediately.

### Auto-refresh action
`.github/workflows/refresh-data.yml` runs Mondays + Wednesdays at 06:00 UTC. Calls `load_season(conn, current_year)`, commits any DB changes as `f1-data-refresh-bot`, pushes — which triggers a Streamlit Cloud redeploy. Manually triggerable from the Actions tab.

The Mon refresh catches Sunday race results once they've settled. The Wed refresh catches mid-week steward decisions, DSQs, post-race penalty changes that retroactively shift positions.

The Live Race page shows a stale-data warning if the most-recent race in the DB is more than 14 days old.

## Page → File Map
The sidebar labels and page titles don't always match the file names because we've renamed pages without renumbering the files:

| Sidebar / URL                | File                                  |
|------------------------------|---------------------------------------|
| Live Race (default)          | pages/14_Live_Race.py                 |
| Standings                    | pages/1_Season_Tracker.py             |
| Race Calendar                | pages/9_Race_Calendar.py              |
| Race Breakdown               | pages/2_Race_Breakdown.py             |
| Sprint Analysis              | pages/11_Sprint_Analysis.py           |
| Championship Momentum        | pages/16_Championship_Momentum.py     |
| Driver Profiles (current)    | pages/6_Driver_Profiles.py            |
| Head-to-Head (current)       | pages/3_Head_to_Head.py               |
| Circuit Map                  | pages/5_Circuit_Map.py                |
| GOAT Calculator              | pages/7_GOAT_Calculator.py            |
| What-If Simulator            | pages/8_What_If.py                    |
| Trivia                       | pages/10_Trivia.py                    |
| Prediction Tracker           | pages/13_Predictions.py               |
| Historical Driver Profiles   | pages/18_Driver_Profiles_Historical.py|
| Historical Head-to-Head      | pages/19_Head_to_Head_Historical.py   |
| Era Comparison               | pages/4_Historical.py                 |
| Pit Stop Records             | pages/15_Pit_Stop_Records.py          |
| Lap Time Evolution           | pages/17_Lap_Time_Evolution.py        |
| DNF Analysis                 | pages/12_Safety_Stats.py              |
| Load Data                    | pages/0_Load_Data.py                  |

The numeric prefixes on the files no longer affect routing or order — `app.py`'s `GROUPS` dict is the single source of truth. The numbers are kept for compatibility / file-tree readability.

## Drivers split: current vs historical
- **Drivers** group in the nav: filtered to the most-recent season's grid via `queries/drivers.py::get_current_drivers()`.
- **Records & History** group: full archive via `get_all_drivers()`. Same rendering, different filter.

## Live Race page conventions

### Live session detection
`pages/14_Live_Race.py::_is_live(sess)` checks whether the session is currently in progress (current UTC between `date_start` and `date_end`). Used to:
- Show a red "LIVE" badge in the header
- Default the auto-refresh checkbox to ON
- Pre-select the 10s refresh interval (vs 15s for archived sessions)

`_time_since_end(sess)` formats human-readable "ended 2h ago" / "ended 3d ago" suffixes for finished-session headers.

### Sector colours on standings
S1/S2/S3 columns coloured via pandas `Styler.apply`:
- Purple (`rgba(139, 92, 246, 0.45)`) = session-best for that sector
- Green (`rgba(34, 197, 94, 0.35)`) = personal-best for that driver/sector
- Default = no colour

Bests are computed once from the full `laps` frame: session-best is `laps["duration_sector_N"].min()`, personal-best is per-driver `min()`. Comparisons round to 3dp because OpenF1 sometimes returns extra trailing precision.

### Click-to-fill Time-to-Strike
Standings dataframe uses `selection_mode="single-row"` + `on_select="rerun"`. Clicking any row populates the chaser picker with that driver and defaults the target to whoever is one position ahead. The selectboxes still allow override.

The Time-to-Strike block rebuilds the selectbox `key` based on the clicked row index — this forces Streamlit to re-render with the new default rather than keeping the user's previous selection sticky.

### Position movement strip
"Up: VER +3 (P12→P9)" / "Down: ALO -2 (P5→P7)" computed over the last 5 minutes of `position` events. Uses the data's own max timestamp as "now" rather than wall-clock time so the widget works on archived sessions too. Empty when nothing has changed in the window.

## Verification
- `streamlit run app.py` then click each section
- For the Time-to-Strike feature: defaults to the latest OpenF1 session; will fall back to the most recent completed race when no live race is running, so the page is never empty
- For sprint-point parity: Antonelli's 2026 total should be 100 (93 main + 7 sprint as of R4 Miami)
- For pit-stop outlier handling: Australia 2026 should show Stroll's stops 1, 2, 4 stacked, with stops 3 + Alonso's stop 2 listed in the annotation above the chart

## Don't
- Don't add docstrings or comments that re-state what well-named code already says
- Don't add fallback paths for things that can't happen (frameworks have invariants — trust them)
- Don't write to `predictions.json` on the server
- Don't drop the `legendgroup` / `legendgrouptitle_text` from multi-driver charts — they keep teammates grouped in the legend
- Don't switch to `hovermode="x unified"` on the Standings charts — 22 drivers don't fit; we use the driver+teammate model instead

## Future ideas (not started)
- **Live track map** — driver dots on the racing line via OpenF1's `/v1/location`. Phased plan in `project_notes.md`.
- Pit-window predictor (best lap to pit given tire age + traffic)
- Undercut/overcut calculator
- Tire degradation modeling for Time-to-Strike (currently flat-line pace)
- Equal-area projection for track outlines (Mercator-squash at high latitude)
- Per-circuit rotation table to match F1.com's stylized track diagrams
- Accurate start/finish marker on track outlines (bacinger GeoJSON doesn't encode the line — would need hand-curated index per circuit or OpenF1 timing-line data)
- Team radio playback — OpenF1's `team_radio` endpoint returns audio URLs

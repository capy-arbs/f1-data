# f1-dashboard reference

Moved out of `CLAUDE.md` (2026-08-18) so it is read on demand. Page-specific conventions
and the Time-to-Strike formula only matter when you are working on those surfaces.

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

"""Time-to-Strike: predict when a chasing driver will catch a target.

The core formula is intentionally simple so the output stays interpretable:

    laps_to_catch = ceil(gap_seconds / pace_advantage_per_lap)

Where ``pace_advantage_per_lap = pace(target) - pace(chaser)`` measured in
seconds per lap from recent clean laps. We then layer on signals — tire age
delta, lap-time consistency, close proximity, target's stint phase — to produce
a confidence label. The math is exposed in the returned ``factors`` dict so
the UI can show *why* it expects a given outcome rather than just a number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd


# Number of recent laps used to estimate pace. Long enough to reject one-off
# blips (lap-to-lap noise on the order of 0.3-0.5s), short enough that a stint
# change or tire degradation phase shows up quickly.
PACE_WINDOW = 5

# Outliers (yellow flags, lifts) — clip laps that are this much slower than
# the driver's median over the window before computing the mean.
OUTLIER_FACTOR = 1.05

# Proximity threshold (seconds). Under 2026 regs DRS is gone — overtaking
# uses manual override (electrical boost) instead, deployable anywhere with
# charge. There's no "within 1 second" technical trigger anymore, but a sub-
# second gap still indicates "overtake imminent" because slipstream and
# manual-override windows favour the chaser at that range.
PROXIMITY_THRESHOLD_S = 1.0


@dataclass
class StrikeResult:
    """Outcome of a Time-to-Strike calculation. All fields are JSON-safe."""
    chaser: str
    target: str
    gap_seconds: float | None
    chaser_pace: float | None
    target_pace: float | None
    pace_delta: float | None       # target_pace - chaser_pace; positive = chaser is faster
    laps_to_catch: int | None
    eta_seconds: float | None
    on_lap: int | None
    laps_remaining: int | None
    verdict: str = ""              # short headline, e.g. "Catches in 4 laps"
    confidence: str = "unknown"    # high | medium | low | unknown
    factors: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# -- Internal helpers -------------------------------------------------------

def _clean_laps(laps_df: pd.DataFrame, driver_number: int, window: int = PACE_WINDOW) -> pd.DataFrame:
    """Recent valid laps for one driver: drop pit in/out and outlier-slow laps."""
    if laps_df.empty:
        return laps_df

    d = laps_df[laps_df["driver_number"] == driver_number].copy()
    if d.empty:
        return d

    # Drop pit-out laps (slow) and any rows missing a lap_duration.
    d = d.dropna(subset=["lap_duration"])
    if "is_pit_out_lap" in d.columns:
        d = d[d["is_pit_out_lap"] != True]  # noqa: E712 — explicit boolean check

    if d.empty:
        return d

    d = d.sort_values("lap_number").tail(window * 2)  # take a wider slice, then prune outliers
    if d.empty:
        return d

    median = d["lap_duration"].median()
    d = d[d["lap_duration"] <= median * OUTLIER_FACTOR]
    return d.tail(window)


def _pace(laps_df: pd.DataFrame, driver_number: int, window: int = PACE_WINDOW) -> float | None:
    """Mean lap duration over the last ``window`` clean laps."""
    clean = _clean_laps(laps_df, driver_number, window=window)
    if clean.empty or len(clean) < 2:
        return None
    return float(clean["lap_duration"].mean())


def _consistency(laps_df: pd.DataFrame, driver_number: int) -> float | None:
    """Stdev of recent clean laps. Lower = more consistent = higher confidence."""
    clean = _clean_laps(laps_df, driver_number, window=PACE_WINDOW)
    if len(clean) < 3:
        return None
    return float(clean["lap_duration"].std(ddof=0))


def _gap_between(intervals_df: pd.DataFrame, chaser: int, target: int) -> float | None:
    """Time gap (s) chaser → target using the most recent gap_to_leader values.

    Positive value = target is ahead of chaser. None if either driver has no
    snapshot yet.
    """
    if intervals_df.empty:
        return None

    latest = (
        intervals_df.sort_values("date")
        .groupby("driver_number", as_index=False)
        .tail(1)
    )
    rows = latest.set_index("driver_number")
    if chaser not in rows.index or target not in rows.index:
        return None

    gc = rows.loc[chaser, "gap_to_leader"]
    gt = rows.loc[target, "gap_to_leader"]
    # Lapped cars come through as NaN (the API uses "+1 LAP" strings, coerced
    # to NaN in get_intervals). Treat that as "can't compute gap".
    if pd.isna(gc) or pd.isna(gt):
        return None
    try:
        return float(gc) - float(gt)
    except (TypeError, ValueError):
        return None


def _tire_info(stints_df: pd.DataFrame, laps_df: pd.DataFrame, driver_number: int) -> dict:
    """Current compound and tire age for a driver."""
    if stints_df.empty:
        return {"compound": None, "tyre_age": None}

    d = stints_df[stints_df["driver_number"] == driver_number]
    if d.empty:
        return {"compound": None, "tyre_age": None}

    cur = d.sort_values("stint_number").iloc[-1]
    current_lap = int(laps_df["lap_number"].max()) if not laps_df.empty else int(cur["lap_start"])
    age = int(cur["tyre_age_at_start"]) + max(0, current_lap - int(cur["lap_start"]))
    return {"compound": cur.get("compound"), "tyre_age": age}


def _confidence_label(
    pace_delta: float,
    chaser_consistency: float | None,
    target_consistency: float | None,
    chaser_age: int | None,
    target_age: int | None,
    gap: float,
) -> tuple[str, list[str]]:
    """Heuristic confidence rating with human-readable factors driving it."""
    notes: list[str] = []
    score = 0  # higher = more confident

    # Magnitude of pace delta vs. lap-to-lap noise. > 0.5 s/lap is a clear gap.
    if pace_delta >= 0.6:
        score += 2
        notes.append(f"Strong pace advantage (+{pace_delta:.2f} s/lap)")
    elif pace_delta >= 0.25:
        score += 1
        notes.append(f"Moderate pace advantage (+{pace_delta:.2f} s/lap)")
    else:
        notes.append(f"Marginal pace advantage (+{pace_delta:.2f} s/lap) — could swing either way")

    # Consistency: large stdev means recent laps are noisy.
    noise = max(chaser_consistency or 0.0, target_consistency or 0.0)
    if noise > 0:
        if noise < 0.3:
            score += 1
            notes.append(f"Both drivers running consistent laps (σ={noise:.2f}s)")
        elif noise > 0.8:
            score -= 1
            notes.append(f"Lap times unsettled (σ={noise:.2f}s) — pace estimate is shaky")

    # Tire age delta — fresher tires for the chaser supports a hold-up.
    if chaser_age is not None and target_age is not None:
        diff = target_age - chaser_age
        if diff >= 5:
            score += 1
            notes.append(f"Chaser is {diff} laps fresher on tires")
        elif diff <= -5:
            score -= 1
            notes.append(f"Target is {abs(diff)} laps fresher — degradation may flip the gap")

    # Sub-second gap — overtake window is open.
    if gap <= PROXIMITY_THRESHOLD_S:
        notes.append("Within 1 second — slipstream + override range")
        score += 1

    if score >= 3:
        return "high", notes
    if score >= 1:
        return "medium", notes
    return "low", notes


# -- Public API -------------------------------------------------------------

def compute_strike(
    chaser_number: int,
    target_number: int,
    intervals_df: pd.DataFrame,
    laps_df: pd.DataFrame,
    stints_df: pd.DataFrame,
    drivers_df: pd.DataFrame,
    total_laps: int | None = None,
) -> StrikeResult:
    """Predict laps until the chaser catches the target.

    Parameters
    ----------
    chaser_number, target_number : car numbers (e.g. 1, 4, 16)
    intervals_df : output of ``data.live.get_intervals``
    laps_df : output of ``data.live.get_laps``
    stints_df : output of ``data.live.get_stints``
    drivers_df : output of ``data.live.get_drivers`` — used for display names
    total_laps : optional total race distance to compute laps remaining
    """
    def _name(num: int) -> str:
        if drivers_df.empty:
            return str(num)
        row = drivers_df[drivers_df["driver_number"] == num]
        return row.iloc[0]["name_acronym"] if not row.empty else str(num)

    result = StrikeResult(
        chaser=_name(chaser_number),
        target=_name(target_number),
        gap_seconds=None,
        chaser_pace=None,
        target_pace=None,
        pace_delta=None,
        laps_to_catch=None,
        eta_seconds=None,
        on_lap=None,
        laps_remaining=None,
    )

    gap = _gap_between(intervals_df, chaser_number, target_number)
    chaser_pace = _pace(laps_df, chaser_number)
    target_pace = _pace(laps_df, target_number)

    result.gap_seconds = gap
    result.chaser_pace = chaser_pace
    result.target_pace = target_pace

    chaser_tire = _tire_info(stints_df, laps_df, chaser_number)
    target_tire = _tire_info(stints_df, laps_df, target_number)
    result.factors = {
        "chaser_compound": chaser_tire["compound"],
        "chaser_tyre_age": chaser_tire["tyre_age"],
        "target_compound": target_tire["compound"],
        "target_tyre_age": target_tire["tyre_age"],
    }

    # Bail-out conditions ---------------------------------------------------
    if gap is None:
        result.verdict = "No live gap data yet"
        return result
    if gap <= 0:
        result.verdict = f"{result.chaser} is already ahead of {result.target}"
        return result
    if chaser_pace is None or target_pace is None:
        result.verdict = "Not enough laps to estimate pace"
        result.notes.append(f"Need at least {PACE_WINDOW} laps each. Try again in a few laps.")
        return result

    pace_delta = target_pace - chaser_pace
    result.pace_delta = pace_delta

    if pace_delta <= 0.05:
        # Chaser isn't meaningfully faster — even a tiny pace deficit means no catch.
        result.verdict = f"{result.chaser} can't close on current pace"
        result.confidence = "high" if pace_delta < -0.1 else "low"
        result.notes.append(
            f"Pace delta is {pace_delta:+.2f} s/lap. "
            "Catching requires the target to slow (degradation, traffic, pit) or the chaser to find time."
        )
        return result

    laps_to_catch = math.ceil(gap / pace_delta)
    eta_seconds = laps_to_catch * chaser_pace

    current_lap = int(laps_df["lap_number"].max()) if not laps_df.empty else 0
    on_lap = current_lap + laps_to_catch
    laps_remaining = (total_laps - current_lap) if total_laps else None

    result.laps_to_catch = laps_to_catch
    result.eta_seconds = eta_seconds
    result.on_lap = on_lap
    result.laps_remaining = laps_remaining

    if laps_remaining is not None and laps_to_catch > laps_remaining:
        result.verdict = f"Won't catch before flag (needs {laps_to_catch}, only {laps_remaining} left)"
    elif laps_to_catch <= 1 and gap <= PROXIMITY_THRESHOLD_S:
        result.verdict = f"Within 1 second — overtake imminent"
    elif laps_to_catch == 1:
        result.verdict = f"Catches {result.target} on the next lap"
    else:
        result.verdict = f"Catches {result.target} in ~{laps_to_catch} laps (lap {on_lap})"

    confidence, why = _confidence_label(
        pace_delta=pace_delta,
        chaser_consistency=_consistency(laps_df, chaser_number),
        target_consistency=_consistency(laps_df, target_number),
        chaser_age=chaser_tire["tyre_age"],
        target_age=target_tire["tyre_age"],
        gap=gap,
    )
    result.confidence = confidence
    result.notes.extend(why)

    return result


def all_strike_pairs(
    grid_df: pd.DataFrame,
    intervals_df: pd.DataFrame,
    laps_df: pd.DataFrame,
    stints_df: pd.DataFrame,
    drivers_df: pd.DataFrame,
    total_laps: int | None = None,
    only_close: bool = True,
) -> pd.DataFrame:
    """Compute Time-to-Strike for every adjacent pair on the grid.

    Useful as a leaderboard ("which battle is closest?"). When ``only_close``
    is True, returns just the pairs where the chaser is faster than the target.
    """
    if grid_df.empty or "position" not in grid_df.columns:
        return pd.DataFrame()

    ordered = grid_df.dropna(subset=["position"]).sort_values("position")
    rows = []
    pairs = list(zip(ordered.iloc[1:].itertuples(index=False), ordered.iloc[:-1].itertuples(index=False)))
    for chaser, target in pairs:
        res = compute_strike(
            int(chaser.driver_number),
            int(target.driver_number),
            intervals_df, laps_df, stints_df, drivers_df,
            total_laps=total_laps,
        )
        rows.append({
            "Chaser": res.chaser,
            "Target": res.target,
            "Gap (s)": res.gap_seconds,
            "Δ Pace (s/lap)": res.pace_delta,
            "Laps to Catch": res.laps_to_catch,
            "Verdict": res.verdict,
            "Confidence": res.confidence,
        })

    df = pd.DataFrame(rows)
    if only_close and not df.empty:
        df = df[df["Laps to Catch"].notna()]
    return df.reset_index(drop=True)

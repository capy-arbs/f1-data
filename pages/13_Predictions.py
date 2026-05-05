"""Prediction Tracker — log race predictions and track accuracy.

Predictions are stored in the **browser's localStorage** (per-browser, not
on the server). This means:
  - Each visitor's predictions are isolated from everyone else's.
  - Predictions survive container restarts on Streamlit Cloud (the previous
    server-side predictions.json was wiped whenever the container slept).
  - Predictions don't follow you across devices — that's the trade-off for
    not requiring an account.
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st
from streamlit_local_storage import LocalStorage

from db.schema import init_db
from db.connection import get_db
from queries.standings import get_available_seasons, get_rounds_for_season

init_db()

st.title("Prediction Tracker")
st.markdown("Log your podium predictions before each race and see how accurate you are over time.")

STORAGE_KEY = "f1_predictions_v1"
storage = LocalStorage()


# -- Storage helpers (browser localStorage via component) ------------------

def load_predictions() -> dict:
    """Pull the predictions dict out of localStorage, or {} if nothing stored.

    The component returns the raw stored string; we JSON-decode here.
    First render of a fresh session may return None — Streamlit reruns
    automatically once the component reports its real value.
    """
    raw = storage.getItem(STORAGE_KEY)
    if raw is None or raw == "":
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def save_predictions(data: dict) -> None:
    storage.setItem(STORAGE_KEY, json.dumps(data))


def get_drivers_for_season(season: int) -> list[str]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT d.given_name || ' ' || d.family_name as name
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            JOIN races r ON res.race_id = r.race_id
            WHERE r.season = ?
            ORDER BY d.family_name
            """,
            (season,),
        ).fetchall()
    return [r["name"] for r in rows]


def get_actual_result(season: int, round_num: int) -> dict | None:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT res.position, d.given_name || ' ' || d.family_name as driver
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            JOIN drivers d ON res.driver_id = d.driver_id
            WHERE r.season = ? AND r.round = ? AND res.position IS NOT NULL
            ORDER BY res.position
            LIMIT 3
            """,
            (season, round_num),
        ).fetchall()
    if not rows:
        return None
    return {
        "p1": rows[0]["driver"] if len(rows) > 0 else None,
        "p2": rows[1]["driver"] if len(rows) > 1 else None,
        "p3": rows[2]["driver"] if len(rows) > 2 else None,
    }


seasons = get_available_seasons()
if not seasons:
    st.warning("No data loaded.")
    st.stop()

predictions = load_predictions()

tab1, tab2 = st.tabs(["Make Predictions", "Track Accuracy"])

with tab1:
    st.subheader("Log a Prediction")
    season = st.selectbox("Season", seasons, key="pred_season")
    rounds = get_rounds_for_season(season)
    if not rounds:
        st.warning("No races found.")
        st.stop()

    round_opts = {f"R{r['round']}: {r['race_name']}": r["round"] for r in rounds}
    selected = st.selectbox("Race", list(round_opts.keys()), key="pred_race")
    round_num = round_opts[selected]

    drivers = get_drivers_for_season(season)
    if not drivers:
        st.info("No driver data for this season.")
        st.stop()

    key = f"{season}_{round_num}"
    existing = predictions.get(key)

    if existing:
        st.success(
            f"You already predicted: P1: {existing.get('p1')}, "
            f"P2: {existing.get('p2')}, P3: {existing.get('p3')}"
        )
        if st.button("Clear prediction"):
            del predictions[key]
            save_predictions(predictions)
            st.rerun()
    else:
        st.markdown("**Predict the podium:**")
        col1, col2, col3 = st.columns(3)
        p1 = col1.selectbox("P1 (Winner)", drivers, key="p1")
        p2 = col2.selectbox("P2", [d for d in drivers if d != p1], key="p2")
        remaining = [d for d in drivers if d not in (p1, p2)]
        p3 = col3.selectbox("P3", remaining, key="p3")

        if st.button("Save Prediction", type="primary"):
            predictions[key] = {
                "season": season,
                "round": round_num,
                "race": selected.split(": ", 1)[1],
                "p1": p1,
                "p2": p2,
                "p3": p3,
                "timestamp": datetime.now().isoformat(),
            }
            save_predictions(predictions)
            st.success("Prediction saved to your browser.")
            st.rerun()

with tab2:
    st.subheader("Prediction Accuracy")

    if not predictions:
        st.info("No predictions logged yet — go make some.")
        st.stop()

    results = []
    for key, pred in predictions.items():
        actual = get_actual_result(pred["season"], pred["round"])
        score = 0
        details = {"Race": pred.get("race", key), "Season": pred["season"]}
        details["Pred P1"] = pred["p1"]
        details["Pred P2"] = pred["p2"]
        details["Pred P3"] = pred["p3"]

        if actual:
            details["Actual P1"] = actual["p1"]
            details["Actual P2"] = actual["p2"]
            details["Actual P3"] = actual["p3"]
            actual_podium = [actual["p1"], actual["p2"], actual["p3"]]
            for pos in ("p1", "p2", "p3"):
                if pred[pos] == actual[pos]:
                    score += 3  # exact spot
                elif pred[pos] in actual_podium:
                    score += 1  # right driver, wrong spot
            details["Score"] = f"{score}/9"
        else:
            details["Actual P1"] = "—"
            details["Actual P2"] = "—"
            details["Actual P3"] = "—"
            details["Score"] = "Pending"

        results.append(details)

    results_df = pd.DataFrame(results)
    st.dataframe(results_df, hide_index=True, use_container_width=True)

    scored = [r for r in results if r["Score"] != "Pending"]
    if scored:
        total_score = sum(int(r["Score"].split("/")[0]) for r in scored)
        max_score = len(scored) * 9
        accuracy = 100 * total_score / max_score if max_score > 0 else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Predictions Made", len(scored))
        m2.metric("Total Score", f"{total_score}/{max_score}")
        m3.metric("Accuracy", f"{accuracy:.1f}%")

        perfect = sum(1 for r in scored if r["Score"] == "9/9")
        if perfect > 0:
            st.success(f"Perfect predictions: {perfect}")

    with st.expander("Reset all predictions"):
        st.caption("Clears every prediction stored in your browser. Cannot be undone.")
        if st.button("Wipe all predictions", type="secondary"):
            storage.setItem(STORAGE_KEY, json.dumps({}))
            st.rerun()

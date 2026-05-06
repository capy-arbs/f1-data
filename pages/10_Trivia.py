"""F1 Trivia — test your knowledge with database-generated questions."""

import streamlit as st
import random

from db.schema import init_db
from db.connection import get_db

init_db()

st.title("F1 Trivia Quiz")


def _placeholders(values) -> str:
    return ",".join("?" * len(values))


def generate_question(conn, seen: dict) -> dict | None:
    """Generate a random trivia question, skipping subjects already asked.

    ``seen`` carries per-kind id sets across one quiz session so the same
    race / driver / circuit doesn't show up twice — even across question
    types (e.g. a driver in `first_win_year` won't reappear in `win_count`).
    """
    # Try each type in random order so we don't get stuck if one is exhausted
    # for the loaded data.
    types = ["race_winner", "first_win_year", "win_count", "circuit_country"]
    random.shuffle(types)

    for qtype in types:
        q = _try_question(conn, qtype, seen)
        if q is not None:
            return q
    return None


def _try_question(conn, qtype: str, seen: dict) -> dict | None:
    if qtype == "race_winner":
        seen_races = seen["races"]
        excl = f"AND r.race_id NOT IN ({_placeholders(seen_races)})" if seen_races else ""
        race = conn.execute(
            f"""
            SELECT r.race_id, r.season, r.race_name,
                   d.given_name || ' ' || d.family_name as winner,
                   d.driver_id
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            JOIN drivers d ON res.driver_id = d.driver_id
            WHERE res.position = 1 {excl}
            ORDER BY RANDOM() LIMIT 1
            """,
            list(seen_races),
        ).fetchone()
        if not race:
            return None

        wrong = conn.execute(
            """
            SELECT DISTINCT d.given_name || ' ' || d.family_name as name
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            JOIN drivers d ON res.driver_id = d.driver_id
            WHERE r.season = ? AND d.driver_id != ?
            ORDER BY RANDOM() LIMIT 3
            """,
            (race["season"], race["driver_id"]),
        ).fetchall()

        options = [race["winner"]] + [w["name"] for w in wrong]
        random.shuffle(options)
        return {
            "question": f"Who won the {race['season']} {race['race_name']}?",
            "options": options,
            "answer": race["winner"],
            "subject_kind": "races",
            "subject_id": race["race_id"],
        }

    if qtype == "first_win_year":
        seen_drivers = seen["drivers"]
        excl = f"AND res.driver_id NOT IN ({_placeholders(seen_drivers)})" if seen_drivers else ""
        driver = conn.execute(
            f"""
            SELECT res.driver_id,
                   d.given_name || ' ' || d.family_name as name,
                   MIN(r.season) as first_win_year
            FROM results res
            JOIN races r ON res.race_id = r.race_id
            JOIN drivers d ON res.driver_id = d.driver_id
            WHERE res.position = 1 {excl}
            GROUP BY res.driver_id
            HAVING COUNT(*) >= 3
            ORDER BY RANDOM() LIMIT 1
            """,
            list(seen_drivers),
        ).fetchone()
        if not driver:
            return None

        correct = driver["first_win_year"]
        wrong_years = list(set([correct + random.randint(-5, 5) for _ in range(10)]) - {correct})
        random.shuffle(wrong_years)
        options = [correct] + wrong_years[:3]
        options = [str(o) for o in options]
        random.shuffle(options)
        return {
            "question": f"In what year did {driver['name']} win their first Grand Prix?",
            "options": options,
            "answer": str(correct),
            "subject_kind": "drivers",
            "subject_id": driver["driver_id"],
        }

    if qtype == "win_count":
        seen_drivers = seen["drivers"]
        excl = f"WHERE res.driver_id NOT IN ({_placeholders(seen_drivers)})" if seen_drivers else ""
        driver = conn.execute(
            f"""
            SELECT res.driver_id,
                   d.given_name || ' ' || d.family_name as name,
                   SUM(CASE WHEN res.position = 1 THEN 1 ELSE 0 END) as wins
            FROM results res
            JOIN drivers d ON res.driver_id = d.driver_id
            {excl}
            GROUP BY res.driver_id
            HAVING wins >= 5
            ORDER BY RANDOM() LIMIT 1
            """,
            list(seen_drivers),
        ).fetchone()
        if not driver:
            return None

        correct = driver["wins"]
        offsets = random.sample(range(1, 15), min(6, 14))
        wrong_counts = list(set([max(0, correct + random.choice([-1, 1]) * o) for o in offsets]) - {correct})
        random.shuffle(wrong_counts)
        options = [str(correct)] + [str(w) for w in wrong_counts[:3]]
        random.shuffle(options)
        return {
            "question": f"How many Grand Prix wins does {driver['name']} have?",
            "options": options,
            "answer": str(correct),
            "subject_kind": "drivers",
            "subject_id": driver["driver_id"],
        }

    if qtype == "circuit_country":
        seen_circuits = seen["circuits"]
        excl = f"AND circuit_id NOT IN ({_placeholders(seen_circuits)})" if seen_circuits else ""
        circuit = conn.execute(
            f"""
            SELECT circuit_id, name, country FROM circuits
            WHERE country IS NOT NULL {excl}
            ORDER BY RANDOM() LIMIT 1
            """,
            list(seen_circuits),
        ).fetchone()
        if not circuit:
            return None

        wrong = conn.execute(
            """
            SELECT DISTINCT country FROM circuits
            WHERE country != ? AND country IS NOT NULL
            ORDER BY RANDOM() LIMIT 3
            """,
            (circuit["country"],),
        ).fetchall()

        options = [circuit["country"]] + [w["country"] for w in wrong]
        random.shuffle(options)
        return {
            "question": f"In which country is the {circuit['name']}?",
            "options": options,
            "answer": circuit["country"],
            "subject_kind": "circuits",
            "subject_id": circuit["circuit_id"],
        }

    return None


# Session state
if "trivia_score" not in st.session_state:
    st.session_state.trivia_score = 0
if "trivia_total" not in st.session_state:
    st.session_state.trivia_total = 0
if "trivia_question" not in st.session_state:
    st.session_state.trivia_question = None
if "trivia_answered" not in st.session_state:
    st.session_state.trivia_answered = False
if "trivia_finished" not in st.session_state:
    st.session_state.trivia_finished = False
if "trivia_seen" not in st.session_state:
    st.session_state.trivia_seen = {"races": set(), "drivers": set(), "circuits": set()}

TOTAL_QUESTIONS = 10

# Score display
col1, col2, col3 = st.columns(3)
col1.metric("Score", f"{st.session_state.trivia_score}/{st.session_state.trivia_total}")
col2.metric("Remaining", TOTAL_QUESTIONS - st.session_state.trivia_total)
if st.session_state.trivia_total > 0:
    pct = round(100 * st.session_state.trivia_score / st.session_state.trivia_total)
    col3.metric("Accuracy", f"{pct}%")

st.divider()

# Game finished
if st.session_state.trivia_finished:
    score = st.session_state.trivia_score
    st.subheader("Quiz Complete!")

    if score == 10:
        st.markdown("### Perfect Score! You're basically a walking F1 encyclopedia.")
    elif score >= 8:
        st.markdown("### Excellent! You know your stuff. Toto Wolff would be impressed.")
    elif score >= 6:
        st.markdown("### Not bad! You're a solid fan. Keep watching those races.")
    elif score >= 4:
        st.markdown("### Room for improvement. Maybe binge some F1 documentaries?")
    else:
        st.markdown("### Oof. Are you sure you've watched F1 before? No judgment. Okay, a little judgment.")

    if st.button("Play Again", type="primary"):
        st.session_state.trivia_score = 0
        st.session_state.trivia_total = 0
        st.session_state.trivia_question = None
        st.session_state.trivia_answered = False
        st.session_state.trivia_finished = False
        st.session_state.trivia_seen = {"races": set(), "drivers": set(), "circuits": set()}
        st.rerun()
    st.stop()

# Generate new question if needed
if st.session_state.trivia_question is None:
    with get_db() as conn:
        q = generate_question(conn, st.session_state.trivia_seen)
    if q is None:
        st.warning("Not enough data to generate questions. Load more seasons!")
        st.stop()
    st.session_state.trivia_seen[q["subject_kind"]].add(q["subject_id"])
    st.session_state.trivia_question = q
    st.session_state.trivia_answered = False

q = st.session_state.trivia_question

st.subheader(f"Question {st.session_state.trivia_total + 1} of {TOTAL_QUESTIONS}")
st.markdown(f"**{q['question']}**")

# Answer buttons
if not st.session_state.trivia_answered:
    for option in q["options"]:
        if st.button(option, key=f"opt_{option}", use_container_width=True):
            st.session_state.trivia_answered = True
            st.session_state.trivia_total += 1
            if option == q["answer"]:
                st.session_state.trivia_score += 1
                st.session_state.trivia_last_correct = True
            else:
                st.session_state.trivia_last_correct = False
            st.rerun()
else:
    if st.session_state.trivia_last_correct:
        st.success(f"Correct! The answer is **{q['answer']}**")
    else:
        st.error(f"Wrong! The answer was **{q['answer']}**")

    if st.session_state.trivia_total >= TOTAL_QUESTIONS:
        st.session_state.trivia_finished = True
        st.rerun()
    else:
        if st.button("Next Question", type="primary"):
            st.session_state.trivia_question = None
            st.rerun()

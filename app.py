"""
Weekly quiz app for the Reinforcement Learning assignments.

Run locally:    streamlit run app.py
Question banks: questions/<year>.json, one file per year (each year is kept separate)
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------
st.set_page_config(page_title="RL Weekly Quiz", page_icon="🧠", layout="wide")

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "questions"
SECONDS_PER_QUESTION = 90          # exam time budget per question
PRACTICE, EXAM, BOSS = "practice", "exam", "Final Boss 💀"

CSS = """
<style>
.block-container {max-width: 980px; padding-top: 2rem;}
.fb {padding: .7rem 1rem; border-radius: 8px; border-left: 6px solid; margin: .4rem 0 .6rem;
     font-weight: 500; line-height: 1.45;}
.fb-correct {background: rgba(34,139,84,.13); border-color: #22a35a;}
.fb-wrong   {background: rgba(214,57,57,.13); border-color: #d63939;}
.fb-skip    {background: rgba(140,140,140,.15); border-color: #8c8c8c;}
.tag {display:inline-block; font-size:.78rem; padding:.1rem .5rem; border-radius:999px;
      border:1px solid rgba(128,128,128,.45); margin-left:.4rem; vertical-align:middle;}
[data-testid="stMetric"] {border:1px solid rgba(128,128,128,.25); border-radius:10px;
      padding:.6rem .9rem;}
</style>
"""


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
@st.cache_data
def load_banks(data_dir: str = str(DATA_DIR)) -> dict[int, dict]:
    """Load every questions/<year>.json file and validate it."""
    banks: dict[int, dict] = {}
    problems: list[str] = []
    seen: set[str] = set()
    for path in sorted(Path(data_dir).glob("*.json")):
        with open(path, encoding="utf-8") as f:
            bank = json.load(f)
        year = int(bank["year"])
        if year in banks:
            problems.append(f"year {year} appears in more than one file")
        banks[year] = bank
        for week in bank["weeks"]:
            for q in week["questions"]:
                if q["id"] in seen:
                    problems.append(f"duplicate id {q['id']}")
                seen.add(q["id"])
                missing = [a for a in q["correct_answer"] if a not in q["options"]]
                if missing:
                    problems.append(f"{q['id']}: answer {missing} not in options")
                for img in q.get("images", []):
                    if not (APP_DIR / img).exists():
                        problems.append(f"{q['id']}: image {img} not found")
    if not banks:
        problems.append(f"no question files found in {data_dir}")
    if problems:
        raise ValueError("Question bank is invalid: " + "; ".join(problems))
    return banks


BANKS = load_banks()
YEARS = sorted(BANKS, reverse=True)              # newest first
WEEKS: dict[int, dict[int, dict]] = {y: {w["week"]: w for w in BANKS[y]["weeks"]} for y in YEARS}
YEAR_TOTAL = {y: sum(len(w["questions"]) for w in BANKS[y]["weeks"]) for y in YEARS}
ALL_QUESTIONS: list[dict] = [q for y in sorted(BANKS) for w in BANKS[y]["weeks"] for q in w["questions"]]


def wkey(year: int, week: int) -> str:
    return f"{year}-{week}"


def stable_seed(*args: object) -> int:
    s = ":".join(str(a) for a in args)
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


# --------------------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------------------
def init_state() -> None:
    ss = st.session_state
    ss.setdefault("responses", {PRACTICE: {}, EXAM: {}})  # mode -> qid -> [letters]
    ss.setdefault("graded", {})        # qid -> {"correct": bool, "mode": str}
    ss.setdefault("checked", set())    # qids checked in practice mode
    ss.setdefault("exam", {})          # "year-week" -> {"started_at", "deadline", "submitted", ...}
    ss.setdefault("history", [])       # completed attempts, for the trend chart
    ss.setdefault("practice_logged", set())  # "year-week" keys already logged to history
    ss.setdefault("nonce", {})         # "year-week" -> int, bumped on reset so widgets start fresh
    ss.setdefault("flash", {})         # qid -> one-off message
    ss.setdefault("shuffle_questions", True)  # default ON as requested
    ss.setdefault("shuffle_options", True)    # default ON as requested
    ss.setdefault("shuffle_seed", {})         # "year-week" -> int seed
    # Final Boss 💀 state
    ss.setdefault("boss_style", PRACTICE)
    ss.setdefault("boss_idx", 0)
    ss.setdefault("boss_seed", random.randint(1, 1_000_000))
    ss.setdefault("boss_nonce", 0)
    ss.setdefault("boss_responses", {PRACTICE: {}, EXAM: {}})
    ss.setdefault("boss_graded", {})
    ss.setdefault("boss_checked", set())
    ss.setdefault("boss_flash", {})
    ss.setdefault("boss_exam", {"started_at": None, "deadline": None, "submitted": False, "timed_out": False})


def ensure_shuffle_seed(year: int, week: int) -> int:
    k = wkey(year, week)
    if k not in st.session_state.shuffle_seed:
        st.session_state.shuffle_seed[k] = random.randint(1, 1_000_000)
    return st.session_state.shuffle_seed[k]


def reshuffle_week(year: int, week: int) -> None:
    k = wkey(year, week)
    st.session_state.shuffle_seed[k] = random.randint(1, 1_000_000)
    st.session_state.nonce[k] = st.session_state.nonce.get(k, 0) + 1


def get_week_questions(year: int, week: int) -> list[dict]:
    qs = WEEKS[year][week]["questions"]
    if not st.session_state.get("shuffle_questions", True):
        return list(qs)
    seed = ensure_shuffle_seed(year, week)
    rng = random.Random(seed)
    shuffled = list(qs)
    rng.shuffle(shuffled)
    return shuffled


def get_option_mapping(q: dict, is_boss: bool = False) -> tuple[dict[str, str], dict[str, str]]:
    """Returns (new_to_orig, orig_to_new) letter mappings."""
    orig_keys = list(q["options"].keys())
    if not st.session_state.get("shuffle_options", True):
        identity = {k: k for k in orig_keys}
        return identity, identity
    seed = st.session_state.boss_seed if is_boss else ensure_shuffle_seed(q["year"], q["week"])
    q_seed = stable_seed(seed, q["id"], "options")
    rng = random.Random(q_seed)
    shuffled_orig_keys = list(orig_keys)
    rng.shuffle(shuffled_orig_keys)
    new_to_orig = {orig_keys[i]: shuffled_orig_keys[i] for i in range(len(orig_keys))}
    orig_to_new = {shuffled_orig_keys[i]: orig_keys[i] for i in range(len(orig_keys))}
    return new_to_orig, orig_to_new


def get_display_question(q: dict, is_boss: bool = False) -> dict:
    new_to_orig, orig_to_new = get_option_mapping(q, is_boss=is_boss)
    orig_keys = list(q["options"].keys())
    disp_options = {new_k: q["options"][new_to_orig[new_k]] for new_k in orig_keys}
    disp_correct = sorted([orig_to_new[k] for k in q["correct_answer"]])
    disp_q = dict(q)
    disp_q["options"] = disp_options
    disp_q["correct_answer"] = disp_correct
    disp_q["_new_to_orig"] = new_to_orig
    disp_q["_orig_to_new"] = orig_to_new
    return disp_q


def exam_state(year: int, week: int) -> dict:
    return st.session_state.exam.setdefault(
        wkey(year, week), {"started_at": None, "deadline": None, "submitted": False, "timed_out": False}
    )


def widget_key(mode: str, q: dict, letter: str | None = None, is_boss: bool = False) -> str:
    if is_boss:
        n = st.session_state.boss_nonce
        shuf_opt = 1 if st.session_state.get("shuffle_options", True) else 0
        seed = st.session_state.boss_seed
        base = f"boss:{mode}:{n}:{shuf_opt}:{seed}:{q['id']}"
    else:
        k = wkey(q["year"], q["week"])
        n = st.session_state.nonce.get(k, 0)
        shuf_opt = 1 if st.session_state.get("shuffle_options", True) else 0
        seed = st.session_state.shuffle_seed.get(k, 0)
        base = f"{mode}:{n}:{shuf_opt}:{seed}:{q['id']}"
    return f"{base}:{letter}" if letter else base


def response(mode: str, q: dict, is_boss: bool = False) -> list[str]:
    d = st.session_state.boss_responses[mode] if is_boss else st.session_state.responses[mode]
    return d.get(q["id"], [])


def is_correct(resp: list[str], q: dict) -> bool:
    return sorted(resp) == sorted(q["correct_answer"])


def week_stats(year: int, week: int) -> dict:
    qs = WEEKS[year][week]["questions"]
    graded = st.session_state.graded
    done = [q for q in qs if q["id"] in graded]
    correct = sum(graded[q["id"]]["correct"] for q in done)
    return {
        "total": len(qs),
        "answered": len(done),
        "correct": correct,
        "incorrect": len(done) - correct,
        "score": (100 * correct / len(done)) if done else None,
    }


def year_answered(year: int) -> tuple[int, int]:
    """(answered, correct) across all weeks of one year."""
    graded = st.session_state.graded
    ids = [q["id"] for w in BANKS[year]["weeks"] for q in w["questions"] if q["id"] in graded]
    return len(ids), sum(graded[i]["correct"] for i in ids)


def week_status_icon(year: int, week: int) -> str:
    s = week_stats(year, week)
    if s["answered"] == 0:
        return "⚪"
    return "✅" if s["answered"] == s["total"] else "🟡"


# --------------------------------------------------------------------------------------
# Callbacks (run before the next script rerun)
# --------------------------------------------------------------------------------------
def save_single(mode: str, q: dict, disp_q: dict, is_boss: bool = False) -> None:
    val = st.session_state.get(widget_key(mode, q, is_boss=is_boss))
    target = st.session_state.boss_responses[mode] if is_boss else st.session_state.responses[mode]
    if val:
        orig_val = disp_q["_new_to_orig"].get(val, val)
        target[q["id"]] = [orig_val]
    else:
        target[q["id"]] = []


def save_multi(mode: str, q: dict, disp_q: dict, is_boss: bool = False) -> None:
    chosen = []
    for disp_L in disp_q["options"]:
        orig_L = disp_q["_new_to_orig"][disp_L]
        if st.session_state.get(widget_key(mode, q, orig_L, is_boss=is_boss)):
            chosen.append(orig_L)
    target = st.session_state.boss_responses[mode] if is_boss else st.session_state.responses[mode]
    target[q["id"]] = chosen


def check_practice(q: dict) -> None:
    resp = response(PRACTICE, q)
    if not resp:
        st.session_state.flash[q["id"]] = "Choose an answer before checking."
        return
    st.session_state.checked.add(q["id"])
    st.session_state.graded[q["id"]] = {"correct": is_correct(resp, q), "mode": PRACTICE}

    year, week = q["year"], q["week"]
    qs = WEEKS[year][week]["questions"]
    if wkey(year, week) not in st.session_state.practice_logged and all(
        x["id"] in st.session_state.checked for x in qs
    ):
        correct = sum(is_correct(response(PRACTICE, x), x) for x in qs)
        log_attempt(year, week, "Practice", correct, len(qs), None)
        st.session_state.practice_logged.add(wkey(year, week))


def start_exam(year: int, week: int, timed: bool) -> None:
    s = exam_state(year, week)
    n = len(WEEKS[year][week]["questions"])
    s["started_at"] = time.time()
    s["deadline"] = s["started_at"] + n * SECONDS_PER_QUESTION if timed else None
    s["submitted"] = False
    s["timed_out"] = False


def submit_exam(year: int, week: int, timed_out: bool = False) -> None:
    s = exam_state(year, week)
    if s["submitted"]:
        return
    qs = WEEKS[year][week]["questions"]
    correct = 0
    for q in qs:
        ok = is_correct(response(EXAM, q), q)
        correct += ok
        st.session_state.graded[q["id"]] = {"correct": ok, "mode": EXAM}
    s["submitted"] = True
    s["timed_out"] = timed_out
    s["submitted_at"] = time.time()
    log_attempt(year, week, "Exam", correct, len(qs), s["submitted_at"] - s["started_at"])


def log_attempt(year: int, week: int, mode: str, correct: int, total: int,
                seconds: float | None) -> None:
    st.session_state.history.append({
        "year": year,
        "week": week,
        "mode": mode,
        "correct": correct,
        "total": total,
        "score": round(100 * correct / total, 1),
        "seconds": round(seconds) if seconds is not None else None,
        "finished": datetime.now().strftime("%H:%M:%S"),
    })


def reset_week(year: int, week: int) -> None:
    ss = st.session_state
    k = wkey(year, week)
    for q in WEEKS[year][week]["questions"]:
        for mode in (PRACTICE, EXAM):
            ss.responses[mode].pop(q["id"], None)
        ss.graded.pop(q["id"], None)
        ss.checked.discard(q["id"])
        ss.flash.pop(q["id"], None)
    ss.exam.pop(k, None)
    ss.practice_logged.discard(k)
    ss.nonce[k] = ss.nonce.get(k, 0) + 1   # brand-new widget keys = blank inputs
    ss.shuffle_seed[k] = random.randint(1, 1_000_000)


def reset_year(year: int) -> None:
    """Clear every week of one year; the other year's progress is untouched."""
    for week in WEEKS[year]:
        reset_week(year, week)
    st.session_state.history = [h for h in st.session_state.history if h["year"] != year]


# --------------------------------------------------------------------------------------
# UI building blocks
# --------------------------------------------------------------------------------------
def fmt_letters(letters: list[str]) -> str:
    return ", ".join(letters) if letters else "—"


def render_inputs(mode: str, q: dict, disp_q: dict, disabled: bool, is_boss: bool = False) -> None:
    saved = response(mode, q, is_boss=is_boss)
    orig_to_new = disp_q["_orig_to_new"]
    disp_saved = [orig_to_new[k] for k in saved if k in orig_to_new]
    if disp_q["type"] == "single":
        letters = list(disp_q["options"])
        st.radio(
            "Your answer",
            options=letters,
            index=letters.index(disp_saved[0]) if disp_saved else None,
            format_func=lambda L: f"**{L}.** {disp_q['options'][L]}",
            key=widget_key(mode, q, is_boss=is_boss),
            on_change=save_single,
            args=(mode, q, disp_q, is_boss),
            disabled=disabled,
            label_visibility="collapsed",
        )
    else:
        for disp_L, text in disp_q["options"].items():
            orig_L = disp_q["_new_to_orig"][disp_L]
            st.checkbox(
                f"**{disp_L}.** {text}",
                value=orig_L in saved,
                key=widget_key(mode, q, orig_L, is_boss=is_boss),
                on_change=save_multi,
                args=(mode, q, disp_q, is_boss),
                disabled=disabled,
            )


def render_feedback(q: dict, resp: list[str]) -> None:
    correct = fmt_letters(q["correct_answer"])
    if not resp:
        st.markdown(f'<div class="fb fb-skip">⚪ Not answered. Correct answer: <b>{correct}</b></div>',
                    unsafe_allow_html=True)
    elif is_correct(resp, q):
        st.markdown(f'<div class="fb fb-correct">✅ Correct! Answer: <b>{correct}</b></div>',
                    unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div class="fb fb-wrong">❌ Not quite. You chose <b>{fmt_letters(resp)}</b>; '
            f'correct answer: <b>{correct}</b></div>',
            unsafe_allow_html=True,
        )


def render_explanation(q: dict, expanded: bool) -> None:
    with st.expander("Explanation", expanded=expanded):
        for L in q["correct_answer"]:
            st.markdown(f"**{L}.** {q['options'][L]}")
        st.markdown(q["explanation"] or "_The source solution gives the answer without a written explanation._")


def question_header(q: dict, i: int, n: int) -> None:
    tag = '<span class="tag">Select all that apply</span>' if q["type"] == "multiple" else ""
    st.markdown(f"**Question {i} of {n}** {tag}", unsafe_allow_html=True)
    images = q.get("images", [])
    if images:
        cols = st.columns(len(images))
        for col, img in zip(cols, images):
            col.image(str(APP_DIR / img), width="content")
    st.markdown(q["question"])


def week_metrics(year: int, week: int) -> None:
    s = week_stats(year, week)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Questions", s["total"])
    c2.metric("Answered", f"{s['answered']}/{s['total']}")
    c3.metric("Correct", s["correct"])
    c4.metric("Score", f"{s['score']:.0f}%" if s["score"] is not None else "—")


# --------------------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------------------
def render_shuffle_controls(year: int, week: int) -> None:
    ensure_shuffle_seed(year, week)
    is_exam_running = (
        exam_state(year, week)["started_at"] is not None
        and not exam_state(year, week)["submitted"]
    )
    with st.container(border=True):
        c1, c2, c3 = st.columns([1.5, 1.5, 1.0])
        with c1:
            st.toggle(
                "🔀 Shuffle questions",
                key="shuffle_questions",
                help="Randomizes the question order for this week.",
            )
        with c2:
            st.toggle(
                "🔀 Shuffle options",
                key="shuffle_options",
                help="Randomizes the choice order (A, B, C, D) inside each question.",
            )
        with c3:
            if st.button("🎲 Reshuffle", key=f"reshuffle_{year}_{week}",
                         help="Generate a new random shuffle for this week", width="stretch",
                         disabled=is_exam_running):
                reshuffle_week(year, week)
                st.rerun()


# --------------------------------------------------------------------------------------
# Practice mode
# --------------------------------------------------------------------------------------
def practice_view(year: int, week: int) -> None:
    qs = get_week_questions(year, week)
    week_metrics(year, week)
    st.write("")
    for i, q in enumerate(qs, 1):
        disp_q = get_display_question(q)
        checked = q["id"] in st.session_state.checked
        with st.container(border=True):
            question_header(disp_q, i, len(qs))
            render_inputs(PRACTICE, q, disp_q, disabled=checked)
            if checked:
                saved = response(PRACTICE, q)
                disp_saved = [disp_q["_orig_to_new"][k] for k in saved if k in disp_q["_orig_to_new"]]
                render_feedback(disp_q, disp_saved)
                render_explanation(disp_q, expanded=True)
            else:
                st.button("Check answer", key=f"check:{widget_key(PRACTICE, q)}",
                          on_click=check_practice, args=(q,))
                msg = st.session_state.flash.pop(q["id"], None)
                if msg:
                    st.warning(msg)

    if all(q["id"] in st.session_state.checked for q in qs):
        s = week_stats(year, week)
        st.success(f"Week {week} ({year}) complete: {s['correct']}/{s['total']} correct. "
                   "Use **Retry this week** in the sidebar to try again.")


# --------------------------------------------------------------------------------------
# Exam mode
# --------------------------------------------------------------------------------------
@st.fragment(run_every=1)
def countdown(year: int, week: int) -> None:
    s = exam_state(year, week)
    if s["submitted"] or s["deadline"] is None:
        return
    remaining = s["deadline"] - time.time()
    if remaining <= 0:
        submit_exam(year, week, timed_out=True)
        st.rerun()  # full-app rerun to show the results
    total = s["deadline"] - s["started_at"]
    mins, secs = divmod(int(remaining), 60)
    st.progress(max(0.0, remaining / total), text=f"⏱️ Time left: {mins:02d}:{secs:02d}")


def exam_view(year: int, week: int, timed: bool) -> None:
    qs = get_week_questions(year, week)
    s = exam_state(year, week)

    # 1) Not started
    if s["started_at"] is None:
        with st.container(border=True):
            st.markdown(f"### Exam: Week {week} ({year})")
            limit = f"{len(qs) * SECONDS_PER_QUESTION // 60} minutes" if timed else "no time limit"
            st.markdown(
                f"{len(qs)} questions, {limit}. Answers are hidden until you submit; "
                "unanswered questions count as incorrect."
                + (" The exam submits itself when time runs out." if timed else "")
            )
            st.button("Start exam", type="primary", on_click=start_exam, args=(year, week, timed))
        return

    # 2) In progress
    if not s["submitted"]:
        countdown(year, week)
        answered = sum(bool(response(EXAM, q)) for q in qs)
        st.caption(f"{answered} of {len(qs)} answered")
        for i, q in enumerate(qs, 1):
            disp_q = get_display_question(q)
            with st.container(border=True):
                question_header(disp_q, i, len(qs))
                render_inputs(EXAM, q, disp_q, disabled=False)
        st.button("Submit exam", type="primary", on_click=submit_exam, args=(year, week),
                  width="stretch")
        return

    # 3) Submitted: summary + review
    correct = sum(st.session_state.graded.get(q["id"], {}).get("correct", False) for q in qs)
    unanswered = sum(not response(EXAM, q) for q in qs)
    secs = int(s["submitted_at"] - s["started_at"])
    if s["timed_out"]:
        st.warning("Time ran out, so your exam was submitted automatically.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score", f"{100 * correct / len(qs):.0f}%")
    c2.metric("Correct", f"{correct}/{len(qs)}")
    c3.metric("Incorrect", len(qs) - correct - unanswered)
    c4.metric("Time taken", f"{secs // 60}m {secs % 60:02d}s")

    st.subheader("Review")
    only_wrong = st.toggle("Show only questions I missed")
    for i, q in enumerate(qs, 1):
        disp_q = get_display_question(q)
        resp = response(EXAM, q)
        if only_wrong and is_correct(resp, q):
            continue
        with st.container(border=True):
            question_header(disp_q, i, len(qs))
            for disp_L, text in disp_q["options"].items():
                orig_L = disp_q["_new_to_orig"][disp_L]
                mark = "✅" if orig_L in q["correct_answer"] else ("❌" if orig_L in resp else "▫️")
                mine = " _(your answer)_" if orig_L in resp else ""
                st.markdown(f"{mark} **{disp_L}.** {text}{mine}")
            disp_resp = [disp_q["_orig_to_new"][k] for k in resp if k in disp_q["_orig_to_new"]]
            render_feedback(disp_q, disp_resp)
            render_explanation(disp_q, expanded=False)
    st.button("Retry this week", on_click=reset_week, args=(year, week), key="retry_bottom")


# --------------------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------------------
def score_color(v: float | None) -> str:
    v = v or 0
    return "#22a35a" if v >= 70 else "#e0a526" if v >= 40 else "#d63939"


def dashboard_view(year: int) -> None:
    n_answered, n_correct = year_answered(year)

    st.markdown(f"#### {year} question set")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total questions", YEAR_TOTAL[year])
    c2.metric("Answered", n_answered)
    c3.metric("Correct", n_correct)
    c4.metric("Incorrect", n_answered - n_correct)
    c5.metric("Score", f"{100 * n_correct / n_answered:.0f}%" if n_answered else "—")

    if not n_answered:
        st.info(f"No {year} answers yet. Check an answer in Practice mode or submit an exam "
                "to see results here.")
    else:
        rows = []
        for w in WEEKS[year]:
            s = week_stats(year, w)
            rows.append({
                "Week": f"W{w}",
                "Topic": WEEKS[year][w]["title"],
                "Answered": s["answered"],
                "Correct": s["correct"],
                "Incorrect": s["incorrect"],
                "Not attempted": s["total"] - s["answered"],
                "Score %": s["score"],
                "Completion %": 100 * s["answered"] / s["total"],
            })
        df = pd.DataFrame(rows)

        fig = go.Figure()
        fig.add_bar(x=df["Week"], y=df["Score %"], name="Score %",
                    marker_color=[score_color(v) for v in df["Score %"]],
                    hovertemplate="%{x}: %{y:.0f}%<extra>Score</extra>")
        fig.add_scatter(x=df["Week"], y=df["Completion %"], name="Completion %",
                        mode="lines+markers", line=dict(color="#4c78a8", width=2),
                        hovertemplate="%{x}: %{y:.0f}% answered<extra></extra>")
        fig.update_layout(title=f"Score and completion by week ({year})",
                          yaxis=dict(range=[0, 105], title="%"),
                          height=380, margin=dict(t=50, b=10, l=10, r=10),
                          legend=dict(orientation="h", y=1.12, x=1, xanchor="right"))
        st.plotly_chart(fig, width="stretch")

        fig2 = go.Figure()
        for col, color in (("Correct", "#22a35a"), ("Incorrect", "#d63939"),
                           ("Not attempted", "#b9b9b9")):
            fig2.add_bar(x=df["Week"], y=df[col], name=col, marker_color=color)
        fig2.update_layout(barmode="stack", title=f"Correct vs. incorrect answers ({year})",
                           yaxis_title="Questions", height=340,
                           margin=dict(t=50, b=10, l=10, r=10),
                           legend=dict(orientation="h", y=1.14, x=1, xanchor="right"))
        st.plotly_chart(fig2, width="stretch")

        st.dataframe(
            df[["Week", "Topic", "Answered", "Correct", "Score %"]],
            hide_index=True, width="stretch",
            column_config={"Score %": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f%%")},
        )

        history = [h for h in st.session_state.history if h["year"] == year]
        if history:
            st.subheader("Attempt history")
            hist = pd.DataFrame(history)
            hist.index = range(1, len(hist) + 1)
            hist["Week"] = "W" + hist["week"].astype(str)
            fig3 = go.Figure()
            for wk, grp in hist.groupby("Week", sort=False):
                fig3.add_scatter(x=grp.index, y=grp["score"], mode="lines+markers", name=wk,
                                 hovertemplate=f"{wk} attempt #%{{x}}: %{{y}}%<extra></extra>")
            fig3.update_layout(xaxis_title="Attempt #", yaxis=dict(range=[0, 105], title="Score %"),
                               height=320, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig3, width="stretch")
            st.dataframe(
                hist[["Week", "mode", "correct", "total", "score", "seconds", "finished"]].rename(
                    columns={"mode": "Mode", "correct": "Correct", "total": "Total",
                             "score": "Score %", "seconds": "Time (s)",
                             "finished": "Finished at"}),
                width="stretch",
            )
        st.caption("Each question counts its most recent graded attempt, from either mode.")

    # Side-by-side view of the years. Scores stay separate; this only puts them next to each other.
    others = [y for y in YEARS if y != year and year_answered(y)[0]]
    if others and n_answered:
        st.divider()
        st.subheader("Compare years")
        fig4 = go.Figure()
        for y in sorted([year] + others):
            weeks = list(WEEKS[y])
            fig4.add_bar(x=[f"W{w}" for w in weeks],
                         y=[week_stats(y, w)["score"] for w in weeks], name=str(y),
                         hovertemplate=f"{y} %{{x}}: %{{y:.0f}}%<extra></extra>")
        fig4.update_layout(barmode="group", yaxis=dict(range=[0, 105], title="Score %"),
                           height=340, margin=dict(t=20, b=10, l=10, r=10),
                           legend=dict(orientation="h", y=1.1, x=1, xanchor="right"))
        st.plotly_chart(fig4, width="stretch")
        st.caption("Weeks with no answers in a year show no bar for that year.")


# --------------------------------------------------------------------------------------
# Final Boss 💀 Mode
# --------------------------------------------------------------------------------------
def get_boss_questions() -> list[dict]:
    if not st.session_state.get("shuffle_questions", True):
        return list(ALL_QUESTIONS)
    rng = random.Random(st.session_state.boss_seed)
    shuffled = list(ALL_QUESTIONS)
    rng.shuffle(shuffled)
    return shuffled


def reshuffle_boss() -> None:
    st.session_state.boss_seed = random.randint(1, 1_000_000)
    st.session_state.boss_nonce += 1
    st.session_state.boss_idx = 0


def reset_boss() -> None:
    ss = st.session_state
    ss.boss_responses = {PRACTICE: {}, EXAM: {}}
    ss.boss_graded = {}
    ss.boss_checked = set()
    ss.boss_flash = {}
    ss.boss_exam = {"started_at": None, "deadline": None, "submitted": False, "timed_out": False}
    ss.boss_nonce += 1
    ss.boss_seed = random.randint(1, 1_000_000)
    ss.boss_idx = 0


def check_boss_practice(q: dict) -> None:
    resp = response(PRACTICE, q, is_boss=True)
    if not resp:
        st.session_state.boss_flash[q["id"]] = "Choose an answer before checking."
        return
    st.session_state.boss_checked.add(q["id"])
    st.session_state.boss_graded[q["id"]] = {"correct": is_correct(resp, q), "mode": PRACTICE}


def start_boss_exam(timed: bool) -> None:
    s = st.session_state.boss_exam
    n = len(ALL_QUESTIONS)
    s["started_at"] = time.time()
    s["deadline"] = s["started_at"] + n * SECONDS_PER_QUESTION if timed else None
    s["submitted"] = False
    s["timed_out"] = False


def submit_boss_exam(timed_out: bool = False) -> None:
    s = st.session_state.boss_exam
    if s["submitted"]:
        return
    for q in ALL_QUESTIONS:
        ok = is_correct(response(EXAM, q, is_boss=True), q)
        st.session_state.boss_graded[q["id"]] = {"correct": ok, "mode": EXAM}
    s["submitted"] = True
    s["timed_out"] = timed_out
    s["submitted_at"] = time.time()


@st.fragment(run_every=1)
def boss_countdown() -> None:
    s = st.session_state.boss_exam
    if s["submitted"] or s["deadline"] is None:
        return
    remaining = s["deadline"] - time.time()
    if remaining <= 0:
        submit_boss_exam(timed_out=True)
        st.rerun()
    total = s["deadline"] - s["started_at"]
    hours, rem = divmod(int(remaining), 3600)
    mins, secs = divmod(rem, 60)
    st.progress(max(0.0, remaining / total), text=f"⏱️ Time left: {hours:02d}h {mins:02d}m {secs:02d}s")


def render_boss_shuffle_controls() -> None:
    is_exam_running = (
        st.session_state.boss_exam["started_at"] is not None
        and not st.session_state.boss_exam["submitted"]
    )
    with st.container(border=True):
        c1, c2, c3 = st.columns([1.5, 1.5, 1.0])
        with c1:
            st.toggle(
                "🔀 Shuffle questions",
                key="shuffle_questions",
                help="Randomizes all 219 questions into a mixed gauntlet.",
            )
        with c2:
            st.toggle(
                "🔀 Shuffle options",
                key="shuffle_options",
                help="Randomizes choice order (A, B, C, D) inside each question.",
            )
        with c3:
            if st.button("🎲 Reshuffle", key="reshuffle_boss",
                         help="Generate a new random shuffle for the Boss fight", width="stretch",
                         disabled=is_exam_running):
                reshuffle_boss()
                st.rerun()


def render_boss_navigator(qs: list[dict], mode: str) -> None:
    curr_idx = min(st.session_state.boss_idx, len(qs) - 1)
    total = len(qs)
    with st.expander(f"🗺️ Question Navigator Grid (Question {curr_idx + 1} of {total})", expanded=False):
        ranges = [
            ("1–50", 0, 50),
            ("51–100", 50, 100),
            ("101–150", 100, 150),
            ("151–200", 150, 200),
            ("201–219", 200, total),
        ]
        nav_tabs = st.tabs([r[0] for r in ranges])
        for tab, (_, start, end) in zip(nav_tabs, ranges):
            with tab:
                cols = st.columns(10)
                for i in range(start, min(end, total)):
                    q = qs[i]
                    col = cols[(i - start) % 10]
                    is_curr = (i == curr_idx)
                    if mode == PRACTICE:
                        checked = q["id"] in st.session_state.boss_checked
                        if checked:
                            corr = st.session_state.boss_graded.get(q["id"], {}).get("correct", False)
                            badge = "✅" if corr else "❌"
                        else:
                            badge = "👉" if is_curr else ""
                    else:
                        if st.session_state.boss_exam["submitted"]:
                            corr = st.session_state.boss_graded.get(q["id"], {}).get("correct", False)
                            badge = "✅" if corr else ("⚪" if not response(EXAM, q, is_boss=True) else "❌")
                        else:
                            has_ans = bool(response(EXAM, q, is_boss=True))
                            badge = "👉" if is_curr else ("●" if has_ans else "")
                    lbl = f"{badge} {i + 1}" if badge else f"{i + 1}"
                    if col.button(lbl, key=f"bnav_{i}_{q['id']}", width="stretch",
                                  type="primary" if is_curr else "secondary"):
                        st.session_state.boss_idx = i
                        st.rerun()


def render_boss_stepper(qs: list[dict]) -> None:
    curr_idx = min(st.session_state.boss_idx, len(qs) - 1)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("⬅️ Previous", key=f"boss_prev_top_{curr_idx}", disabled=curr_idx <= 0, width="stretch"):
            st.session_state.boss_idx -= 1
            st.rerun()
    with c2:
        st.markdown(
            f"<div style='text-align: center; padding-top: 0.4rem; font-weight: 600; font-size: 1.05rem;'>"
            f"Question {curr_idx + 1} of {len(qs)}</div>",
            unsafe_allow_html=True,
        )
    with c3:
        if st.button("Next ➡️", key=f"boss_next_top_{curr_idx}", disabled=curr_idx >= len(qs) - 1, width="stretch"):
            st.session_state.boss_idx += 1
            st.rerun()


def boss_practice_view(qs: list[dict]) -> None:
    curr_idx = min(st.session_state.boss_idx, len(qs) - 1)
    q = qs[curr_idx]
    disp_q = get_display_question(q, is_boss=True)

    n_checked = len(st.session_state.boss_checked)
    n_correct = sum(st.session_state.boss_graded.get(k, {}).get("correct", False) for k in st.session_state.boss_checked)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total questions", len(qs))
    c2.metric("Checked", f"{n_checked}/{len(qs)}")
    c3.metric("Correct", n_correct)
    c4.metric("Accuracy", f"{100 * n_correct / n_checked:.0f}%" if n_checked else "—")

    render_boss_navigator(qs, PRACTICE)
    render_boss_stepper(qs)

    checked = q["id"] in st.session_state.boss_checked
    with st.container(border=True):
        st.caption(f"**From {q['year']} Week {q['week']}**")
        question_header(disp_q, curr_idx + 1, len(qs))
        render_inputs(PRACTICE, q, disp_q, disabled=checked, is_boss=True)
        if checked:
            saved = response(PRACTICE, q, is_boss=True)
            disp_saved = [disp_q["_orig_to_new"][k] for k in saved if k in disp_q["_orig_to_new"]]
            render_feedback(disp_q, disp_saved)
            render_explanation(disp_q, expanded=True)
        else:
            st.button("Check answer", key=f"boss_check:{widget_key(PRACTICE, q, is_boss=True)}",
                      on_click=check_boss_practice, args=(q,))
            msg = st.session_state.boss_flash.pop(q["id"], None)
            if msg:
                st.warning(msg)

    c_prev, _, c_next = st.columns([1, 2, 1])
    with c_prev:
        if st.button("⬅️ Previous", key="boss_prev_bot", disabled=curr_idx <= 0, width="stretch"):
            st.session_state.boss_idx -= 1
            st.rerun()
    with c_next:
        if curr_idx < len(qs) - 1:
            if st.button("Next Question ➡️", key="boss_next_bot", type="primary", width="stretch"):
                st.session_state.boss_idx += 1
                st.rerun()
        else:
            st.success("🎉 You've reached the final question of the gauntlet!")


def boss_exam_view(qs: list[dict], timed: bool) -> None:
    s = st.session_state.boss_exam

    # 1) Not started
    if s["started_at"] is None:
        with st.container(border=True):
            st.markdown("### 💀 Final Boss: The 219-Question Exam")
            limit = f"{len(qs) * SECONDS_PER_QUESTION // 60} minutes (~5.5 hours)" if timed else "no time limit"
            st.markdown(
                f"Face **all {len(qs)} questions** from both 2025 and 2026. Time budget: {limit}. "
                "Answers remain hidden until you submit at the end. Unanswered questions count as incorrect."
            )
            st.button("🔥 Start Final Boss Exam", type="primary", on_click=start_boss_exam, args=(timed,))
        return

    # 2) In progress
    if not s["submitted"]:
        if timed:
            boss_countdown()
        answered = sum(bool(response(EXAM, q, is_boss=True)) for q in qs)
        st.caption(f"📝 {answered} of {len(qs)} questions answered")

        render_boss_navigator(qs, EXAM)
        render_boss_stepper(qs)

        curr_idx = min(st.session_state.boss_idx, len(qs) - 1)
        q = qs[curr_idx]
        disp_q = get_display_question(q, is_boss=True)

        with st.container(border=True):
            st.caption(f"**From {q['year']} Week {q['week']}**")
            question_header(disp_q, curr_idx + 1, len(qs))
            render_inputs(EXAM, q, disp_q, disabled=False, is_boss=True)

        c_prev, c_sub, c_next = st.columns([1, 1.5, 1])
        with c_prev:
            if st.button("⬅️ Previous", key="boss_ex_prev", disabled=curr_idx <= 0, width="stretch"):
                st.session_state.boss_idx -= 1
                st.rerun()
        with c_sub:
            with st.popover("🏁 Submit Exam", width="stretch"):
                st.write(f"You have answered **{answered} of {len(qs)}** questions.")
                if answered < len(qs):
                    st.warning(f"⚠️ {len(qs) - answered} questions are unanswered!")
                st.button("Yes, Submit Exam", type="primary", on_click=submit_boss_exam, width="stretch")
        with c_next:
            if st.button("Next ➡️", key="boss_ex_next", disabled=curr_idx >= len(qs) - 1, width="stretch"):
                st.session_state.boss_idx += 1
                st.rerun()
        return

    # 3) Submitted
    correct = sum(st.session_state.boss_graded.get(q["id"], {}).get("correct", False) for q in qs)
    unanswered = sum(not response(EXAM, q, is_boss=True) for q in qs)
    secs = int(s["submitted_at"] - s["started_at"])
    if s["timed_out"]:
        st.warning("⏱️ Time ran out, so your exam was submitted automatically.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Final Score", f"{100 * correct / len(qs):.1f}%")
    c2.metric("Correct", f"{correct}/{len(qs)}")
    c3.metric("Incorrect", len(qs) - correct - unanswered)
    c4.metric("Time taken", f"{secs // 3600}h {(secs % 3600) // 60}m {secs % 60:02d}s")

    st.subheader("Exam Review")
    render_boss_navigator(qs, EXAM)
    render_boss_stepper(qs)

    curr_idx = min(st.session_state.boss_idx, len(qs) - 1)
    q = qs[curr_idx]
    disp_q = get_display_question(q, is_boss=True)
    resp = response(EXAM, q, is_boss=True)

    with st.container(border=True):
        st.caption(f"**From {q['year']} Week {q['week']}**")
        question_header(disp_q, curr_idx + 1, len(qs))
        for disp_L, text in disp_q["options"].items():
            orig_L = disp_q["_new_to_orig"][disp_L]
            mark = "✅" if orig_L in q["correct_answer"] else ("❌" if orig_L in resp else "▫️")
            mine = " _(your answer)_" if orig_L in resp else ""
            st.markdown(f"{mark} **{disp_L}.** {text}{mine}")
        disp_resp = [disp_q["_orig_to_new"][k] for k in resp if k in disp_q["_orig_to_new"]]
        render_feedback(disp_q, disp_resp)
        render_explanation(disp_q, expanded=True)

    st.divider()
    st.button("Retry Final Boss", on_click=reset_boss, width="stretch", key="retry_boss_btn")


def boss_stats_view(qs: list[dict], mode: str) -> None:
    st.subheader("Performance Breakdown")
    graded = st.session_state.boss_graded
    if not graded:
        st.info("No questions graded yet. Check an answer in Practice or submit an Exam to see analytics.")
        return

    rows = []
    for w in range(1, 13):
        w_qs = [q for q in ALL_QUESTIONS if q["week"] == w]
        done = [q for q in w_qs if q["id"] in graded]
        corr = sum(graded[q["id"]]["correct"] for q in done)
        rows.append({
            "Week": f"W{w}",
            "Questions": len(w_qs),
            "Answered": len(done),
            "Correct": corr,
            "Score %": (100 * corr / len(done)) if done else None,
        })
    df = pd.DataFrame(rows)

    fig = go.Figure()
    fig.add_bar(x=df["Week"], y=df["Score %"], name="Score %",
                marker_color=[score_color(v) for v in df["Score %"]],
                hovertemplate="%{x}: %{y:.0f}%<extra>Score</extra>")
    fig.update_layout(title="Accuracy by Topic (Weeks 1–12)",
                      yaxis=dict(range=[0, 105], title="%"),
                      height=320, margin=dict(t=40, b=10, l=10, r=10))
    st.plotly_chart(fig, width="stretch")

    st.dataframe(
        df[["Week", "Questions", "Answered", "Correct", "Score %"]],
        hide_index=True, width="stretch",
        column_config={"Score %": st.column_config.ProgressColumn(
            "Score", min_value=0, max_value=100, format="%.0f%%")},
    )


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def main() -> None:
    init_state()
    st.markdown(CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.title("🧠 RL Weekly Quiz")
        mode_label = st.radio(
            "Mode",
            ["Practice", "Exam", "Final Boss 💀"],
            horizontal=False,
            key="main_mode",
            help="Practice: instant feedback per question. "
                 "Exam: answers revealed after you submit. "
                 "Final Boss 💀: all 219 questions from 2025 & 2026 combined!",
        )

        if mode_label == "Final Boss 💀":
            boss_style_label = st.radio(
                "Boss Style",
                ["Practice", "Exam"],
                horizontal=True,
                key="boss_style_choice",
                help="Practice: check as you go. Exam: timed test submitted at the end.",
            )
            boss_style = PRACTICE if boss_style_label == "Practice" else EXAM
            timed = False
            if boss_style == EXAM:
                timed = st.toggle(
                    "Time limit",
                    value=False,
                    help=f"{SECONDS_PER_QUESTION} seconds per question (~5.5 hours total).",
                    disabled=st.session_state.boss_exam["started_at"] is not None,
                )

            st.divider()
            st.markdown("**💀 Final Boss Progress**")
            if boss_style == PRACTICE:
                n_done = len(st.session_state.boss_checked)
            else:
                n_done = sum(bool(response(EXAM, q, is_boss=True)) for q in ALL_QUESTIONS)
            st.progress(n_done / len(ALL_QUESTIONS), text=f"{n_done} of {len(ALL_QUESTIONS)} answered")
            st.divider()
            st.button("Reset Final Boss", on_click=reset_boss, width="stretch")
        else:
            year = st.radio("Question set", YEARS, horizontal=True, key="year",
                            help="Each year's questions, scores and history are kept separate.")

            # Labels stay static: changing them would give the widget a new identity and drop the
            # user's selection. Status is shown in the caption below instead. One selector per year.
            labels = {w: f"Week {w}: {WEEKS[year][w]['title']}" for w in WEEKS[year]}
            week = st.selectbox("Week", options=list(WEEKS[year]), format_func=labels.get,
                                key=f"week_{year}")
            s = week_stats(year, week)
            icon = week_status_icon(year, week)
            status = {"⚪": "not started", "🟡": "in progress", "✅": "complete"}[icon]
            st.caption(f"{icon} {status} ({s['answered']}/{s['total']} answered)")

            mode = PRACTICE if mode_label == "Practice" else EXAM
            timed = True
            if mode == EXAM:
                timed = st.toggle("Time limit", value=True,
                                  help=f"{SECONDS_PER_QUESTION} seconds per question.",
                                  disabled=exam_state(year, week)["started_at"] is not None)

            st.divider()
            done, _ = year_answered(year)
            st.markdown(f"**{year} progress**")
            st.progress(done / YEAR_TOTAL[year],
                        text=f"{done} of {YEAR_TOTAL[year]} questions answered")
            complete = sum(week_stats(year, w)["answered"] == week_stats(year, w)["total"]
                           for w in WEEKS[year])
            st.caption(f"{complete} of {len(WEEKS[year])} weeks complete")
            for y in YEARS:
                if y != year:
                    d, _ = year_answered(y)
                    st.caption(f"{y}: {d} of {YEAR_TOTAL[y]} answered")

            st.divider()
            st.button("Retry this week", on_click=reset_week, args=(year, week), width="stretch")
            with st.popover(f"Reset all of {year}", width="stretch"):
                st.write(f"Clear every {year} answer, score and attempt? "
                         "Other years are not affected.")
                st.button(f"Yes, reset {year}", type="primary", on_click=reset_year, args=(year,))

    if mode_label == "Final Boss 💀":
        st.title("💀 Final Boss: 219 Questions (2025 & 2026)", anchor=False)
        st.caption("The complete gauntlet covering all 12 weeks of Reinforcement Learning assignments (Prof. B. Ravindran)")
        tab_boss, tab_stats = st.tabs(["⚔️ Boss Battle", "📊 Boss Stats"])
        with tab_boss:
            render_boss_shuffle_controls()
            qs = get_boss_questions()
            if boss_style == PRACTICE:
                boss_practice_view(qs)
            else:
                boss_exam_view(qs, timed)
        with tab_stats:
            boss_stats_view(get_boss_questions(), boss_style)
    else:
        st.title(f"Week {week}: {WEEKS[year][week]['title']}", anchor=False)
        st.caption(BANKS[year].get("source", ""))
        tab_quiz, tab_dash = st.tabs(["📝 Quiz", "📊 Results dashboard"])
        with tab_quiz:
            render_shuffle_controls(year, week)
            if mode == PRACTICE:
                practice_view(year, week)
            else:
                exam_view(year, week, timed)
        with tab_dash:
            dashboard_view(year)


if __name__ == "__main__":
    main()

"""
Lesson runtime for the Learn tab.

Lessons are markdown files under ``content/lessons/`` with YAML front-matter
that declares the lesson's id, title, duration, and a list of ``actions`` —
buttons the student can press to run a stage, run a Tcl command, ask the RAG
agent a question, or jump to another tab.

Progress is kept in ``st.session_state['lesson_progress']`` — a set of
completed lesson ids. No DB write yet; that arrives with signup in Phase 5.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import os

import streamlit as st
import yaml

from ip_agent.ui.components import callout, lesson_card, step_header


def _find_lessons_dir() -> Path:
    """Lessons live outside the Python package. Try the common locations."""
    env = os.environ.get("LESSONS_DIR")
    if env and Path(env).exists():
        return Path(env)
    # Docker image copies ./content into /app/content
    if Path("/app/content/lessons").exists():
        return Path("/app/content/lessons")
    # Local dev: repo root
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "content" / "lessons"
        if candidate.exists():
            return candidate
    # Last-resort fallback matches the original layout (may not exist).
    return here.parents[3] / "content" / "lessons"


LESSONS_DIR = _find_lessons_dir()
FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

# Action types the renderer knows how to wire up.
_ACTION_TYPES = {"run_stage", "run_tcl", "ask_agent", "open_timing_closure", "open_flow_manager"}


@dataclass
class Action:
    type: str
    label: str
    design: str | None = None
    pdk: str | None = None
    stage: str | None = None
    command: str | None = None
    question: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Action":
        kind = raw.get("type", "")
        if kind not in _ACTION_TYPES:
            raise ValueError(f"Unknown lesson action type: {kind!r}")
        return cls(
            type=kind,
            label=raw.get("label", kind),
            design=raw.get("design"),
            pdk=raw.get("pdk"),
            stage=raw.get("stage"),
            command=raw.get("command"),
            question=raw.get("question"),
        )


@dataclass
class Lesson:
    id: int
    title: str
    summary: str
    duration_min: int
    requires_runner: bool
    body: str
    actions: list[Action] = field(default_factory=list)
    path: Path | None = None


def _parse(path: Path) -> Lesson:
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise ValueError(f"Lesson file missing YAML front-matter: {path}")
    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()
    raw_actions = meta.get("actions") or []
    actions = [Action.from_dict(a) for a in raw_actions]
    return Lesson(
        id=int(meta["id"]),
        title=str(meta["title"]),
        summary=str(meta.get("summary", "")),
        duration_min=int(meta.get("duration_min", 0)),
        requires_runner=bool(meta.get("requires_runner", False)),
        body=body,
        actions=actions,
        path=path,
    )


@lru_cache(maxsize=1)
def load_lessons() -> list[Lesson]:
    """Load all lessons from ``content/lessons/`` sorted by id. Cached for the process."""
    if not LESSONS_DIR.exists():
        return []
    lessons = [_parse(p) for p in sorted(LESSONS_DIR.glob("lesson_*.md"))]
    lessons.sort(key=lambda l: l.id)
    return lessons


# ---------------------------------------------------------------------------
# Progress tracking (session-scoped for now)
# ---------------------------------------------------------------------------


def _progress_set() -> set[int]:
    if "lesson_progress" not in st.session_state:
        st.session_state.lesson_progress = set()
    return st.session_state.lesson_progress


def mark_complete(lesson_id: int) -> None:
    _progress_set().add(lesson_id)


def is_complete(lesson_id: int) -> bool:
    return lesson_id in _progress_set()


def selected_lesson_id() -> int:
    if "selected_lesson" not in st.session_state:
        st.session_state.selected_lesson = 1
    return st.session_state.selected_lesson


def select_lesson(lesson_id: int) -> None:
    st.session_state.selected_lesson = lesson_id


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


def _handle_run_stage(action: Action) -> None:
    from ip_agent.flow_manager import FlowManager  # lazy import

    if not (action.design and action.pdk and action.stage):
        st.error("Lesson action is missing design/pdk/stage.")
        return
    fm = FlowManager(design=action.design, pdk=action.pdk)
    try:
        job_id = fm.submit_stage(action.stage)
    except Exception as exc:
        st.error(f"Could not submit stage: {exc}")
        return
    st.session_state.setdefault("flow_jobs", {})[job_id] = {
        "type": "stage",
        "design": action.design,
        "pdk": action.pdk,
        "stage": action.stage,
        "submitted_from": "lesson",
    }
    st.success(
        f"Submitted **{action.stage}** on **{action.design} / {action.pdk}**. "
        f"Open the Lab tab to watch the log stream. (job: `{job_id[:8]}`)"
    )


def _handle_run_tcl(action: Action) -> None:
    from ip_agent.flow_manager import FlowManager

    if not (action.design and action.pdk and action.command):
        st.error("Lesson action is missing design/pdk/command.")
        return
    fm = FlowManager(design=action.design, pdk=action.pdk)
    try:
        job_id = fm.submit_tcl_command(action.command)
    except Exception as exc:
        st.error(f"Could not submit Tcl command: {exc}")
        return
    st.session_state.setdefault("flow_jobs", {})[job_id] = {
        "type": "tcl",
        "design": action.design,
        "pdk": action.pdk,
        "command": action.command,
        "submitted_from": "lesson",
    }
    st.success(f"Submitted Tcl command. Open the Lab tab for output. (job: `{job_id[:8]}`)")


def _handle_ask_agent(action: Action) -> None:
    if not action.question:
        st.error("Lesson action is missing question text.")
        return
    st.session_state.pending_question = action.question
    st.info("Question queued. Switch to the **💬 Chat** tab — the agent will answer there.")


def _handle_open(action: Action) -> None:
    # There's no programmatic tab switch in Streamlit; leave a clear pointer.
    target = "Timing Closure" if action.type == "open_timing_closure" else "Flow Manager"
    st.info(f"Click the **{target}** tab at the top of the page to continue.")


_HANDLERS = {
    "run_stage": _handle_run_stage,
    "run_tcl": _handle_run_tcl,
    "ask_agent": _handle_ask_agent,
    "open_timing_closure": _handle_open,
    "open_flow_manager": _handle_open,
}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_sidebar_list(lessons: list[Lesson]) -> None:
    st.markdown("### Lessons")
    current = selected_lesson_id()
    for lesson in lessons:
        marker = "✓ " if is_complete(lesson.id) else ("▸ " if lesson.id == current else "　")
        if st.button(
            f"{marker}{lesson.id:02d}. {lesson.title}",
            key=f"lesson_select_{lesson.id}",
            use_container_width=True,
        ):
            select_lesson(lesson.id)
            st.rerun()
    st.divider()
    total = len(lessons)
    done = sum(1 for l in lessons if is_complete(l.id))
    st.caption(f"Progress: **{done} / {total}** complete")


def _render_actions(lesson: Lesson) -> None:
    if not lesson.actions:
        return
    st.markdown("### Try it")
    for idx, action in enumerate(lesson.actions):
        button_key = f"action_{lesson.id}_{idx}"
        col_a, col_b = st.columns([4, 1])
        with col_a:
            if st.button(action.label, key=button_key, type="primary", use_container_width=True):
                handler = _HANDLERS.get(action.type)
                if handler is None:
                    st.error(f"Unhandled action type: {action.type}")
                else:
                    handler(action)
        with col_b:
            st.caption({
                "run_stage": "stage",
                "run_tcl": "tcl",
                "ask_agent": "chat",
                "open_timing_closure": "tab",
                "open_flow_manager": "tab",
            }.get(action.type, action.type))


def _render_lesson_body(lesson: Lesson) -> None:
    step_header(
        lesson.id,
        lesson.title,
        subtitle=f"~{lesson.duration_min} min" if lesson.duration_min else "",
    )
    if lesson.summary:
        callout(lesson.summary, title="In this lesson", tone="blue")
    if lesson.requires_runner:
        callout(
            "This lesson uses the shared OpenROAD runner. If someone else has the slot, "
            "you'll see a queue banner on the Lab tab — wait your turn or keep reading.",
            title="Runner required",
            tone="amber",
        )
    st.markdown(lesson.body)
    _render_actions(lesson)

    st.divider()
    col_mark, col_next = st.columns(2)
    with col_mark:
        already = is_complete(lesson.id)
        label = "✓ Marked complete" if already else "Mark this lesson complete"
        if st.button(label, key=f"mark_done_{lesson.id}", disabled=already, use_container_width=True):
            mark_complete(lesson.id)
            st.rerun()
    with col_next:
        lessons = load_lessons()
        next_ids = [l.id for l in lessons if l.id > lesson.id]
        if next_ids:
            next_id = next_ids[0]
            if st.button("Next lesson →", key=f"next_{lesson.id}", use_container_width=True):
                select_lesson(next_id)
                st.rerun()


def render_lessons_tab() -> None:
    """Entry point called from ``app.py`` inside the Lessons tab."""
    lessons = load_lessons()
    if not lessons:
        st.warning("No lessons found. Check that `content/lessons/*.md` exists.")
        return

    left, right = st.columns([1, 3], gap="large")
    with left:
        _render_sidebar_list(lessons)
    with right:
        current_id = selected_lesson_id()
        lesson = next((l for l in lessons if l.id == current_id), lessons[0])
        _render_lesson_body(lesson)


def render_lessons_overview() -> None:
    """Card grid of all lessons — used on the Landing tab in Phase 5."""
    lessons = load_lessons()
    for lesson in lessons:
        lesson_card(
            number=lesson.id,
            title=lesson.title,
            description=lesson.summary,
            duration_min=lesson.duration_min,
            requires_runner=lesson.requires_runner,
            completed=is_complete(lesson.id),
        )

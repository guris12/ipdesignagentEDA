"""
Reusable HTML components rendered via ``st.markdown(..., unsafe_allow_html=True)``.

Each helper returns an HTML string so callers can compose them or render inline.
All CSS classes are defined in ``theme.py`` and begin with the ``vg-`` prefix to
avoid colliding with Streamlit's own class names.
"""

from __future__ import annotations

import html
from typing import Literal, Optional

import streamlit as st

PillTone = Literal["blue", "green", "amber", "red", "gray"]
QueueStatus = Literal["active", "waiting", "idle"]
CalloutTone = Literal["blue", "green", "amber", "red"]


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def hero_header(
    title: str,
    subtitle: str = "",
    eyebrow: str = "",
    *,
    render: bool = True,
) -> str:
    """Big navy gradient hero banner for the Landing tab."""
    parts = ['<div class="vg-hero">']
    if eyebrow:
        parts.append(f'<div class="vg-hero-eyebrow">{_esc(eyebrow)}</div>')
    parts.append(f"<h1>{_esc(title)}</h1>")
    if subtitle:
        parts.append(f"<p>{_esc(subtitle)}</p>")
    parts.append("</div>")
    html_out = "".join(parts)
    if render:
        st.markdown(html_out, unsafe_allow_html=True)
    return html_out


def lesson_card(
    number: int,
    title: str,
    description: str,
    duration_min: Optional[int] = None,
    requires_runner: bool = False,
    completed: bool = False,
    *,
    render: bool = True,
) -> str:
    """Visual card for one lesson in the Lessons tab list."""
    meta_bits = []
    if duration_min is not None:
        meta_bits.append(f"~{duration_min} min")
    if requires_runner:
        meta_bits.append("uses runner")
    if completed:
        meta_bits.append("✓ completed")
    meta = " · ".join(meta_bits)
    html_out = (
        '<div class="vg-lesson-card">'
        f'<span class="vg-lesson-num">LESSON {number:02d}</span>'
        f"<h4>{_esc(title)}</h4>"
        f'<div style="color: var(--text-muted); font-size: 0.9rem; line-height: 1.55;">'
        f"{_esc(description)}</div>"
        f'<div class="vg-lesson-meta">{_esc(meta)}</div>'
        "</div>"
    )
    if render:
        st.markdown(html_out, unsafe_allow_html=True)
    return html_out


def stat_pill(
    label: str,
    value: str,
    tone: PillTone = "gray",
    *,
    render: bool = True,
) -> str:
    """Inline rounded pill for showing a labeled value (WNS, TNS, #violations, etc.)."""
    tone_class = "" if tone == "gray" else f" pill-{tone}"
    html_out = (
        f'<span class="vg-stat-pill{tone_class}">'
        f'<span class="vg-pill-label">{_esc(label)}</span>'
        f"<span>{_esc(value)}</span>"
        "</span>"
    )
    if render:
        st.markdown(html_out, unsafe_allow_html=True)
    return html_out


def queue_banner(
    status: QueueStatus,
    message: str,
    *,
    render: bool = True,
) -> str:
    """Banner shown at the top of the Lab tab indicating queue state."""
    html_out = (
        f'<div class="vg-queue-banner banner-{status}">'
        '<span class="vg-banner-dot"></span>'
        f"<span>{_esc(message)}</span>"
        "</div>"
    )
    if render:
        st.markdown(html_out, unsafe_allow_html=True)
    return html_out


def callout(
    body: str,
    title: str = "",
    tone: CalloutTone = "blue",
    *,
    render: bool = True,
) -> str:
    """Colored callout box for tips, warnings, and key takeaways inside lessons."""
    title_html = f"<strong>{_esc(title)}</strong>" if title else ""
    html_out = (
        f'<div class="vg-callout callout-{tone}">'
        f"{title_html}{_esc(body)}"
        "</div>"
    )
    if render:
        st.markdown(html_out, unsafe_allow_html=True)
    return html_out


def step_header(
    number: int,
    title: str,
    subtitle: str = "",
    *,
    render: bool = True,
) -> str:
    """Dark navy header bar used for each step inside a guided walkthrough."""
    sub_html = f'<span class="vg-step-sub">{_esc(subtitle)}</span>' if subtitle else ""
    html_out = (
        '<div class="vg-step-header">'
        f'<span class="vg-step-num">STEP {number:02d}</span>'
        f'<span class="vg-step-title">{_esc(title)}</span>'
        f"{sub_html}"
        "</div>"
    )
    if render:
        st.markdown(html_out, unsafe_allow_html=True)
    return html_out

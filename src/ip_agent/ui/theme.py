"""
Theme injection for the Streamlit app.

Ports the design system from /Users/ondevtratech/Documents/JobhuntAI/styles.css
into Streamlit by injecting one block of CSS at startup. Call ``inject_theme()``
exactly once, right after ``st.set_page_config`` in ``app.py``.
"""

from __future__ import annotations

import streamlit as st


_FONTS_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Fraunces:ital,wght@0,400;0,600;0,700;1,400"
    "&family=Plus+Jakarta+Sans:wght@400;500;600;700"
    "&family=JetBrains+Mono:wght@400;500"
    "&display=swap"
)


_CSS = """
<style>
:root {
  --navy: #1e3a5f;
  --navy-dark: #16304f;
  --navy-light: #264875;
  --blue: #2563eb;
  --blue-light: #dbeafe;
  --green: #16a34a;
  --green-light: #dcfce7;
  --amber: #d97706;
  --amber-light: #fef3c7;
  --red: #dc2626;
  --red-light: #fee2e2;
  --bg: #f1f5f9;
  --surface: #ffffff;
  --border: #e2e8f0;
  --text: #0f172a;
  --text-muted: #64748b;
  --text-light: #94a3b8;
  --code-bg: #1e293b;
  --font-sans: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
  --font-display: 'Fraunces', Georgia, serif;
  --font-mono: 'JetBrains Mono', 'Courier New', monospace;
}

html, body, [class*="css"], .stApp, .stMarkdown,
div[data-testid="stAppViewContainer"] {
  font-family: var(--font-sans) !important;
  color: var(--text);
}

.stApp { background: var(--bg); }

/* ── Headings ─────────────────────────────────── */
h1, .stMarkdown h1, div[data-testid="stHeading"] h1 {
  font-family: var(--font-display) !important;
  font-weight: 700 !important;
  color: var(--navy) !important;
  line-height: 1.2 !important;
  letter-spacing: -0.01em;
}

h2, .stMarkdown h2, div[data-testid="stHeading"] h2 {
  font-family: var(--font-display) !important;
  font-weight: 600 !important;
  color: var(--navy) !important;
  border-bottom: 2px solid var(--border);
  padding-bottom: 8px;
  margin-top: 1.5rem !important;
}

h3, h4, .stMarkdown h3, .stMarkdown h4 {
  font-family: var(--font-sans) !important;
  font-weight: 700 !important;
  color: var(--text) !important;
}

/* ── Body text ────────────────────────────────── */
.stMarkdown p, .stMarkdown li {
  font-size: 0.95rem;
  line-height: 1.65;
  color: var(--text);
}

.stCaption, [data-testid="stCaptionContainer"] {
  color: var(--text-muted) !important;
  font-size: 0.82rem !important;
}

/* ── Buttons ──────────────────────────────────── */
.stButton > button,
div[data-testid="stFormSubmitButton"] > button {
  font-family: var(--font-sans) !important;
  font-weight: 600 !important;
  border-radius: 8px !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  color: var(--text) !important;
  transition: all 0.15s ease !important;
  box-shadow: 0 1px 2px rgba(15,23,42,0.04);
}

.stButton > button:hover,
div[data-testid="stFormSubmitButton"] > button:hover {
  border-color: var(--blue) !important;
  color: var(--blue) !important;
  background: var(--blue-light) !important;
}

.stButton > button[kind="primary"],
div[data-testid="stFormSubmitButton"] > button[kind="primary"] {
  background: var(--blue) !important;
  color: #ffffff !important;
  border-color: var(--blue) !important;
}

.stButton > button[kind="primary"]:hover,
div[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
  background: #1d4ed8 !important;
  border-color: #1d4ed8 !important;
  color: #ffffff !important;
}

/* ── Tabs ─────────────────────────────────────── */
div[data-testid="stTabs"] button[role="tab"] {
  font-family: var(--font-sans) !important;
  font-weight: 600 !important;
  font-size: 0.95rem !important;
  color: var(--text-muted) !important;
  padding: 10px 18px !important;
}

div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  color: var(--navy) !important;
  border-bottom-color: var(--blue) !important;
}

/* ── Metrics ──────────────────────────────────── */
div[data-testid="stMetric"] {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 18px;
}

div[data-testid="stMetricLabel"] {
  font-size: 0.72rem !important;
  font-weight: 700 !important;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-muted) !important;
}

div[data-testid="stMetricValue"] {
  font-family: var(--font-display) !important;
  font-weight: 700 !important;
  color: var(--navy) !important;
}

/* ── Expanders ────────────────────────────────── */
div[data-testid="stExpander"] {
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
  background: var(--surface);
}

div[data-testid="stExpander"] summary {
  font-weight: 600 !important;
  color: var(--navy) !important;
}

/* ── Sidebar ──────────────────────────────────── */
section[data-testid="stSidebar"] {
  background: var(--navy) !important;
  border-right: 1px solid rgba(255,255,255,0.05);
}

section[data-testid="stSidebar"] * {
  color: rgba(255,255,255,0.85) !important;
}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4 {
  color: #ffffff !important;
  font-family: var(--font-display) !important;
}

section[data-testid="stSidebar"] .stButton > button {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
  color: rgba(255,255,255,0.85) !important;
  text-align: left !important;
  justify-content: flex-start !important;
}

section[data-testid="stSidebar"] .stButton > button:hover {
  background: rgba(37,99,235,0.25) !important;
  border-color: rgba(147,197,253,0.4) !important;
  color: #ffffff !important;
}

section[data-testid="stSidebar"] pre,
section[data-testid="stSidebar"] code {
  background: rgba(0,0,0,0.25) !important;
  color: #e2e8f0 !important;
  border-radius: 6px;
  font-family: var(--font-mono) !important;
  font-size: 0.78rem !important;
}

section[data-testid="stSidebar"] hr {
  border-top: 1px solid rgba(255,255,255,0.08) !important;
}

/* ── Code blocks ──────────────────────────────── */
pre, code, .stCode {
  font-family: var(--font-mono) !important;
  font-size: 0.82rem !important;
}

div[data-testid="stCodeBlock"] pre {
  background: var(--code-bg) !important;
  border-radius: 10px !important;
  padding: 16px 18px !important;
}

/* ── Chat messages ────────────────────────────── */
div[data-testid="stChatMessage"] {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 18px;
  margin-bottom: 10px;
}

/* ── Inputs ───────────────────────────────────── */
div[data-baseweb="input"] > div,
div[data-baseweb="select"] > div,
div[data-baseweb="textarea"] > div {
  border-radius: 8px !important;
  border-color: var(--border) !important;
}

/* ── Dividers ─────────────────────────────────── */
hr { border-top-color: var(--border) !important; }

/* ── Our custom components (HTML string helpers) ─ */
.vg-lesson-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 12px;
  transition: all 0.15s ease;
}
.vg-lesson-card:hover { border-color: var(--blue); box-shadow: 0 4px 12px rgba(37,99,235,0.08); }
.vg-lesson-card .vg-lesson-num {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--blue);
  background: var(--blue-light);
  padding: 3px 9px;
  border-radius: 6px;
  margin-bottom: 8px;
}
.vg-lesson-card h4 {
  font-family: var(--font-display);
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--navy);
  margin: 0 0 4px 0;
}
.vg-lesson-card .vg-lesson-meta {
  font-size: 0.78rem;
  color: var(--text-muted);
  margin-top: 8px;
}

.vg-stat-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 12px;
  font-size: 0.8rem;
  font-weight: 600;
  margin-right: 6px;
  margin-bottom: 4px;
}
.vg-stat-pill .vg-pill-label { color: var(--text-muted); font-weight: 500; }
.vg-stat-pill.pill-green { background: var(--green-light); border-color: transparent; color: #15803d; }
.vg-stat-pill.pill-amber { background: var(--amber-light); border-color: transparent; color: #b45309; }
.vg-stat-pill.pill-red   { background: var(--red-light);   border-color: transparent; color: #b91c1c; }
.vg-stat-pill.pill-blue  { background: var(--blue-light);  border-color: transparent; color: #1d4ed8; }

.vg-queue-banner {
  border-radius: 12px;
  padding: 14px 18px;
  margin: 8px 0 16px 0;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.9rem;
  font-weight: 500;
}
.vg-queue-banner .vg-banner-dot {
  width: 10px; height: 10px; border-radius: 50%;
  box-shadow: 0 0 0 4px rgba(255,255,255,0.5);
}
.vg-queue-banner.banner-active {
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
  color: #14532d;
}
.vg-queue-banner.banner-active .vg-banner-dot { background: var(--green); }
.vg-queue-banner.banner-waiting {
  background: var(--amber-light);
  color: #92400e;
}
.vg-queue-banner.banner-waiting .vg-banner-dot { background: var(--amber); }
.vg-queue-banner.banner-idle {
  background: var(--blue-light);
  color: #1e40af;
}
.vg-queue-banner.banner-idle .vg-banner-dot { background: var(--blue); }

.vg-callout {
  border-radius: 10px;
  padding: 14px 18px;
  margin: 12px 0;
  border-left: 4px solid;
  font-size: 0.9rem;
  line-height: 1.6;
}
.vg-callout strong { display: block; margin-bottom: 4px; font-weight: 700; }
.vg-callout.callout-blue  { background: var(--blue-light);  border-color: var(--blue);  color: #1e3a8a; }
.vg-callout.callout-green { background: var(--green-light); border-color: var(--green); color: #14532d; }
.vg-callout.callout-amber { background: var(--amber-light); border-color: var(--amber); color: #78350f; }
.vg-callout.callout-red   { background: var(--red-light);   border-color: var(--red);   color: #7f1d1d; }
.vg-callout.callout-blue  strong { color: #1d4ed8; }
.vg-callout.callout-green strong { color: #15803d; }
.vg-callout.callout-amber strong { color: #b45309; }
.vg-callout.callout-red   strong { color: #b91c1c; }

.vg-step-header {
  background: var(--navy);
  color: #fff;
  padding: 12px 18px;
  border-radius: 10px 10px 0 0;
  display: flex;
  align-items: center;
  gap: 12px;
  font-family: var(--font-sans);
}
.vg-step-header .vg-step-num {
  background: rgba(255,255,255,0.15);
  font-family: var(--font-mono);
  font-size: 0.72rem;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 6px;
}
.vg-step-header .vg-step-title { font-weight: 600; font-size: 0.95rem; }
.vg-step-header .vg-step-sub { margin-left: auto; font-size: 0.78rem; color: rgba(255,255,255,0.6); }

.vg-hero {
  background: linear-gradient(135deg, var(--navy) 0%, #264875 100%);
  border-radius: 16px;
  padding: 36px 40px;
  color: #fff;
  margin-bottom: 24px;
}
.vg-hero .vg-hero-eyebrow {
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: #93c5fd;
  margin-bottom: 10px;
}
.vg-hero h1 {
  font-family: var(--font-display);
  font-size: 2.3rem !important;
  font-weight: 700;
  color: #fff !important;
  line-height: 1.15;
  margin-bottom: 10px;
}
.vg-hero p {
  font-size: 1.02rem;
  color: rgba(255,255,255,0.8);
  max-width: 640px;
  line-height: 1.6;
}
</style>
"""


def inject_theme() -> None:
    """Inject the design system. Call once right after ``st.set_page_config``."""
    st.markdown(
        f'<link rel="preconnect" href="https://fonts.googleapis.com">'
        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link href="{_FONTS_URL}" rel="stylesheet">',
        unsafe_allow_html=True,
    )
    st.markdown(_CSS, unsafe_allow_html=True)

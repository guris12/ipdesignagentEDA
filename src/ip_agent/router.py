"""
Deterministic Router — Rule-based routing that fires BEFORE semantic search.

Why deterministic routing?
- LLM-based tool selection is non-deterministic (sometimes picks wrong tool)
- For critical queries (e.g., "report timing violations"), we MUST hit the right tool
- Rules are 100% reliable, fast (no LLM call), and auditable
- Falls through to semantic routing only if no rule matches

Architecture:
    Query → [Deterministic Rules] → match? → Route directly to tool
                                  → no match? → Fall through to LLM/semantic routing

Swift analogy: Like a URLRouter with pattern matching — exact patterns get
handled by specific handlers, anything else falls through to the default handler.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Route Definitions
# ---------------------------------------------------------------------------

class Route(str, Enum):
    """Named routes that map to specific tool/action chains."""
    SEARCH_DOCS = "search_documentation"
    SEARCH_TIMING = "search_timing_reports"
    ANALYZE_VIOLATIONS = "analyze_violations"
    FIX_SETUP = "fix_setup_violations"
    FIX_HOLD = "fix_hold_violations"
    EXPLAIN_CONCEPT = "explain_concept"
    OPENROAD_COMMAND = "openroad_command"
    OPENSTA_COMMAND = "opensta_command"
    GENERAL = "general"  # Fall-through to LLM routing


# ---------------------------------------------------------------------------
# Routing Rules
# ---------------------------------------------------------------------------

@dataclass
class RoutingRule:
    """A single deterministic routing rule."""
    route: Route
    patterns: list[str]  # Regex patterns (any match triggers this route)
    priority: int = 0    # Higher = checked first
    description: str = ""


# Rules ordered by priority (most specific first)
ROUTING_RULES: list[RoutingRule] = [
    # --- Timing violation analysis ---
    RoutingRule(
        route=Route.ANALYZE_VIOLATIONS,
        patterns=[
            r"(?i)(report|show|list|display)\s+(all\s+)?(timing\s+)?violations",
            r"(?i)what\s+(are|is)\s+(the\s+)?(worst|critical)\s+(violation|slack|path)",
            r"(?i)(wns|tns|worst\s+negative\s+slack|total\s+negative\s+slack)",
            r"(?i)timing\s+summary",
        ],
        priority=100,
        description="Direct violation analysis queries",
    ),
    # --- Setup fix guidance ---
    RoutingRule(
        route=Route.FIX_SETUP,
        patterns=[
            r"(?i)(fix|repair|resolve|close)\s+(setup|max\s+delay)\s+(violation|timing|issue)",
            r"(?i)how\s+to\s+(fix|close|resolve)\s+setup",
            r"(?i)setup\s+(fix|repair|closure)",
        ],
        priority=90,
        description="Setup violation fix queries",
    ),
    # --- Hold fix guidance ---
    RoutingRule(
        route=Route.FIX_HOLD,
        patterns=[
            r"(?i)(fix|repair|resolve|close)\s+(hold|min\s+delay)\s+(violation|timing|issue)",
            r"(?i)how\s+to\s+(fix|close|resolve)\s+hold",
            r"(?i)hold\s+(fix|repair|closure)",
        ],
        priority=90,
        description="Hold violation fix queries",
    ),
    # --- OpenSTA commands ---
    RoutingRule(
        route=Route.OPENSTA_COMMAND,
        patterns=[
            r"(?i)(report_checks|report_timing|set_input_delay|set_output_delay)",
            r"(?i)(create_clock|set_clock_uncertainty|set_false_path)",
            r"(?i)opensta\s+(command|syntax|usage)",
            r"(?i)how\s+to\s+use\s+.+\s+in\s+opensta",
        ],
        priority=80,
        description="OpenSTA command syntax queries",
    ),
    # --- OpenROAD commands ---
    RoutingRule(
        route=Route.OPENROAD_COMMAND,
        patterns=[
            r"(?i)(detailed_placement|global_route|detailed_route|clock_tree_synthesis)",
            r"(?i)(place_design|route_design|optimize_design)",
            r"(?i)openroad\s+(command|syntax|flow|usage)",
            r"(?i)how\s+to\s+use\s+.+\s+in\s+openroad",
        ],
        priority=80,
        description="OpenROAD command queries",
    ),
    # --- Timing report search ---
    RoutingRule(
        route=Route.SEARCH_TIMING,
        patterns=[
            r"(?i)(search|find|look\s+up)\s+(in\s+)?(timing\s+report|\.rpt)",
            r"(?i)(slack|delay|path)\s+(for|of|in)\s+\w+",
            r"(?i)timing\s+(of|for|on)\s+\w+",
        ],
        priority=70,
        description="Timing report-specific search",
    ),
    # --- Documentation search ---
    RoutingRule(
        route=Route.SEARCH_DOCS,
        patterns=[
            r"(?i)(search|find|look\s+up)\s+(in\s+)?(documentation|docs|manual)",
            r"(?i)(what\s+does|explain|describe)\s+the\s+\w+\s+(command|function|option)",
        ],
        priority=60,
        description="Documentation search queries",
    ),
    # --- Concept explanation ---
    RoutingRule(
        route=Route.EXPLAIN_CONCEPT,
        patterns=[
            r"(?i)what\s+is\s+(a\s+)?(setup\s+time|hold\s+time|slack|clock\s+skew|jitter)",
            r"(?i)(define|explain|describe)\s+.{0,20}(setup|hold|slack|skew|metastability|timing|clock|jitter)",
            r"(?i)difference\s+between\s+.+\s+and\s+",
        ],
        priority=50,
        description="EDA concept explanations",
    ),
]


# ---------------------------------------------------------------------------
# Router Logic
# ---------------------------------------------------------------------------

def route_query(query: str) -> Route:
    """
    Attempt deterministic routing. Returns Route.GENERAL if no rule matches.

    This is fast (regex only, no LLM call) and 100% reliable.
    """
    # Sort rules by priority (highest first)
    sorted_rules = sorted(ROUTING_RULES, key=lambda r: r.priority, reverse=True)

    for rule in sorted_rules:
        for pattern in rule.patterns:
            if re.search(pattern, query):
                logger.info(
                    f"Deterministic route matched: {rule.route.value} "
                    f"(pattern: {pattern[:40]}...)"
                )
                return rule.route

    logger.info("No deterministic route matched — falling through to LLM routing")
    return Route.GENERAL


def get_route_description(route: Route) -> str:
    """Get human-readable description of what a route does."""
    descriptions = {
        Route.SEARCH_DOCS: "Search OpenROAD/OpenSTA documentation",
        Route.SEARCH_TIMING: "Search timing reports for specific paths/slack",
        Route.ANALYZE_VIOLATIONS: "Analyze timing violations from reports",
        Route.FIX_SETUP: "Provide setup violation fix strategies",
        Route.FIX_HOLD: "Provide hold violation fix strategies",
        Route.EXPLAIN_CONCEPT: "Explain an EDA/timing concept",
        Route.OPENROAD_COMMAND: "Look up OpenROAD command syntax",
        Route.OPENSTA_COMMAND: "Look up OpenSTA command syntax",
        Route.GENERAL: "General query — use LLM routing",
    }
    return descriptions.get(route, "Unknown route")

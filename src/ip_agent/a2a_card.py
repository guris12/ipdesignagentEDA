"""
A2A Agent Card — Discovery metadata for the Agent-to-Agent protocol.

A2A (Agent-to-Agent) is Google's protocol for agents to discover and
communicate with each other. The Agent Card is a JSON-LD document that
describes what this agent can do, so other agents can find and delegate to it.

Architecture:
    Other Agent → discovers Agent Card → sends task → this agent processes → returns result

Swift analogy: Like an App Clip Card — metadata that tells the system what
your app can do before it's even launched.

Spec: https://google.github.io/A2A/
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Agent Card Definition
# ---------------------------------------------------------------------------

AGENT_CARD: dict[str, Any] = {
    "@context": "https://google.github.io/A2A/context.jsonld",
    "@type": "AgentCard",
    "name": "IP Design Intelligence Agent",
    "description": (
        "Expert assistant for digital IC physical design and static timing analysis. "
        "Specializes in OpenROAD/OpenSTA toolchains, timing closure, and EDA workflows."
    ),
    "version": "0.1.0",
    "url": "http://localhost:8001",  # Updated at deployment
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
    },
    "skills": [
        {
            "id": "search_documentation",
            "name": "EDA Documentation Search",
            "description": "Search OpenROAD and OpenSTA documentation for commands, flows, and options",
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "analyze_timing",
            "name": "Timing Analysis",
            "description": "Analyze timing reports, identify violations, report WNS/TNS",
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "suggest_fixes",
            "name": "Timing Fix Suggestions",
            "description": "Suggest strategies to fix setup/hold timing violations",
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
        {
            "id": "explain_concepts",
            "name": "EDA Concept Explanation",
            "description": "Explain physical design and timing concepts",
            "inputModes": ["text"],
            "outputModes": ["text"],
        },
    ],
    "authentication": {
        "schemes": ["bearer"],
    },
    "provider": {
        "organization": "IP Design Intelligence",
        "url": "https://github.com/gursimran-sodhi/ip-design-agent",
    },
}


def get_agent_card(base_url: str = "http://localhost:8001") -> dict[str, Any]:
    """Get the Agent Card with the correct base URL."""
    card = AGENT_CARD.copy()
    card["url"] = base_url
    return card

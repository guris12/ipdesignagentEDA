"""Tests for the LangGraph agent."""

import pytest
from unittest.mock import patch, AsyncMock

from ip_agent.agent import build_agent_graph, create_agent, GraphState
from ip_agent.models import AgentState


class TestAgentGraph:
    """Test agent graph construction."""

    def test_graph_builds(self):
        """Graph should compile without errors."""
        graph = build_agent_graph()
        assert graph is not None

    def test_agent_creates(self):
        """Agent should compile from graph."""
        agent = create_agent()
        assert agent is not None

    def test_graph_has_expected_nodes(self):
        """Graph should contain all required nodes."""
        graph = build_agent_graph()
        node_names = set(graph.nodes.keys())
        expected = {"router", "model_selector", "agent", "tools", "guardrails"}
        assert expected.issubset(node_names)


class TestAgentState:
    """Test Pydantic state model."""

    def test_default_state(self):
        state = AgentState(query="test question")
        assert state.query == "test question"
        assert state.model_tier == "gpt-4o-mini"
        assert state.guardrail_passed is True
        assert state.contexts == []

    def test_state_with_route(self):
        state = AgentState(query="fix setup", route="fix_setup_violations")
        assert state.route == "fix_setup_violations"

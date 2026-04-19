"""Tests for the hybrid retriever module."""

import pytest
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document

from ip_agent.router import route_query, Route


class TestDeterministicRouter:
    """Test the deterministic routing rules."""

    def test_setup_fix_route(self):
        assert route_query("How to fix setup violations?") == Route.FIX_SETUP
        assert route_query("fix setup timing issue") == Route.FIX_SETUP

    def test_hold_fix_route(self):
        assert route_query("How to fix hold violations?") == Route.FIX_HOLD
        assert route_query("resolve hold timing issue") == Route.FIX_HOLD

    def test_violation_analysis_route(self):
        assert route_query("report all timing violations") == Route.ANALYZE_VIOLATIONS
        assert route_query("what is the worst slack?") == Route.ANALYZE_VIOLATIONS
        assert route_query("show WNS") == Route.ANALYZE_VIOLATIONS

    def test_opensta_command_route(self):
        assert route_query("report_checks command") == Route.OPENSTA_COMMAND
        assert route_query("set_input_delay syntax") == Route.OPENSTA_COMMAND

    def test_openroad_command_route(self):
        assert route_query("detailed_placement options") == Route.OPENROAD_COMMAND
        assert route_query("openroad command for routing") == Route.OPENROAD_COMMAND

    def test_concept_explanation_route(self):
        assert route_query("what is setup time?") == Route.EXPLAIN_CONCEPT
        assert route_query("explain clock skew") == Route.EXPLAIN_CONCEPT

    def test_general_fallthrough(self):
        assert route_query("hello") == Route.GENERAL
        assert route_query("tell me a joke") == Route.GENERAL

    def test_doc_search_route(self):
        assert route_query("search documentation for buffer insertion") == Route.SEARCH_DOCS

    def test_timing_search_route(self):
        assert route_query("search timing report for clk path") == Route.SEARCH_TIMING

"""
LangGraph Agent — The core agentic workflow for IP Design Intelligence.

Architecture (refined with deterministic routing + cost routing + guardrails):

    Query → [Deterministic Router] → matched? → Direct tool call
                                   → no match ↓
            [Cost Router] → select model tier
                         ↓
            [LLM + Tools] → generate answer
                         ↓
            [Guardrails] → validate → pass? → Return answer
                                    → fail? → Regenerate with feedback

This is a LangGraph StateGraph — each box above is a node, arrows are edges.
The graph compiles to an executable that handles state transitions automatically.

Swift analogy: Like a Combine pipeline or async/await chain, but with
explicit state machine semantics. Each node is a pure function that takes
state in and returns modified state out.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from ip_agent.config import MODEL_CHEAP, MODEL_STANDARD, MAX_AGENT_ITERATIONS
from ip_agent.router import route_query, Route, get_route_description
from ip_agent.tools import ALL_TOOLS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent State (TypedDict for LangGraph compatibility)
# ---------------------------------------------------------------------------

from typing import TypedDict, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class GraphState(TypedDict):
    """State schema for the LangGraph agent."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    query: str
    route: str
    model_tier: str
    contexts: list[str]
    answer: str
    guardrail_passed: bool
    guardrail_score: float
    iteration: int


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert EDA (Electronic Design Automation) engineer assistant
specializing in digital IC physical design, static timing analysis, and the
OpenROAD/OpenSTA open-source EDA toolchain.

Your expertise includes:
- Static Timing Analysis (STA): setup/hold checks, slack, clock domains
- Physical design: placement, routing, clock tree synthesis, optimization
- OpenROAD flow: from RTL synthesis through GDSII
- OpenSTA commands: report_checks, create_clock, timing constraints
- Timing closure: fixing violations, ECO strategies, multi-corner/multi-mode

Guidelines:
1. Always ground your answers in the retrieved documentation/reports
2. When suggesting fixes, be specific about commands and parameters
3. Distinguish between setup vs hold violations clearly
4. Reference specific tools and their options when applicable
5. If you don't know something, say so — never fabricate tool commands

You have access to tools for searching documentation and timing reports.
Use them to find relevant information before answering."""


# ---------------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------------

def deterministic_router_node(state: GraphState) -> dict:
    """
    Node 1: Try deterministic routing first.
    If a rule matches, set the route. Otherwise, fall through.
    """
    query = state["query"]
    route = route_query(query)

    logger.info(f"Router: query='{query[:50]}...' → route={route.value}")

    return {
        "route": route.value,
        "iteration": state.get("iteration", 0),
    }


def model_selector_node(state: GraphState) -> dict:
    """
    Node 2: Select model tier based on query complexity.

    Simple queries (definitions, lookups) → gpt-4o-mini
    Complex queries (debugging, multi-step analysis) → gpt-4o
    """
    query = state["query"]
    route = state.get("route", "general")

    # Simple routes get cheap model
    cheap_routes = {
        Route.EXPLAIN_CONCEPT.value,
        Route.OPENSTA_COMMAND.value,
        Route.OPENROAD_COMMAND.value,
        Route.SEARCH_DOCS.value,
    }

    if route in cheap_routes:
        tier = MODEL_CHEAP
    elif route in {Route.ANALYZE_VIOLATIONS.value, Route.FIX_SETUP.value, Route.FIX_HOLD.value}:
        tier = MODEL_STANDARD
    else:
        # Heuristic: longer queries or those with multiple clauses → standard
        if len(query.split()) > 20 or " and " in query.lower():
            tier = MODEL_STANDARD
        else:
            tier = MODEL_CHEAP

    logger.info(f"Model selector: {tier}")
    return {"model_tier": tier}


def agent_node(state: GraphState) -> dict:
    """
    Node 3: The LLM agent — calls tools and generates responses.
    """
    model_tier = state.get("model_tier", MODEL_CHEAP)
    messages = list(state["messages"])

    # Inject system prompt if not present
    if not messages or not isinstance(messages[0], SystemMessage):
        messages.insert(0, SystemMessage(content=SYSTEM_PROMPT))

    # Create LLM with tools bound
    llm = ChatOpenAI(model=model_tier, temperature=0)
    llm_with_tools = llm.bind_tools(ALL_TOOLS)

    response = llm_with_tools.invoke(messages)

    return {"messages": [response]}


def guardrail_node(state: GraphState) -> dict:
    """
    Node 4: Validate the agent's response.

    Checks:
    - Is the answer grounded in retrieved context?
    - Are EDA terms used correctly?
    - Is the format appropriate?
    """
    messages = state["messages"]
    last_message = messages[-1] if messages else None

    if not last_message or not isinstance(last_message, AIMessage):
        return {"guardrail_passed": True, "guardrail_score": 1.0}

    answer = last_message.content
    if not answer:
        # Tool call in progress, no answer to validate yet
        return {"guardrail_passed": True, "guardrail_score": 1.0}

    # Basic validation (full guardrails module integration would go here)
    issues = []

    # Check 1: Answer not empty
    if len(answer.strip()) < 10:
        issues.append("Answer too short")

    # Check 2: No hallucinated commands (basic check)
    suspicious_patterns = [
        "run_timing_fix",  # Not a real command
        "auto_optimize",   # Not a real command
        "fix_all",         # Not a real command
    ]
    for pattern in suspicious_patterns:
        if pattern in answer.lower():
            issues.append(f"Suspicious command: {pattern}")

    score = 1.0 - (len(issues) * 0.2)
    passed = score >= 0.6

    if not passed:
        logger.warning(f"Guardrail FAILED: {issues}")

    return {
        "guardrail_passed": passed,
        "guardrail_score": max(0.0, score),
    }


# ---------------------------------------------------------------------------
# Conditional Edges
# ---------------------------------------------------------------------------

def should_continue(state: GraphState) -> str:
    """After agent node: continue with tools or finish?"""
    messages = state["messages"]
    last_message = messages[-1] if messages else None

    # Check iteration limit
    iteration = state.get("iteration", 0)
    if iteration >= MAX_AGENT_ITERATIONS:
        logger.warning("Hit max iterations — forcing end")
        return "end"

    # If the LLM made tool calls, route to tools
    if last_message and hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "guardrails"


def after_guardrails(state: GraphState) -> str:
    """After guardrails: accept or retry?"""
    if state.get("guardrail_passed", True):
        return "end"

    # Only retry once
    iteration = state.get("iteration", 0)
    if iteration >= 2:
        return "end"

    return "retry"


# ---------------------------------------------------------------------------
# Build the Graph
# ---------------------------------------------------------------------------

def build_agent_graph() -> StateGraph:
    """
    Construct the LangGraph agent with all nodes and edges.

    Graph structure:
        START → router → model_selector → agent → should_continue?
                                                     ├── tools → agent (loop)
                                                     └── guardrails → after_guardrails?
                                                                        ├── end
                                                                        └── agent (retry)
    """
    graph = StateGraph(GraphState)

    # Add nodes
    graph.add_node("router", deterministic_router_node)
    graph.add_node("model_selector", model_selector_node)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.add_node("guardrails", guardrail_node)

    # Set entry point
    graph.set_entry_point("router")

    # Add edges
    graph.add_edge("router", "model_selector")
    graph.add_edge("model_selector", "agent")

    # Conditional: after agent, either call tools or go to guardrails
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "guardrails": "guardrails",
            "end": END,
        },
    )

    # Tools loop back to agent
    graph.add_edge("tools", "agent")

    # After guardrails: end or retry
    graph.add_conditional_edges(
        "guardrails",
        after_guardrails,
        {
            "end": END,
            "retry": "agent",
        },
    )

    return graph


# ---------------------------------------------------------------------------
# Compiled Agent (ready to invoke)
# ---------------------------------------------------------------------------

def create_agent():
    """Create and compile the agent graph."""
    graph = build_agent_graph()
    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

async def ask(query: str, chat_history: list[dict] | None = None) -> str:
    """
    Ask the agent a question. Returns the final answer string.

    Usage:
        answer = await ask("How do I fix setup violations?")
    """
    agent = create_agent()

    # Build messages
    messages: list[BaseMessage] = []
    if chat_history:
        for msg in chat_history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=query))

    # Invoke
    initial_state: GraphState = {
        "messages": messages,
        "query": query,
        "route": "",
        "model_tier": MODEL_CHEAP,
        "contexts": [],
        "answer": "",
        "guardrail_passed": True,
        "guardrail_score": 1.0,
        "iteration": 0,
    }

    result = await agent.ainvoke(initial_state)

    # Extract final answer from last AI message
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content

    return "I wasn't able to generate an answer. Please try rephrasing your question."

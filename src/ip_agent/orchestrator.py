"""
Multi-Agent Orchestrator — Coordinates 3 specialist agents via LangGraph.

This demonstrates the core pattern for Synopsys/Broadcom:
    Engineer: "Close timing on block_alu, don't introduce DRC violations"

    Orchestrator:
        Step 1: Timing Agent → finds setup violations (-0.14ns worst)
        Step 2: DRC Agent → checks DRC status (5 violations, congested region)
        Step 3: Physical Agent → suggests fixes (conservative sizing due to DRC)
        Step 4: Merge → unified report with Tcl ECO script

Architecture:
    Query → [Orchestrator]
               ├── [Timing Agent]   → reads .rpt, finds violations, reports WNS/TNS
               ├── [DRC Agent]      → reads DRC report, maps congested regions
               └── [Physical Agent] → reads cell report, generates ECO fixes
             → [Merge] → unified answer + fix_timing.tcl

This is EXACTLY how MMMC timing closure works in production:
    - Multiple domains (timing, DRC, physical) must coordinate
    - Fixes in one domain can break another (buffer insertion → DRC violations)
    - The orchestrator ensures cross-domain awareness

LangGraph makes this a state machine — each step is a node, data flows
through edges, and the graph handles the coordination automatically.

Swift analogy: Like a TaskGroup with 3 child tasks that share context
through an actor-isolated state dictionary.
"""

from __future__ import annotations

import logging
from typing import TypedDict, Annotated, Sequence, Any

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from ip_agent.config import MODEL_STANDARD
from ip_agent.specialists import TimingAgent, DRCAgent, PhysicalAgent
from ip_agent.tools import (
    search_documentation,
    search_timing_reports,
    analyze_timing_violations,
    suggest_timing_fix,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Orchestrator State
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict):
    """State for the multi-agent orchestrator."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    query: str
    # Specialist results (passed between agents as shared context)
    timing_result: dict[str, Any]
    drc_result: dict[str, Any]
    physical_result: dict[str, Any]
    # Final
    final_answer: str


# ---------------------------------------------------------------------------
# Orchestrator Nodes — Each calls a specialist agent
# ---------------------------------------------------------------------------

async def timing_analysis_node(state: OrchestratorState) -> dict:
    """
    Step 1: Timing Agent analyzes violations.

    EDA analogy: Running PrimeTime report_timing across all corners.
    """
    query = state["query"]
    logger.info(f"[Timing Agent] Analyzing: {query}")

    agent = TimingAgent()
    result = await agent.process(query)

    logger.info(f"[Timing Agent] Found: {result.get('severity', 'unknown')} severity")
    return {"timing_result": result}


async def drc_check_node(state: OrchestratorState) -> dict:
    """
    Step 2: DRC Agent checks physical violations.

    EDA analogy: Running ICV/Calibre DRC on the same block.
    Uses timing findings to focus on the right region.
    """
    query = state["query"]
    timing_result = state.get("timing_result", {})
    logger.info(f"[DRC Agent] Checking DRC status")

    agent = DRCAgent()
    result = await agent.process(query, context={"timing_findings": timing_result})

    logger.info(f"[DRC Agent] Found: {result.get('severity', 'unknown')} severity, "
                f"congested={result.get('congested_region', False)}")
    return {"drc_result": result}


async def physical_fix_node(state: OrchestratorState) -> dict:
    """
    Step 3: Physical Agent generates ECO fixes.

    EDA analogy: Running ICC2 ECO commands — but DRC-aware.
    This is the key insight: fixes must respect DRC constraints.

    The Physical Agent receives context from BOTH Timing and DRC agents,
    so it can make smart decisions (e.g., use resizing instead of buffer
    insertion in congested regions).
    """
    query = state["query"]
    timing_result = state.get("timing_result", {})
    drc_result = state.get("drc_result", {})
    logger.info(f"[Physical Agent] Generating fixes (DRC-aware)")

    # Pass DRC context so Physical Agent knows about congestion
    context = {
        "timing_findings": timing_result.get("findings", ""),
        "affected_nets": drc_result.get("affected_nets", []),
        "congested_region": drc_result.get("congested_region", False),
    }

    agent = PhysicalAgent()
    result = await agent.process(query, context=context)

    logger.info(f"[Physical Agent] Generated {result.get('fix_count', 0)} ECO commands")
    return {"physical_result": result}


async def merge_results_node(state: OrchestratorState) -> dict:
    """
    Step 4: Merge all specialist findings into unified report.

    EDA analogy: The timing closure review meeting where PD, STA, and DRC
    engineers present their findings and agree on a plan.
    """
    timing = state.get("timing_result", {})
    drc = state.get("drc_result", {})
    physical = state.get("physical_result", {})

    # Build unified report
    sections = []

    sections.append("=" * 70)
    sections.append("  MULTI-AGENT TIMING CLOSURE REPORT")
    sections.append("=" * 70)

    # Timing section
    sections.append("\n--- TIMING ANALYSIS (Timing Agent) ---")
    sections.append(f"Severity: {timing.get('severity', 'N/A').upper()}")
    sections.append(timing.get("findings", "No timing data available"))
    if timing.get("recommendations"):
        sections.append("\nRecommendations:")
        for r in timing["recommendations"]:
            sections.append(f"  - {r}")

    # DRC section
    sections.append("\n--- DRC STATUS (DRC Agent) ---")
    sections.append(f"Severity: {drc.get('severity', 'N/A').upper()}")
    sections.append(drc.get("findings", "No DRC data available"))
    if drc.get("recommendations"):
        sections.append("\nRecommendations:")
        for r in drc["recommendations"]:
            sections.append(f"  - {r}")

    # Physical fix section
    sections.append("\n--- ECO FIX PLAN (Physical Agent) ---")
    sections.append(f"Severity: {physical.get('severity', 'N/A').upper()}")
    sections.append(physical.get("findings", "No fixes generated"))
    if physical.get("recommendations"):
        sections.append("\nRecommendations:")
        for r in physical["recommendations"]:
            sections.append(f"  - {r}")

    # Cross-domain summary
    sections.append("\n" + "=" * 70)
    sections.append("  CROSS-DOMAIN SUMMARY")
    sections.append("=" * 70)

    tcl_commands = physical.get("tcl_commands", [])
    congested = drc.get("congested_region", False)

    if tcl_commands:
        sections.append(f"\nECO Script ({len(tcl_commands)} commands):")
        sections.append("  # fix_timing.tcl — generated by Physical Agent")
        sections.append(f"  # DRC-aware: {'YES' if congested else 'NO'}")
        for cmd in tcl_commands:
            sections.append(f"  {cmd}")
        sections.append("\nNext Steps:")
        sections.append("  1. source fix_timing.tcl   (apply ECO)")
        sections.append("  2. report_timing           (verify timing)")
        sections.append("  3. check_drc               (verify no new DRC)")
    else:
        sections.append("\nNo ECO fixes generated. Manual review needed.")

    final_answer = "\n".join(sections)

    return {
        "final_answer": final_answer,
        "messages": [AIMessage(content=final_answer)],
    }


# ---------------------------------------------------------------------------
# Build Orchestrator Graph
# ---------------------------------------------------------------------------

def build_orchestrator_graph() -> StateGraph:
    """
    Build the 3-agent orchestrator.

    Graph: timing → drc → physical → merge → END

    Sequential because each agent needs context from the previous:
    - DRC needs to know which region timing is failing in
    - Physical needs to know DRC constraints before suggesting fixes
    """
    graph = StateGraph(OrchestratorState)

    graph.add_node("timing_analysis", timing_analysis_node)
    graph.add_node("drc_check", drc_check_node)
    graph.add_node("physical_fix", physical_fix_node)
    graph.add_node("merge", merge_results_node)

    graph.set_entry_point("timing_analysis")
    graph.add_edge("timing_analysis", "drc_check")
    graph.add_edge("drc_check", "physical_fix")
    graph.add_edge("physical_fix", "merge")
    graph.add_edge("merge", END)

    return graph


def create_orchestrator():
    """Create and compile the orchestrator."""
    return build_orchestrator_graph().compile()


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

async def orchestrate(query: str) -> str:
    """
    Run the full multi-agent timing closure flow.

    Usage:
        result = await orchestrate("Close timing on block_alu, don't break DRC")
    """
    orchestrator = create_orchestrator()

    initial_state: OrchestratorState = {
        "messages": [HumanMessage(content=query)],
        "query": query,
        "timing_result": {},
        "drc_result": {},
        "physical_result": {},
        "final_answer": "",
    }

    result = await orchestrator.ainvoke(initial_state)
    return result.get("final_answer", "No answer generated.")


async def orchestrate_timing_closure(block_name: str = "block_alu") -> str:
    """
    Shortcut for the common case: close timing on a block.

    This is the demo function — shows the full 3-agent flow.
    """
    return await orchestrate(
        f"Analyze timing violations on {block_name}, check DRC status, "
        f"and suggest fixes that close timing without introducing new DRC violations."
    )

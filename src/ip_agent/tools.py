"""
Agent Tools — LangChain @tool functions for the IP Design Agent.

These are the actions the agent can take. Each tool is a function the LLM
can invoke when it needs specific information or capabilities.

Architecture:
    1. Deterministic router tries to match query → tool (100% reliable)
    2. If no match, LLM picks tool via function-calling (semantic selection)
    3. Tool executes and returns results to the agent

Swift analogy: Each @tool is like an Intent in Shortcuts — a declared action
with typed inputs/outputs that the system can invoke on behalf of the user.
"""

from __future__ import annotations

from langchain_core.tools import tool
from langchain_core.documents import Document

from ip_agent.config import TOP_K_RESULTS
from ip_agent.retriever import hybrid_search, hybrid_search_filtered, search_with_score


# ---------------------------------------------------------------------------
# Documentation Search Tools
# ---------------------------------------------------------------------------

@tool
def search_documentation(query: str) -> str:
    """
    Search OpenROAD and OpenSTA documentation for relevant information.

    Use this when the user asks about:
    - EDA tool commands and syntax
    - Design flow steps (placement, routing, CTS, etc.)
    - Tool options and parameters
    - How to use specific features

    Args:
        query: Natural language question about EDA documentation
    """
    results = hybrid_search_filtered(
        query=query,
        source_type="documentation",
        top_k=TOP_K_RESULTS,
    )

    if not results:
        return "No relevant documentation found. Try rephrasing your query."

    formatted = []
    for i, doc in enumerate(results, 1):
        source = doc.metadata.get("source", "unknown")
        formatted.append(f"[{i}] Source: {source}\n{doc.page_content}")

    return "\n\n---\n\n".join(formatted)


@tool
def search_timing_reports(query: str) -> str:
    """
    Search parsed timing reports for specific paths, slack values, or violations.

    Use this when the user asks about:
    - Specific timing paths or endpoints
    - Slack values
    - Timing violations in their design
    - Critical paths

    Args:
        query: Question about timing data (paths, slack, violations)
    """
    results = hybrid_search_filtered(
        query=query,
        source_type="timing_report",
        top_k=TOP_K_RESULTS,
    )

    if not results:
        return "No matching timing report data found."

    formatted = []
    for i, doc in enumerate(results, 1):
        source = doc.metadata.get("source", "unknown")
        corner = doc.metadata.get("corner", "unknown")
        formatted.append(
            f"[{i}] Report: {source} | Corner: {corner}\n{doc.page_content}"
        )

    return "\n\n---\n\n".join(formatted)


@tool
def analyze_timing_violations(report_type: str = "setup") -> str:
    """
    Analyze timing violations from ingested reports.

    Summarizes the worst violations, counts, and affected paths.

    Args:
        report_type: Either "setup" or "hold"
    """
    query = f"worst {report_type} violations negative slack critical paths"
    results = hybrid_search_filtered(
        query=query,
        source_type="timing_report",
        top_k=10,
    )

    if not results:
        return f"No {report_type} timing report data available."

    # Extract violation info from results
    violation_summary = []
    for doc in results:
        lower = doc.page_content.lower()
        if "violated" in lower or "violation" in lower or "negative" in lower or "-0." in doc.page_content:
            violation_summary.append(doc.page_content)

    if not violation_summary:
        return f"No {report_type} violations found in the available reports. Timing may be clean."

    header = f"=== {report_type.upper()} VIOLATION ANALYSIS ===\n"
    header += f"Found data in {len(results)} report sections:\n\n"
    return header + "\n\n".join(violation_summary[:5])


@tool
def suggest_timing_fix(violation_type: str, endpoint: str = "") -> str:
    """
    Suggest fixes for timing violations based on best practices and documentation.

    Args:
        violation_type: "setup" or "hold"
        endpoint: Optional specific endpoint with the violation
    """
    if violation_type.lower() == "setup":
        query = "fix setup violation reduce delay resize buffer"
    elif violation_type.lower() == "hold":
        query = "fix hold violation add delay cell hold buffer"
    else:
        return f"Unknown violation type: {violation_type}. Use 'setup' or 'hold'."

    if endpoint:
        query += f" {endpoint}"

    results = hybrid_search(query=query, top_k=TOP_K_RESULTS)

    if not results:
        # Provide built-in knowledge as fallback
        if violation_type.lower() == "setup":
            return (
                "Setup violation fix strategies:\n"
                "1. Resize cells to faster variants (upsizing)\n"
                "2. Add buffers to break long nets\n"
                "3. Move cells closer (reduce wire delay)\n"
                "4. Use faster Vt cells (HVT → SVT → LVT)\n"
                "5. Restructure logic to reduce levels\n"
                "6. Check if constraint can be relaxed"
            )
        else:
            return (
                "Hold violation fix strategies:\n"
                "1. Insert delay buffers/cells\n"
                "2. Resize to slower variants (downsizing)\n"
                "3. Increase useful clock skew\n"
                "4. Add routing detour\n"
                "NOTE: Hold fixes must not degrade setup timing"
            )

    formatted = []
    for i, doc in enumerate(results, 1):
        formatted.append(f"[{i}] {doc.page_content}")

    return f"Fix strategies for {violation_type} violation:\n\n" + "\n\n".join(formatted)


@tool
def explain_eda_concept(concept: str) -> str:
    """
    Explain an EDA or timing concept with definitions and context.

    Use for questions like "what is setup time?" or "explain clock skew".

    Args:
        concept: The EDA concept to explain (e.g., "setup time", "clock skew")
    """
    query = f"definition explanation {concept}"
    results = hybrid_search(query=query, top_k=3)

    if not results:
        return f"No documentation found for '{concept}'. Try a more specific term."

    formatted = []
    for doc in results:
        formatted.append(doc.page_content)

    return f"=== {concept.upper()} ===\n\n" + "\n\n".join(formatted)


@tool
def lookup_command_syntax(tool_name: str, command: str) -> str:
    """
    Look up the exact syntax and options for an EDA tool command.

    Args:
        tool_name: "openroad" or "opensta"
        command: The command to look up (e.g., "report_checks", "place_design")
    """
    query = f"{tool_name} {command} syntax options usage"
    results = hybrid_search_filtered(
        query=query,
        source_type="documentation",
        top_k=3,
    )

    if not results:
        return f"No documentation found for '{command}' in {tool_name}."

    formatted = []
    for doc in results:
        formatted.append(doc.page_content)

    return f"=== {tool_name.upper()}: {command} ===\n\n" + "\n\n".join(formatted)


# ---------------------------------------------------------------------------
# Tool Registry (for LangGraph binding)
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    search_documentation,
    search_timing_reports,
    analyze_timing_violations,
    suggest_timing_fix,
    explain_eda_concept,
    lookup_command_syntax,
]

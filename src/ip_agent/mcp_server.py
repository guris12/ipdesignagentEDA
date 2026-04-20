"""
MCP Server — Expose EDA tools via Model Context Protocol.

MCP (Model Context Protocol) is Anthropic's standard for connecting AI models
to external tools and data. This server exposes our EDA search/analysis
capabilities so any MCP-compatible client (Claude Desktop, Cursor, etc.)
can use them.

Architecture:
    MCP Client (Claude Desktop) → MCP Protocol → This Server → pgvector/tools

Swift analogy: Like exposing your app's functionality via App Intents / Shortcuts.
Any client that speaks the protocol can invoke your capabilities.

Usage:
    # Run standalone:
    python -m ip_agent.mcp_server

    # Or import and configure:
    from ip_agent.mcp_server import mcp
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ip_agent.retriever import hybrid_search, hybrid_search_filtered
from ip_agent.config import TOP_K_RESULTS


# ---------------------------------------------------------------------------
# Create MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "IP Design Intelligence",
    instructions=(
        "EDA knowledge assistant for OpenROAD/OpenSTA. "
        "Search documentation, analyze timing reports, get fix suggestions."
    ),
    host="0.0.0.0",  # accept connections from any host (needed behind ALB proxy)
)


# ---------------------------------------------------------------------------
# MCP Tools (exposed to clients)
# ---------------------------------------------------------------------------

@mcp.tool()
def search_eda_docs(query: str, top_k: int = TOP_K_RESULTS) -> str:
    """
    Search OpenROAD and OpenSTA documentation.

    Args:
        query: Natural language query about EDA tools
        top_k: Number of results to return (default 5)
    """
    results = hybrid_search_filtered(
        query=query,
        source_type="documentation",
        top_k=top_k,
    )

    if not results:
        return "No relevant documentation found."

    formatted = []
    for i, doc in enumerate(results, 1):
        source = doc.metadata.get("source", "unknown")
        formatted.append(f"[{i}] {source}\n{doc.page_content}")

    return "\n\n---\n\n".join(formatted)


@mcp.tool()
def search_timing_data(query: str, top_k: int = TOP_K_RESULTS) -> str:
    """
    Search timing reports for paths, violations, and slack data.

    Args:
        query: Query about timing paths or violations
        top_k: Number of results to return
    """
    results = hybrid_search_filtered(
        query=query,
        source_type="timing_report",
        top_k=top_k,
    )

    if not results:
        return "No timing data found matching your query."

    formatted = []
    for i, doc in enumerate(results, 1):
        corner = doc.metadata.get("corner", "unknown")
        source = doc.metadata.get("source", "unknown")
        formatted.append(f"[{i}] {source} ({corner})\n{doc.page_content}")

    return "\n\n---\n\n".join(formatted)


@mcp.tool()
def get_fix_suggestion(violation_type: str, context: str = "") -> str:
    """
    Get timing fix suggestions for setup or hold violations.

    Args:
        violation_type: "setup" or "hold"
        context: Optional context about the specific violation
    """
    query = f"fix {violation_type} violation {context}".strip()
    results = hybrid_search(query=query, top_k=3)

    if not results:
        if violation_type.lower() == "setup":
            return (
                "Setup fix strategies:\n"
                "1. Upsize cells on critical path\n"
                "2. Insert buffers to reduce net delay\n"
                "3. Swap to faster Vt (HVT→SVT→LVT)\n"
                "4. Improve placement (reduce wire length)\n"
                "5. Restructure logic (reduce levels)"
            )
        else:
            return (
                "Hold fix strategies:\n"
                "1. Insert delay buffers\n"
                "2. Downsize cells on short paths\n"
                "3. Add routing detour\n"
                "4. Useful skew adjustment\n"
                "Note: Must not degrade setup timing"
            )

    formatted = [doc.page_content for doc in results]
    return f"Fix suggestions for {violation_type}:\n\n" + "\n\n".join(formatted)


@mcp.tool()
def explain_concept(term: str) -> str:
    """
    Explain an EDA/timing concept.

    Args:
        term: The concept to explain (e.g., "setup time", "clock skew", "OCV")
    """
    results = hybrid_search(query=f"definition {term} explanation", top_k=3)

    if not results:
        return f"No documentation found for '{term}'."

    formatted = [doc.page_content for doc in results]
    return "\n\n".join(formatted)


# ---------------------------------------------------------------------------
# MCP Resources (expose data sources)
# ---------------------------------------------------------------------------

@mcp.resource("eda://status")
def get_status() -> str:
    """Current status of the EDA knowledge base."""
    return (
        "IP Design Intelligence Agent\n"
        "Status: Running\n"
        "Knowledge base: OpenROAD + OpenSTA documentation\n"
        "Data: Timing reports indexed via pgvector\n"
        "Search: Hybrid (vector + BM25 + RRF)"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()

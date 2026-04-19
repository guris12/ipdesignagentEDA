"""
Pydantic data models for the IP Design Intelligence Agent.

These define the shape of data flowing through the system — timing paths,
reports, document chunks, and agent state.

Swift analogy: These are your Codable structs. Pydantic gives you
free validation + serialization, just like Codable gives you free
encode/decode with compile-time type safety.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Timing Domain Models
# ---------------------------------------------------------------------------

class ViolationType(str, Enum):
    """Type of timing violation."""
    SETUP = "setup"
    HOLD = "hold"


class TimingPath(BaseModel):
    """
    A single timing path from a .rpt file.

    Swift analogy: Like a struct TimingPath: Codable { ... }
    """
    startpoint: str = Field(description="Launch flip-flop or port")
    endpoint: str = Field(description="Capture flip-flop or port")
    path_group: str = Field(default="", description="Clock group name")
    delay: float = Field(description="Total path delay in ns")
    slack: float = Field(description="Timing slack — negative = violation")
    violation_type: ViolationType | None = Field(
        default=None,
        description="setup or hold — None if path meets timing",
    )
    corner: str = Field(default="typical", description="PVT corner name")
    levels: int = Field(default=0, description="Number of logic levels")

    @property
    def is_violated(self) -> bool:
        return self.slack < 0

    @property
    def severity(self) -> str:
        """Classify violation severity by slack magnitude."""
        if self.slack >= 0:
            return "met"
        elif self.slack > -0.1:
            return "minor"  # < 100ps
        elif self.slack > -0.5:
            return "moderate"
        else:
            return "critical"  # > 500ps


class TimingReport(BaseModel):
    """
    Parsed timing report — collection of paths from one .rpt file.
    """
    source_file: str = Field(description="Original .rpt filename")
    report_type: str = Field(default="setup", description="setup or hold report")
    corner: str = Field(default="typical", description="PVT corner")
    clock_period: float | None = Field(default=None, description="Target period in ns")
    paths: list[TimingPath] = Field(default_factory=list)
    worst_slack: float | None = Field(default=None, description="WNS across all paths")
    total_violations: int = Field(default=0)
    generated_at: datetime | None = None

    def compute_stats(self) -> dict[str, Any]:
        """Compute summary statistics for the report."""
        if not self.paths:
            return {"total_paths": 0}

        violated = [p for p in self.paths if p.is_violated]
        return {
            "total_paths": len(self.paths),
            "violations": len(violated),
            "wns": min(p.slack for p in self.paths),
            "tns": sum(p.slack for p in violated) if violated else 0.0,
            "worst_endpoint": min(self.paths, key=lambda p: p.slack).endpoint,
        }


# ---------------------------------------------------------------------------
# Document / Retrieval Models
# ---------------------------------------------------------------------------

class DocumentChunk(BaseModel):
    """
    A chunk of text stored in pgvector for retrieval.

    Swift analogy: Like a CoreData entity — you store it, you query it,
    it carries metadata alongside its content.
    """
    content: str = Field(description="Text content of the chunk")
    source: str = Field(description="Source filename or URL")
    source_type: str = Field(
        description="documentation | timing_report | log",
    )
    chunk_index: int = Field(default=0, description="Position within source")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceType(str, Enum):
    """Types of documents in the knowledge base."""
    DOCUMENTATION = "documentation"
    TIMING_REPORT = "timing_report"
    LOG = "log"


# ---------------------------------------------------------------------------
# Agent State (LangGraph)
# ---------------------------------------------------------------------------

class AgentState(BaseModel):
    """
    State that flows through the LangGraph agent graph.

    This is the 'message bus' — every node reads from and writes to this state.
    LangGraph manages the state transitions between nodes.
    """
    # Input
    query: str = Field(description="User's original question")
    chat_history: list[dict[str, str]] = Field(default_factory=list)

    # Routing
    route: str = Field(default="", description="Deterministic route if matched")
    model_tier: str = Field(default="gpt-4o-mini", description="Selected model")

    # Retrieval
    contexts: list[str] = Field(default_factory=list, description="Retrieved chunks")
    context_sources: list[str] = Field(default_factory=list)

    # Generation
    answer: str = Field(default="", description="Generated answer")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)

    # Guardrails
    guardrail_passed: bool = Field(default=True)
    guardrail_score: float = Field(default=1.0)
    guardrail_issues: list[str] = Field(default_factory=list)

    # Cost tracking
    tokens_used: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    cache_hit: bool = Field(default=False)


# ---------------------------------------------------------------------------
# API Response Models
# ---------------------------------------------------------------------------

class QueryResponse(BaseModel):
    """Response shape for the FastAPI /query endpoint."""
    answer: str
    sources: list[str] = Field(default_factory=list)
    model_used: str = ""
    guardrail_score: float = 1.0
    cached: bool = False
    cost_usd: float = 0.0


class HealthResponse(BaseModel):
    """Response for /health endpoint."""
    status: str = "healthy"
    version: str = "0.1.0"
    components: dict[str, str] = Field(default_factory=dict)

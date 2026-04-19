"""
Specialist Agents — Domain-specific sub-agents for multi-agent orchestration.

This demonstrates the pattern Synopsys needs: multiple AI agents coordinating
across the EDA tool stack, each specialized in one domain.

Architecture (mirrors real EDA flow):
    [Timing Agent]    — knows PrimeTime/OpenSTA, reads .rpt, finds violations
    [Physical Agent]  — knows ICC2/OpenROAD, reads cell reports, suggests resizing
    [DRC Agent]       — knows ICV/Calibre/TritonRoute, reads DRC reports

    [Orchestrator] coordinates all three via A2A pattern:
        1. Timing Agent finds violations
        2. DRC Agent checks current DRC status in same region
        3. Physical Agent suggests fixes that close timing WITHOUT new DRC

    This is the MMMC timing closure loop — automated.

Real-world mapping:
    Broadcom engineer: "Close timing on block_alu, don't break DRC"
    → Orchestrator decomposes → 3 agents coordinate → done

Swift analogy: Like 3 microservices in a Swift Server app, each handling
its own domain, communicating via structured messages (like Codable DTOs).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from ip_agent.config import MODEL_CHEAP, MODEL_STANDARD
from ip_agent.retriever import hybrid_search, hybrid_search_filtered

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "sample_reports"


# ---------------------------------------------------------------------------
# Base Specialist
# ---------------------------------------------------------------------------

class SpecialistAgent:
    """Base class for domain-specific agents."""

    def __init__(self, name: str, system_prompt: str, model: str = MODEL_CHEAP):
        self.name = name
        self._system_prompt = system_prompt
        self._model = model

    async def process(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process a query and return structured result."""
        raise NotImplementedError

    def _format_response(self, findings: str, recommendations: list[str],
                         severity: str = "info") -> dict[str, Any]:
        return {
            "agent": self.name,
            "findings": findings,
            "recommendations": recommendations,
            "severity": severity,
        }


# ---------------------------------------------------------------------------
# Timing Agent — PrimeTime / OpenSTA specialist
# ---------------------------------------------------------------------------

class TimingAgent(SpecialistAgent):
    """
    Specialist for timing analysis.

    Reads timing reports, identifies violations, cross-correlates across corners.
    In production at Synopsys: this would wrap PrimeTime queries.
    In our demo: searches pgvector + parses local .rpt files.
    """

    def __init__(self):
        super().__init__(
            name="timing_agent",
            system_prompt=(
                "You are a timing analysis specialist. You analyze OpenSTA/PrimeTime "
                "timing reports, identify setup/hold violations, and prioritize paths "
                "by severity. Be precise about slack values and path endpoints."
            ),
        )

    async def process(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Analyze timing violations from reports."""
        # Search indexed timing reports
        results = hybrid_search_filtered(
            query=f"timing violation slack {query}",
            source_type="timing_report",
            top_k=10,
        )

        # Also read raw report if available
        raw_report = ""
        setup_rpt = DATA_DIR / "setup_report.rpt"
        if setup_rpt.exists():
            raw_report = setup_rpt.read_text(encoding="utf-8")

        # Parse violations from raw report
        violations = []
        if raw_report:
            blocks = raw_report.split("Startpoint:")
            for block in blocks[1:]:
                slack_match = re.search(r"slack\s*\(VIOLATED\)\s*([-\d.]+)", block)
                if slack_match:
                    slack = float(slack_match.group(1))
                    ep_match = re.search(r"Endpoint:\s*(.+)", block)
                    endpoint = ep_match.group(1).strip() if ep_match else "unknown"
                    violations.append({"endpoint": endpoint, "slack": slack})

        # Sort by worst slack
        violations.sort(key=lambda v: v["slack"])

        if not violations and not results:
            return self._format_response(
                "No timing violations found in available reports.",
                ["Design may be timing-clean or reports not ingested"],
                severity="info",
            )

        # Build findings
        findings_parts = []
        if violations:
            findings_parts.append(f"Found {len(violations)} setup violations:")
            for i, v in enumerate(violations, 1):
                findings_parts.append(
                    f"  {i}. {v['endpoint']} — slack: {v['slack']:.3f}ns "
                    f"({'CRITICAL' if v['slack'] < -0.1 else 'MODERATE'})"
                )
            worst = violations[0]
            findings_parts.append(f"\nWNS: {worst['slack']:.3f}ns at {worst['endpoint']}")
            tns = sum(v["slack"] for v in violations)
            findings_parts.append(f"TNS: {tns:.3f}ns across {len(violations)} paths")

        recommendations = []
        if violations:
            worst_slack = violations[0]["slack"]
            if worst_slack < -0.1:
                recommendations.append("CRITICAL: Multi-step fix needed — upsizing + buffering")
                recommendations.append(f"Priority path: {violations[0]['endpoint']}")
            else:
                recommendations.append("Minor violations — cell upsizing likely sufficient")
            recommendations.append("Run Physical Agent to check cell sizing options")
            recommendations.append("Run DRC Agent to verify fix region is not congested")

        return self._format_response(
            "\n".join(findings_parts),
            recommendations,
            severity="critical" if any(v["slack"] < -0.1 for v in violations) else "warning",
        )


# ---------------------------------------------------------------------------
# DRC Agent — ICV / Calibre / TritonRoute specialist
# ---------------------------------------------------------------------------

class DRCAgent(SpecialistAgent):
    """
    Specialist for physical DRC verification.

    Reads DRC reports, identifies spacing/width/short violations,
    maps them to affected nets and regions.
    In production: wraps ICV/Calibre queries.
    """

    def __init__(self):
        super().__init__(
            name="drc_agent",
            system_prompt=(
                "You are a physical DRC verification specialist. You analyze "
                "DRC reports from TritonRoute/ICV/Calibre, identify metal spacing, "
                "width, and short violations, and map them to affected design regions."
            ),
        )

    async def process(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Analyze DRC violations from reports."""
        drc_rpt = DATA_DIR / "drc_report.rpt"
        if not drc_rpt.exists():
            return self._format_response(
                "No DRC report found.", ["Run DRC check first"], severity="info"
            )

        content = drc_rpt.read_text(encoding="utf-8")

        # Parse violations
        violations = []
        blocks = content.split("------" * 5)  # Split by separator
        for block in blocks:
            type_match = re.search(r"Violation Type:\s*(.+)", block)
            sev_match = re.search(r"Severity:\s*(\w+)", block)
            net_matches = re.findall(r"Net[12]?:\s*(.+)", block)
            loc_match = re.search(r"Location:\s*(.+)", block)

            if type_match:
                violations.append({
                    "type": type_match.group(1).strip(),
                    "severity": sev_match.group(1).strip() if sev_match else "UNKNOWN",
                    "nets": [n.strip() for n in net_matches],
                    "location": loc_match.group(1).strip() if loc_match else "unknown",
                })

        if not violations:
            return self._format_response(
                "DRC clean — no violations found.",
                ["Proceed with timing fixes"],
                severity="info",
            )

        # Build findings
        critical = [v for v in violations if v["severity"] == "CRITICAL"]
        errors = [v for v in violations if v["severity"] == "ERROR"]
        warnings = [v for v in violations if v["severity"] == "WARNING"]

        findings_parts = [
            f"DRC Status: {len(violations)} violations",
            f"  CRITICAL: {len(critical)}",
            f"  ERROR: {len(errors)}",
            f"  WARNING: {len(warnings)}",
            "",
        ]

        all_affected_nets = set()
        for v in violations:
            findings_parts.append(f"  [{v['severity']}] {v['type']}")
            if v["nets"]:
                findings_parts.append(f"    Nets: {', '.join(v['nets'])}")
                all_affected_nets.update(v["nets"])
            findings_parts.append(f"    Location: {v['location']}")

        recommendations = []
        if critical:
            recommendations.append("CRITICAL: Metal short must be fixed before tapeout")
        if errors:
            recommendations.append(f"{len(errors)} spacing/width errors — check routing congestion")
        recommendations.append(f"Affected nets: {', '.join(sorted(all_affected_nets)[:5])}")
        recommendations.append("Timing fixes in this region should use cell resizing, NOT buffer insertion (to avoid worsening congestion)")

        # Pass affected nets to context for other agents
        return {
            **self._format_response(
                "\n".join(findings_parts),
                recommendations,
                severity="critical" if critical else "warning",
            ),
            "affected_nets": list(all_affected_nets),
            "congested_region": True if len(violations) > 3 else False,
        }


# ---------------------------------------------------------------------------
# Physical Agent — ICC2 / OpenROAD specialist
# ---------------------------------------------------------------------------

class PhysicalAgent(SpecialistAgent):
    """
    Specialist for physical design optimization.

    Reads cell usage reports, suggests resizing/buffering strategies,
    respects DRC constraints from DRC Agent.
    In production: wraps ICC2 ECO commands.
    """

    def __init__(self):
        super().__init__(
            name="physical_agent",
            system_prompt=(
                "You are a physical design optimization specialist. You analyze "
                "cell usage, suggest resizing and buffering strategies for timing "
                "closure, and generate ECO fix commands. You must respect DRC "
                "constraints — prefer resizing over buffer insertion in congested areas."
            ),
            model=MODEL_STANDARD,  # Needs better reasoning for fix generation
        )

    async def process(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Suggest physical fixes based on timing + DRC context."""
        context = context or {}

        # Read cell usage report
        cell_rpt = DATA_DIR / "cell_usage.rpt"
        cell_data = ""
        if cell_rpt.exists():
            cell_data = cell_rpt.read_text(encoding="utf-8")

        # Extract cells on critical paths
        critical_cells = []
        if cell_data:
            for line in cell_data.split("\n"):
                if "candidate for" in line.lower():
                    critical_cells.append(line.strip())

        # Check DRC context from DRC Agent
        congested = context.get("congested_region", False)
        drc_nets = set(context.get("affected_nets", []))

        # Get timing violation context
        timing_findings = context.get("timing_findings", "")

        # Build fix strategy
        fixes = []
        tcl_commands = []

        for cell_line in critical_cells:
            # Parse: "u_alu/add_stage1   FA_X1    (setup slack: -0.05ns) → candidate for upsizing"
            parts = cell_line.split()
            if len(parts) < 2:
                continue

            cell_name = parts[0]
            cell_type = parts[1]

            # Check if this cell's net has DRC violations
            has_drc = any(cell_name.split("/")[0] in net for net in drc_nets)

            if congested and has_drc:
                # In congested region with DRC — prefer resizing over buffering
                if "BUF_X1" in cell_type:
                    new_type = cell_type.replace("X1", "X2")  # Modest upsize only
                    fixes.append(f"  {cell_name}: {cell_type} → {new_type} (modest — DRC congested)")
                    tcl_commands.append(f"size_cell {cell_name} {new_type}")
                else:
                    new_type = cell_type.replace("X1", "X2").replace("X2", "X4")
                    fixes.append(f"  {cell_name}: {cell_type} → {new_type} (upsize — avoid buffer)")
                    tcl_commands.append(f"size_cell {cell_name} {new_type}")
            else:
                # No DRC concern — aggressive fix
                if "BUF_X1" in cell_type:
                    fixes.append(f"  {cell_name}: {cell_type} → BUF_X4 (aggressive upsize)")
                    tcl_commands.append(f"size_cell {cell_name} BUF_X4")
                elif "FA_X1" in cell_type:
                    fixes.append(f"  {cell_name}: {cell_type} → FA_X2 (upsize adder)")
                    tcl_commands.append(f"size_cell {cell_name} FA_X2")
                elif "MUX" in cell_type:
                    new_type = cell_type.replace("X1", "X2")
                    fixes.append(f"  {cell_name}: {cell_type} → {new_type} (upsize mux)")
                    tcl_commands.append(f"size_cell {cell_name} {new_type}")

        findings_parts = [
            f"Cell Analysis: {len(critical_cells)} cells on critical paths",
            f"DRC-aware: {'YES — congested region, using conservative fixes' if congested else 'No DRC conflicts'}",
            "",
            "Proposed ECO Fixes:",
        ]
        findings_parts.extend(fixes if fixes else ["  No cell fixes identified"])

        findings_parts.extend([
            "",
            "Generated Tcl ECO Script (fix_timing.tcl):",
            "  " + "\n  ".join(tcl_commands) if tcl_commands else "  # No commands generated",
        ])

        recommendations = []
        if tcl_commands:
            recommendations.append(f"Apply {len(tcl_commands)} ECO commands via: source fix_timing.tcl")
            recommendations.append("Re-run PrimeTime after applying fixes")
            recommendations.append("Re-run DRC to verify no new violations")
        if congested:
            recommendations.append("WARNING: Region is DRC-congested — used conservative sizing")
            recommendations.append("If timing still fails, consider logic restructuring or retiming")

        return {
            **self._format_response(
                "\n".join(findings_parts),
                recommendations,
                severity="warning" if fixes else "info",
            ),
            "tcl_commands": tcl_commands,
            "fix_count": len(tcl_commands),
        }


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------

SPECIALISTS = {
    "timing_agent": TimingAgent,
    "drc_agent": DRCAgent,
    "physical_agent": PhysicalAgent,
}


def get_specialist(name: str) -> SpecialistAgent:
    """Get a specialist agent by name."""
    cls = SPECIALISTS.get(name)
    if not cls:
        raise ValueError(f"Unknown specialist: {name}. Available: {list(SPECIALISTS.keys())}")
    return cls()

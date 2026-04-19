"""
EDA Bridge — Subprocess wrapper for OpenSTA/OpenROAD commands.

This module provides a safe interface to invoke EDA tools as subprocesses,
parse their output, and return structured results to the agent.

In production, this would connect to a running OpenSTA/OpenROAD instance.
For the demo, it parses pre-generated report files.

Architecture:
    Agent Tool Call → EDA Bridge → subprocess/file parsing → Structured Result

Swift analogy: Like a ProcessInfo/NSTask wrapper — you launch a subprocess,
capture stdout/stderr, and parse the result into typed models.

Safety: All commands are whitelisted. No arbitrary shell execution.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from ip_agent.models import TimingPath, TimingReport, ViolationType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Whitelisted Commands (security: only these can be invoked)
# ---------------------------------------------------------------------------

ALLOWED_OPENSTA_COMMANDS = {
    "report_checks",
    "report_timing",
    "report_clock_properties",
    "report_tns",
    "report_wns",
    "read_sdc",
    "read_liberty",
    "read_verilog",
}

ALLOWED_OPENROAD_COMMANDS = {
    "report_design_area",
    "report_cell_usage",
    "report_routing_layers",
    "report_power",
}


# ---------------------------------------------------------------------------
# OpenSTA Bridge
# ---------------------------------------------------------------------------

class OpenSTABridge:
    """
    Interface to OpenSTA for timing analysis.

    In production: launches `sta` subprocess with Tcl commands.
    In demo mode: reads from pre-generated .rpt files.
    """

    def __init__(self, sta_binary: str = "sta", demo_mode: bool = True):
        self._binary = sta_binary
        self._demo_mode = demo_mode
        self._reports_dir = Path(__file__).parent.parent.parent / "data" / "sample_reports"

    def run_command(self, command: str, args: dict[str, Any] | None = None) -> str:
        """
        Execute an OpenSTA command.

        Args:
            command: The STA command (must be in whitelist)
            args: Command arguments

        Returns:
            Command output as string
        """
        if command not in ALLOWED_OPENSTA_COMMANDS:
            raise ValueError(
                f"Command '{command}' not in whitelist. "
                f"Allowed: {sorted(ALLOWED_OPENSTA_COMMANDS)}"
            )

        if self._demo_mode:
            return self._demo_command(command, args)

        # Production mode: invoke subprocess
        return self._invoke_subprocess(command, args)

    def _demo_command(self, command: str, args: dict[str, Any] | None) -> str:
        """Return pre-generated output for demo mode."""
        if command == "report_checks":
            return self._load_report("setup_report.rpt")
        elif command == "report_timing":
            return self._load_report("timing_summary.rpt")
        elif command == "report_wns":
            return "wns -0.234\n"
        elif command == "report_tns":
            return "tns -1.456\n"
        else:
            return f"[Demo mode] Command '{command}' executed successfully.\n"

    def _load_report(self, filename: str) -> str:
        """Load a report file from the sample_reports directory."""
        report_path = self._reports_dir / filename
        if report_path.exists():
            return report_path.read_text(encoding="utf-8")
        return f"[Report not found: {filename}]"

    def _invoke_subprocess(self, command: str, args: dict[str, Any] | None) -> str:
        """Invoke OpenSTA as subprocess with Tcl script."""
        tcl_commands = self._build_tcl(command, args)

        try:
            result = subprocess.run(
                [self._binary, "-exit", "-no_splash"],
                input=tcl_commands,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error(f"OpenSTA error: {result.stderr}")
                return f"Error: {result.stderr}"
            return result.stdout
        except FileNotFoundError:
            return "Error: OpenSTA binary not found. Is it installed and in PATH?"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out (30s limit)"

    def _build_tcl(self, command: str, args: dict[str, Any] | None) -> str:
        """Build Tcl script string for OpenSTA."""
        lines = []
        if args:
            for key, value in args.items():
                lines.append(f"{command} -{key} {value}")
        else:
            lines.append(command)
        lines.append("exit")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# OpenROAD Bridge
# ---------------------------------------------------------------------------

class OpenROADBridge:
    """Interface to OpenROAD for physical design queries."""

    def __init__(self, binary: str = "openroad", demo_mode: bool = True):
        self._binary = binary
        self._demo_mode = demo_mode

    def run_command(self, command: str, args: dict[str, Any] | None = None) -> str:
        """Execute an OpenROAD command (whitelisted only)."""
        if command not in ALLOWED_OPENROAD_COMMANDS:
            raise ValueError(
                f"Command '{command}' not in whitelist. "
                f"Allowed: {sorted(ALLOWED_OPENROAD_COMMANDS)}"
            )

        if self._demo_mode:
            return f"[Demo mode] OpenROAD '{command}' executed.\n"

        # Production mode would invoke openroad subprocess
        return f"[Not implemented in production yet]"


# ---------------------------------------------------------------------------
# Module-level instances
# ---------------------------------------------------------------------------

_sta_bridge: OpenSTABridge | None = None
_openroad_bridge: OpenROADBridge | None = None


def get_sta_bridge(demo_mode: bool = True) -> OpenSTABridge:
    """Get or create the OpenSTA bridge singleton."""
    global _sta_bridge
    if _sta_bridge is None:
        _sta_bridge = OpenSTABridge(demo_mode=demo_mode)
    return _sta_bridge


def get_openroad_bridge(demo_mode: bool = True) -> OpenROADBridge:
    """Get or create the OpenROAD bridge singleton."""
    global _openroad_bridge
    if _openroad_bridge is None:
        _openroad_bridge = OpenROADBridge(demo_mode=demo_mode)
    return _openroad_bridge

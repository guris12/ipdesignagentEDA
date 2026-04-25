"""
Flow Manager — EFS-based job queue for OpenROAD container control.

The agent container writes JSON job files to /shared/jobs/.
The OpenROAD container watches for new jobs, executes them,
and writes results to /shared/results/{job_id}/.

This module is the agent-side client for submitting jobs and
reading results/logs.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from ip_agent.config import SHARED_DATA_PATH

VALID_DESIGNS = {"gcd", "aes", "ibex", "jpeg"}
VALID_PDKS = {"sky130hd", "sky130hs", "asap7", "gf180"}
VALID_STAGES = {"synth", "floorplan", "place", "cts", "route", "finish"}

ALLOWED_TCL_COMMANDS = {
    "report_checks",
    "report_timing",
    "report_clock_properties",
    "report_tns",
    "report_wns",
    "report_design_area",
    "report_cell_usage",
    "report_routing_layers",
    "report_power",
    "read_db",
    "read_sdc",
    "read_liberty",
    "read_verilog",
    "set_propagated_clock",
    "report_check_types",
    "report_parasitic_annotation",
    "size_cell",
    "insert_buffer",
    "swap_cell",
    "remove_buffer",
    "set_dont_touch",
}

BLOCKED_TCL_PATTERNS = [
    "exec ",
    "file delete",
    "open |",
    "catch {exec",
    "system ",
    "eval [",
    "uplevel",
    "interp ",
    "socket ",
    "fconfigure ",
    "package require Tk",
]

JobType = Literal["stage", "tcl_command", "full_flow"]
JobStatus = Literal["pending", "running", "complete", "failed", "unknown"]


@dataclass
class JobResult:
    job_id: str
    success: bool
    exit_code: int
    log_path: Path
    reports_dir: Path
    metrics: dict | None
    elapsed_seconds: float


class FlowManager:
    """EFS-based job queue client for the agent container."""

    def __init__(self, design: str = "gcd", pdk: str = "sky130hd"):
        self.design = design
        self.pdk = pdk
        self._base = Path(SHARED_DATA_PATH)
        self._jobs_dir = self._base / "jobs"
        self._results_dir = self._base / "results"
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._results_dir.mkdir(parents=True, exist_ok=True)

    def submit_stage(self, stage: str) -> str:
        if stage not in VALID_STAGES:
            raise ValueError(f"Invalid stage '{stage}'. Must be one of: {VALID_STAGES}")
        self._validate_design_pdk()
        return self._write_job({
            "type": "stage",
            "stage": stage,
            "design": self.design,
            "pdk": self.pdk,
        })

    def submit_tcl_command(self, command: str) -> str:
        command = command.strip()
        if not command:
            raise ValueError("Empty command")
        self._validate_tcl_command(command)
        return self._write_job({
            "type": "tcl_command",
            "command": command,
            "design": self.design,
            "pdk": self.pdk,
        })

    def submit_full_flow(self) -> str:
        self._validate_design_pdk()
        return self._write_job({
            "type": "full_flow",
            "design": self.design,
            "pdk": self.pdk,
        })

    def submit_gui_session(self, ttl_seconds: int = 1200) -> str:
        """Launch ``openroad -gui`` on the shared runner and stream it via noVNC.

        The job server kills any prior GUI session before starting a new one,
        so only one student can be live at a time. The caller is expected to
        gate access via the queue manager (Phase 4).
        """
        self._validate_design_pdk()
        if ttl_seconds <= 0 or ttl_seconds > 7200:
            raise ValueError("ttl_seconds must be between 1 and 7200")
        return self._write_job({
            "type": "gui_session",
            "design": self.design,
            "pdk": self.pdk,
            "ttl_seconds": int(ttl_seconds),
        })

    def get_status(self, job_id: str) -> JobStatus:
        result_dir = self._results_dir / job_id
        if (result_dir / ".complete").exists():
            return "complete"
        if (result_dir / ".failed").exists():
            return "failed"
        if (result_dir / ".running").exists():
            return "running"
        job_file = self._jobs_dir / f"{job_id}.json"
        if job_file.exists():
            return "pending"
        done_file = self._jobs_dir / f"{job_id}.json.done"
        if done_file.exists():
            if result_dir.exists():
                return "complete"
            return "unknown"
        return "unknown"

    def get_log_tail(self, job_id: str, offset: int = 0) -> tuple[str, int]:
        log_path = self._results_dir / job_id / "output.log"
        if not log_path.exists():
            return "", offset
        try:
            size = log_path.stat().st_size
            if size <= offset:
                return "", offset
            with open(log_path, "r", errors="replace") as f:
                f.seek(offset)
                new_content = f.read()
                new_offset = f.tell()
            return new_content, new_offset
        except OSError:
            return "", offset

    def get_result(self, job_id: str) -> JobResult | None:
        result_dir = self._results_dir / job_id
        if not (result_dir / ".complete").exists() and not (result_dir / ".failed").exists():
            return None

        success = (result_dir / ".complete").exists()
        exit_code = 0
        if not success:
            try:
                fail_content = (result_dir / ".failed").read_text().strip()
                if "exit_code=" in fail_content:
                    exit_code = int(fail_content.split("exit_code=")[1])
            except (OSError, ValueError):
                exit_code = 1

        metrics = self.get_metrics(job_id)
        elapsed = float(metrics.get("elapsed_seconds", 0)) if metrics else 0.0

        return JobResult(
            job_id=job_id,
            success=success,
            exit_code=exit_code,
            log_path=result_dir / "output.log",
            reports_dir=result_dir / "reports",
            metrics=metrics,
            elapsed_seconds=elapsed,
        )

    def get_metrics(self, job_id: str) -> dict | None:
        metrics_path = self._results_dir / job_id / "metrics.json"
        if not metrics_path.exists():
            return None
        try:
            return json.loads(metrics_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def get_reports(self, job_id: str) -> dict[str, str]:
        reports_dir = self._results_dir / job_id / "reports"
        if not reports_dir.exists():
            return {}
        reports = {}
        for f in sorted(reports_dir.iterdir()):
            if f.is_file() and f.suffix in (".rpt", ".log"):
                try:
                    reports[f.name] = f.read_text(errors="replace")
                except OSError:
                    continue
        return reports

    def list_jobs(self, limit: int = 20) -> list[dict]:
        jobs = []
        for f in sorted(self._jobs_dir.glob("*.json*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if len(jobs) >= limit:
                break
            try:
                stem = f.stem
                if stem.endswith(".json"):
                    stem = stem[:-5]
                data = json.loads(f.read_text())
                data["status"] = self.get_status(data.get("job_id", stem))
                jobs.append(data)
            except (json.JSONDecodeError, OSError):
                continue
        return jobs

    def wait_for_completion(self, job_id: str, timeout: float = 600, poll_interval: float = 2.0) -> JobResult | None:
        import time
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            status = self.get_status(job_id)
            if status in ("complete", "failed"):
                return self.get_result(job_id)
            time.sleep(poll_interval)
        return None

    def _write_job(self, payload: dict) -> str:
        job_id = uuid.uuid4().hex[:12]
        payload["job_id"] = job_id
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        job_path = self._jobs_dir / f"{job_id}.json"
        tmp_path = self._jobs_dir / f"{job_id}.tmp"
        tmp_path.write_text(json.dumps(payload, indent=2))
        tmp_path.rename(job_path)
        return job_id

    def _validate_design_pdk(self):
        if self.design not in VALID_DESIGNS:
            raise ValueError(f"Invalid design '{self.design}'. Must be one of: {VALID_DESIGNS}")
        if self.pdk not in VALID_PDKS:
            raise ValueError(f"Invalid PDK '{self.pdk}'. Must be one of: {VALID_PDKS}")

    def _validate_tcl_command(self, command: str):
        for pattern in BLOCKED_TCL_PATTERNS:
            if pattern in command:
                raise ValueError(f"Blocked Tcl pattern: '{pattern}'")
        first_word = command.split()[0] if command.split() else ""
        if first_word not in ALLOWED_TCL_COMMANDS:
            if not any(command.startswith(cmd) for cmd in ALLOWED_TCL_COMMANDS):
                raise ValueError(
                    f"Command '{first_word}' not in whitelist. "
                    f"Allowed: {sorted(ALLOWED_TCL_COMMANDS)}"
                )


# ---------------------------------------------------------------------------
# ECS runner control (AWS-only — gracefully degrades locally)
# ---------------------------------------------------------------------------

ECS_CLUSTER = "ip-design-agent-cluster"
ECS_OPENROAD_SERVICE = "ip-design-agent-openroad"
ECS_REGION = "eu-west-1"


def check_runner_status() -> str:
    """Return 'running', 'starting', 'stopped', or 'unknown'."""
    try:
        import boto3
        ecs = boto3.client("ecs", region_name=ECS_REGION)
        resp = ecs.describe_services(cluster=ECS_CLUSTER, services=[ECS_OPENROAD_SERVICE])
        services = resp.get("services", [])
        if not services:
            return "unknown"
        svc = services[0]
        if svc.get("desiredCount", 0) == 0:
            return "stopped"
        if svc.get("runningCount", 0) > 0:
            return "running"
        return "starting"
    except Exception:
        return "unknown"


def start_runner() -> bool:
    """Scale OpenROAD ECS service to desiredCount=1. Returns True on success."""
    try:
        import boto3
        ecs = boto3.client("ecs", region_name=ECS_REGION)
        ecs.update_service(cluster=ECS_CLUSTER, service=ECS_OPENROAD_SERVICE, desiredCount=1)
        return True
    except Exception:
        return False


def stop_runner() -> bool:
    """Scale OpenROAD ECS service to desiredCount=0. Returns True on success."""
    try:
        import boto3
        ecs = boto3.client("ecs", region_name=ECS_REGION)
        ecs.update_service(cluster=ECS_CLUSTER, service=ECS_OPENROAD_SERVICE, desiredCount=0)
        return True
    except Exception:
        return False

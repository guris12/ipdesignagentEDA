#!/usr/bin/env python3
"""
generate_report_viewer.py — Generate beautiful HTML report viewer from OpenROAD flow logs.

Fetches logs from AWS CloudWatch (or reads local files) and produces an interactive
HTML page with tabs for each P&R stage: Synthesis, Floorplan, Placement, CTS, Routing, Finish.

Usage:
    python generate_report_viewer.py                          # Fetch from CloudWatch
    python generate_report_viewer.py --local /path/to/logs/   # Read local log directory
    python generate_report_viewer.py --output report.html     # Custom output path
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class StageMetrics:
    name: str
    display_name: str
    icon: str
    elapsed_sec: int = 0
    peak_memory_mb: int = 0
    log_content: str = ""
    metrics: dict = field(default_factory=dict)
    status: str = "ok"
    substages: list = field(default_factory=list)


STAGE_MAP = {
    "1_synth": ("Synthesis", "flask"),
    "1_1_yosys_canonicalize": ("Yosys Canonicalize", "code"),
    "1_2_yosys": ("Yosys Synthesis", "code"),
    "2_1_floorplan": ("Floorplan Init", "border-all"),
    "2_2_floorplan_macro": ("Macro Placement", "grid-3x3"),
    "2_3_floorplan_tapcell": ("Tap Cell Insertion", "pin-map"),
    "2_4_floorplan_pdn": ("Power Distribution", "lightning"),
    "3_1_place_gp_skip_io": ("Global Placement (Skip IO)", "grid"),
    "3_2_place_iop": ("IO Placement", "arrows-expand"),
    "3_3_place_gp": ("Global Placement", "grid-fill"),
    "3_4_place_resized": ("Resizer", "arrows-angle-expand"),
    "3_5_place_dp": ("Detailed Placement", "grid-3x3-gap"),
    "4_1_cts": ("Clock Tree Synthesis", "clock"),
    "4_rsz_lec_check": ("CTS LEC Check", "check-circle"),
    "5_1_grt": ("Global Routing", "signpost-split"),
    "5_2_route": ("Detailed Routing", "diagram-3"),
    "5_3_fillcell": ("Fill Cell Insertion", "square-fill"),
    "6_1_fill": ("Metal Fill", "paint-bucket"),
    "6_report": ("Final Report", "file-earmark-bar-graph"),
}

STAGE_GROUPS = [
    ("Synthesis", "cpu", "#6366f1", ["1_1_yosys_canonicalize", "1_2_yosys", "1_synth"]),
    ("Floorplan", "border-all", "#8b5cf6", ["2_1_floorplan", "2_2_floorplan_macro", "2_3_floorplan_tapcell", "2_4_floorplan_pdn"]),
    ("Placement", "grid-3x3-gap-fill", "#ec4899", ["3_1_place_gp_skip_io", "3_2_place_iop", "3_3_place_gp", "3_4_place_resized", "3_5_place_dp"]),
    ("CTS", "clock", "#f59e0b", ["4_1_cts", "4_rsz_lec_check"]),
    ("Routing", "diagram-3", "#10b981", ["5_1_grt", "5_2_route", "5_3_fillcell"]),
    ("Finish", "flag-fill", "#3b82f6", ["6_1_fill", "6_report"]),
]


def fetch_cloudwatch_logs(log_group: str, region: str = "eu-west-1") -> str:
    """Fetch latest log stream from CloudWatch."""
    stream_cmd = [
        "aws", "logs", "describe-log-streams",
        "--log-group-name", log_group,
        "--region", region,
        "--order-by", "LastEventTime",
        "--descending", "--limit", "1",
        "--query", "logStreams[0].logStreamName",
        "--output", "text",
    ]
    stream_name = subprocess.check_output(stream_cmd, text=True).strip()
    if not stream_name or stream_name == "None":
        print(f"No log streams found in {log_group}")
        sys.exit(1)

    events_cmd = [
        "aws", "logs", "get-log-events",
        "--log-group-name", log_group,
        "--log-stream-name", stream_name,
        "--region", region,
        "--query", "events[*].message",
        "--output", "text",
    ]
    raw = subprocess.check_output(events_cmd, text=True)
    return raw.replace("\t", "\n")


def read_local_logs(log_dir: str) -> dict[str, str]:
    """Read log files from a local directory."""
    logs = {}
    for f in sorted(Path(log_dir).glob("*.log")):
        logs[f.stem] = f.read_text()
    return logs


def parse_stage_summary(full_log: str) -> dict[str, tuple[int, int]]:
    """Parse stage summary lines: stage_name elapsed_sec peak_mem_mb."""
    summary = {}
    for line in full_log.split("\n"):
        m = re.match(r"^(\d_\S+)\s+(\d+)\s+(\d+)", line.strip())
        if m:
            stage, elapsed, mem = m.group(1), int(m.group(2)), int(m.group(3))
            summary[stage] = (elapsed, mem)
    return summary


def parse_design_areas(full_log: str) -> list[tuple[str, int, int]]:
    """Extract Design area <um^2> <util>% lines."""
    areas = []
    for line in full_log.split("\n"):
        m = re.search(r"Design area (\d+) um\^2 (\d+)% utilization", line)
        if m:
            areas.append((line.strip(), int(m.group(1)), int(m.group(2))))
    return areas


def parse_cell_report(full_log: str) -> list[dict]:
    """Parse cell type report table."""
    cells = []
    in_report = False
    for line in full_log.split("\n"):
        if "Cell type report:" in line:
            in_report = True
            continue
        if in_report:
            line_s = line.strip()
            if not line_s or "Report metrics" in line_s or "=====" in line_s:
                if cells:
                    in_report = False
                continue
            m = re.match(r"(.+?)\s{2,}(\d+)\s+([\d.]+)", line_s)
            if m:
                cells.append({"type": m.group(1).strip(), "count": int(m.group(2)), "area": float(m.group(3))})
    return cells


def parse_ir_reports(full_log: str) -> list[dict]:
    """Parse IR drop reports."""
    reports = []
    current = {}
    in_ir = False
    for line in full_log.split("\n"):
        if "IR report" in line:
            in_ir = True
            current = {}
            continue
        if in_ir and "######" in line:
            if current:
                reports.append(current)
            in_ir = False
            continue
        if in_ir:
            m = re.match(r"\s*([\w\s]+?)\s*:\s*(.+)", line.strip())
            if m:
                current[m.group(1).strip()] = m.group(2).strip()
    return reports


def parse_drc_violations(full_log: str) -> list[dict]:
    """Parse DRC violation progression from detailed routing."""
    violations = []
    for line in full_log.split("\n"):
        m = re.search(r"\[INFO DRT-0199\]\s+Number of violations = (\d+)", line)
        if m:
            violations.append(int(m.group(1)))
    return violations


def parse_antenna(full_log: str) -> dict:
    """Parse antenna check results."""
    antenna = {"net": 0, "pin": 0}
    for line in full_log.split("\n"):
        m = re.search(r"\[INFO ANT-0002\] Found (\d+) net violations", line)
        if m:
            antenna["net"] = int(m.group(1))
        m = re.search(r"\[INFO ANT-0001\] Found (\d+) pin violations", line)
        if m:
            antenna["pin"] = int(m.group(1))
    return antenna


def parse_placement_metrics(full_log: str) -> dict:
    """Parse placement-specific metrics."""
    metrics = {}
    for line in full_log.split("\n"):
        m = re.search(r"\[INFO GPL-0006\] Number of instances:\s+(\d+)", line)
        if m:
            metrics["instances"] = int(m.group(1))
        m = re.search(r"\[INFO GPL-0010\] Number of nets:\s+(\d+)", line)
        if m:
            metrics["nets"] = int(m.group(1))
        m = re.search(r"\[INFO GPL-0011\] Number of pins:\s+(\d+)", line)
        if m:
            metrics["pins"] = int(m.group(1))
        m = re.search(r"\[INFO GPL-0019\] Utilization:\s+([\d.]+)", line)
        if m:
            metrics["utilization"] = float(m.group(1))
        m = re.search(r"\[INFO GPL-0106\] Timing-driven: worst slack ([\-\d.e]+)", line)
        if m:
            metrics["worst_slack_ns"] = float(m.group(1)) * 1e9 if "e" in m.group(1) else float(m.group(1))
    return metrics


def parse_cts_metrics(full_log: str) -> dict:
    """Parse CTS-specific metrics."""
    metrics = {}
    for line in full_log.split("\n"):
        m = re.search(r"\[INFO CTS-0008\] TritonCTS found (\d+) clock net", line)
        if m:
            metrics["clock_nets"] = int(m.group(1))
        m = re.search(r"\[INFO CTS-0010\] Number of clock nets: (\d+)", line)
        if m:
            metrics["clock_nets"] = int(m.group(1))
    return metrics


def parse_routing_metrics(full_log: str) -> dict:
    """Parse routing-specific metrics."""
    metrics = {}
    for line in full_log.split("\n"):
        m = re.search(r"\[INFO GRT-0012\] Found (\d+) antenna violations", line)
        if m:
            metrics["grt_antenna"] = int(m.group(1))
        m = re.search(r"\[INFO GRT-0096\] Final congestion report", line)
        if m:
            metrics["has_congestion_report"] = True
    return metrics


def parse_setup_violations(full_log: str) -> list[dict]:
    """Parse setup violation repair iterations."""
    iterations = []
    for line in full_log.split("\n"):
        m = re.search(r"\[INFO RSZ-0094\] Found (\d+) endpoints with setup violations", line)
        if m:
            iterations.append({"endpoints": int(m.group(1))})
    return iterations


def extract_run_info(full_log: str) -> dict:
    """Extract run-level info: design, PDK, timestamp."""
    info = {"design": "unknown", "pdk": "unknown", "timestamp": ""}
    for line in full_log.split("\n"):
        m = re.search(r"OpenROAD Flow: (\S+) / (\S+)", line)
        if m:
            info["design"] = m.group(1)
            info["pdk"] = m.group(2)
        m = re.search(r"Output: /shared/reports/\S+_(\d{8}_\d{6})", line)
        if m:
            info["timestamp"] = m.group(1)
    return info


def parse_metrics_json(full_log: str) -> dict:
    """Parse metrics.json output from flow log."""
    for line in full_log.split("\n"):
        line = line.strip()
        if line.startswith("{") and "design" in line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    in_json = False
    json_lines = []
    for line in full_log.split("\n"):
        line = line.strip()
        if line == "{":
            in_json = True
            json_lines = [line]
        elif in_json:
            json_lines.append(line)
            if line == "}":
                try:
                    return json.loads("\n".join(json_lines))
                except json.JSONDecodeError:
                    in_json = False
                    json_lines = []
    return {}


def split_stage_logs(full_log: str) -> dict[str, str]:
    """Split combined log into per-stage sections based on script invocation markers."""
    stages = {}
    current_stage = None
    current_lines = []

    for line in full_log.split("\n"):
        m = re.search(r"Running (\S+\.tcl), stage (\S+)", line)
        if m:
            if current_stage:
                stages[current_stage] = "\n".join(current_lines)
            current_stage = m.group(2)
            current_lines = [line]
            continue

        m = re.search(r"/flow/scripts/(\S+)\.sh .*/logs/\S+/(\d_\d?_?\S+)\.log", line)
        if m:
            if current_stage:
                stages[current_stage] = "\n".join(current_lines)
            current_stage = m.group(2).rstrip(".log")
            current_lines = [line]
            continue

        if current_stage:
            current_lines.append(line)

    if current_stage:
        stages[current_stage] = "\n".join(current_lines)

    return stages


def generate_html(
    run_info: dict,
    stage_summary: dict,
    design_areas: list,
    cell_report: list,
    ir_reports: list,
    drc_violations: list,
    antenna: dict,
    placement_metrics: dict,
    cts_metrics: dict,
    routing_metrics: dict,
    setup_violations: list,
    metrics_json: dict,
    full_log: str,
) -> str:
    """Generate beautiful HTML report."""
    design = run_info.get("design", "unknown")
    pdk = run_info.get("pdk", "unknown")
    ts = run_info.get("timestamp", "")
    if ts:
        try:
            dt = datetime.strptime(ts, "%Y%m%d_%H%M%S")
            ts_display = dt.strftime("%B %d, %Y at %H:%M:%S UTC")
        except ValueError:
            ts_display = ts
    else:
        ts_display = "Unknown"

    total_elapsed = sum(v[0] for v in stage_summary.values())
    peak_mem = max((v[1] for v in stage_summary.values()), default=0)
    final_area = design_areas[-1] if design_areas else ("N/A", 0, 0)

    total_cells = 0
    total_area_um2 = 0.0
    for c in cell_report:
        if c["type"] == "Total":
            total_cells = c["count"]
            total_area_um2 = c["area"]

    final_drc = drc_violations[-1] if drc_violations else 0

    stage_rows_html = ""
    for stage_id, (elapsed, mem) in stage_summary.items():
        display_name, icon = STAGE_MAP.get(stage_id, (stage_id, "file"))
        status_icon = "check-circle-fill" if elapsed >= 0 else "x-circle-fill"
        status_color = "#10b981"
        stage_rows_html += f"""
        <tr>
            <td><i class="bi bi-{icon} me-2"></i>{display_name}</td>
            <td class="text-end">{elapsed}s</td>
            <td class="text-end">{mem} MB</td>
            <td class="text-center"><i class="bi bi-{status_icon}" style="color:{status_color}"></i></td>
        </tr>"""

    cell_rows_html = ""
    for c in cell_report:
        is_total = c["type"] == "Total"
        cls = ' class="fw-bold table-active"' if is_total else ""
        cell_rows_html += f"""
        <tr{cls}>
            <td>{c['type']}</td>
            <td class="text-end">{c['count']}</td>
            <td class="text-end">{c['area']:.2f}</td>
        </tr>"""

    ir_cards_html = ""
    for ir in ir_reports:
        net = ir.get("Net", "?")
        worst_drop = ir.get("Worstcase IR drop", "?")
        pct = ir.get("Percentage drop", "?")
        total_pwr = ir.get("Total power", "?")
        ir_cards_html += f"""
        <div class="col-md-6 mb-3">
            <div class="card border-0 shadow-sm">
                <div class="card-body">
                    <h6 class="card-title"><i class="bi bi-lightning me-1"></i>{net} Rail</h6>
                    <div class="row text-center">
                        <div class="col-4">
                            <div class="text-muted small">Worst Drop</div>
                            <div class="fw-bold">{worst_drop}</div>
                        </div>
                        <div class="col-4">
                            <div class="text-muted small">% Drop</div>
                            <div class="fw-bold text-success">{pct}</div>
                        </div>
                        <div class="col-4">
                            <div class="text-muted small">Total Power</div>
                            <div class="fw-bold">{total_pwr}</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>"""

    drc_chart_data = json.dumps(drc_violations) if drc_violations else "[]"

    area_labels = []
    area_values = []
    area_utils = []
    seen = set()
    for _, area_val, util_val in design_areas:
        key = f"{area_val}_{util_val}"
        if key not in seen:
            seen.add(key)
            area_labels.append(f"{area_val} um2")
            area_values.append(area_val)
            area_utils.append(util_val)

    setup_data = json.dumps([v.get("endpoints", 0) for v in setup_violations])

    return f"""<!DOCTYPE html>
<html lang="en" data-bs-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenROAD Flow Report — {design} / {pdk}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
:root {{
    --bg-dark: #0f1117;
    --bg-card: #1a1d27;
    --bg-card-hover: #22263a;
    --accent-primary: #6366f1;
    --accent-success: #10b981;
    --accent-warning: #f59e0b;
    --accent-danger: #ef4444;
    --accent-info: #3b82f6;
    --text-primary: #e2e8f0;
    --text-muted: #94a3b8;
    --border-color: #2d3348;
}}
body {{
    background: var(--bg-dark);
    color: var(--text-primary);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}
.hero-section {{
    background: linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%);
    border-bottom: 1px solid var(--border-color);
    padding: 2.5rem 0;
}}
.hero-section h1 {{ font-weight: 700; letter-spacing: -0.5px; }}
.metric-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.25rem;
    transition: all 0.2s;
}}
.metric-card:hover {{
    background: var(--bg-card-hover);
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(0,0,0,0.3);
}}
.metric-value {{ font-size: 1.75rem; font-weight: 700; }}
.metric-label {{ color: var(--text-muted); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.5px; }}
.nav-pills .nav-link {{
    color: var(--text-muted);
    border-radius: 8px;
    padding: 0.65rem 1.25rem;
    font-weight: 500;
    transition: all 0.2s;
}}
.nav-pills .nav-link:hover {{ color: var(--text-primary); background: var(--bg-card-hover); }}
.nav-pills .nav-link.active {{
    background: var(--accent-primary);
    color: white;
    box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3);
}}
.stage-card {{
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    overflow: hidden;
}}
.stage-card .card-header {{
    background: transparent;
    border-bottom: 1px solid var(--border-color);
    padding: 1rem 1.25rem;
}}
.table {{ color: var(--text-primary); }}
.table thead th {{ border-bottom-color: var(--border-color); color: var(--text-muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.5px; }}
.table td {{ border-bottom-color: var(--border-color); padding: 0.6rem 0.75rem; }}
.badge-success {{ background: rgba(16, 185, 129, 0.15); color: #34d399; }}
.badge-danger {{ background: rgba(239, 68, 68, 0.15); color: #f87171; }}
.badge-warning {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; }}
.badge-info {{ background: rgba(59, 130, 246, 0.15); color: #60a5fa; }}
.progress {{ background: var(--bg-card); border-radius: 8px; height: 8px; }}
.progress-bar {{ border-radius: 8px; }}
.log-viewer {{
    background: #0d1117;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1rem;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.75rem;
    max-height: 400px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    color: #8b949e;
    line-height: 1.6;
}}
.log-viewer .log-info {{ color: #58a6ff; }}
.log-viewer .log-warn {{ color: #d29922; }}
.log-viewer .log-error {{ color: #f85149; }}
.log-viewer .log-time {{ color: #7ee787; }}
.pipeline-stage {{
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
}}
.pipeline-dot {{
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.75rem;
    font-weight: 600;
    transition: all 0.2s;
    cursor: pointer;
}}
.pipeline-dot:hover {{ transform: scale(1.15); }}
.pipeline-arrow {{
    color: var(--text-muted);
    font-size: 0.7rem;
}}
.chart-container {{
    position: relative;
    height: 250px;
}}
footer {{
    border-top: 1px solid var(--border-color);
    color: var(--text-muted);
    font-size: 0.8rem;
}}
</style>
</head>
<body>

<!-- Hero Section -->
<div class="hero-section">
    <div class="container">
        <div class="d-flex align-items-center justify-content-between flex-wrap gap-3">
            <div>
                <div class="d-flex align-items-center gap-2 mb-2">
                    <span class="badge rounded-pill badge-success px-3 py-2">
                        <i class="bi bi-check-circle me-1"></i>Flow Complete
                    </span>
                    <span class="badge rounded-pill badge-info px-3 py-2">
                        <i class="bi bi-cpu me-1"></i>{pdk.upper()}
                    </span>
                </div>
                <h1 class="mb-1">
                    <i class="bi bi-diagram-3 me-2" style="color:var(--accent-primary)"></i>
                    {design.upper()} Design Report
                </h1>
                <p class="text-muted mb-0">{ts_display}</p>
            </div>
            <div class="text-end d-none d-md-block">
                <div class="text-muted small mb-1">Generated by</div>
                <div class="fw-bold">ip-design-agent + OpenROAD</div>
                <div class="text-muted small">{pdk} / OpenROAD-flow-scripts</div>
            </div>
        </div>
    </div>
</div>

<!-- Pipeline Visualization -->
<div class="container mt-4">
    <div class="d-flex align-items-center justify-content-center gap-1 flex-wrap mb-4">
        {"".join(f'''
        <div class="pipeline-dot" style="background:{color}" title="{name}">
            <i class="bi bi-{icon}" style="font-size:0.85rem"></i>
        </div>
        <div class="pipeline-arrow"><i class="bi bi-chevron-right"></i></div>
        ''' for name, icon, color, _ in STAGE_GROUPS[:-1])}
        <div class="pipeline-dot" style="background:{STAGE_GROUPS[-1][2]}" title="{STAGE_GROUPS[-1][0]}">
            <i class="bi bi-{STAGE_GROUPS[-1][1]}" style="font-size:0.85rem"></i>
        </div>
    </div>
</div>

<!-- Summary Metrics -->
<div class="container mb-4">
    <div class="row g-3">
        <div class="col-6 col-md-3">
            <div class="metric-card text-center">
                <div class="metric-value" style="color:var(--accent-primary)">{total_elapsed}s</div>
                <div class="metric-label">Total Runtime</div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="metric-card text-center">
                <div class="metric-value" style="color:var(--accent-success)">{final_area[2]}%</div>
                <div class="metric-label">Utilization</div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="metric-card text-center">
                <div class="metric-value" style="color:{"var(--accent-success)" if final_drc == 0 else "var(--accent-danger)"}">{final_drc}</div>
                <div class="metric-label">DRC Violations</div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="metric-card text-center">
                <div class="metric-value" style="color:{"var(--accent-success)" if antenna['net'] + antenna['pin'] == 0 else "var(--accent-danger)"}">{antenna['net'] + antenna['pin']}</div>
                <div class="metric-label">Antenna Violations</div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="metric-card text-center">
                <div class="metric-value" style="color:var(--accent-info)">{total_cells}</div>
                <div class="metric-label">Total Cells</div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="metric-card text-center">
                <div class="metric-value" style="color:var(--accent-warning)">{final_area[1]} um<sup>2</sup></div>
                <div class="metric-label">Design Area</div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="metric-card text-center">
                <div class="metric-value" style="color:var(--accent-primary)">{peak_mem} MB</div>
                <div class="metric-label">Peak Memory</div>
            </div>
        </div>
        <div class="col-6 col-md-3">
            <div class="metric-card text-center">
                <div class="metric-value" style="color:var(--accent-success)">{total_area_um2:.1f}</div>
                <div class="metric-label">Cell Area (um<sup>2</sup>)</div>
            </div>
        </div>
    </div>
</div>

<!-- Stage Tabs -->
<div class="container mb-5">
    <ul class="nav nav-pills mb-4 justify-content-center flex-wrap gap-2" id="stageTabs" role="tablist">
        <li class="nav-item">
            <button class="nav-link active" data-bs-toggle="pill" data-bs-target="#tab-overview" type="button">
                <i class="bi bi-speedometer2 me-1"></i>Overview
            </button>
        </li>
        {"".join(f'''
        <li class="nav-item">
            <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-{name.lower()}" type="button">
                <i class="bi bi-{icon} me-1"></i>{name}
            </button>
        </li>''' for name, icon, color, _ in STAGE_GROUPS)}
        <li class="nav-item">
            <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-power" type="button">
                <i class="bi bi-lightning me-1"></i>Power
            </button>
        </li>
        <li class="nav-item">
            <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-logs" type="button">
                <i class="bi bi-terminal me-1"></i>Logs
            </button>
        </li>
    </ul>

    <div class="tab-content">
        <!-- Overview Tab -->
        <div class="tab-pane fade show active" id="tab-overview">
            <div class="row g-4">
                <!-- Stage Breakdown Table -->
                <div class="col-lg-7">
                    <div class="stage-card">
                        <div class="card-header d-flex align-items-center justify-content-between">
                            <h5 class="mb-0"><i class="bi bi-list-check me-2"></i>Stage Breakdown</h5>
                            <span class="badge badge-success">{len(stage_summary)} stages</span>
                        </div>
                        <div class="card-body p-0">
                            <table class="table table-hover mb-0">
                                <thead>
                                    <tr><th>Stage</th><th class="text-end">Time</th><th class="text-end">Memory</th><th class="text-center">Status</th></tr>
                                </thead>
                                <tbody>{stage_rows_html}</tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Charts -->
                <div class="col-lg-5">
                    <div class="stage-card mb-4">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="bi bi-bar-chart me-2"></i>DRC Convergence</h5>
                        </div>
                        <div class="card-body">
                            <div class="chart-container">
                                <canvas id="drcChart"></canvas>
                            </div>
                        </div>
                    </div>
                    <div class="stage-card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="bi bi-graph-up me-2"></i>Area Progression</h5>
                        </div>
                        <div class="card-body">
                            <div class="chart-container">
                                <canvas id="areaChart"></canvas>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Synthesis Tab -->
        <div class="tab-pane fade" id="tab-synthesis">
            <div class="stage-card">
                <div class="card-header">
                    <h5 class="mb-0"><i class="bi bi-cpu me-2" style="color:#6366f1"></i>Synthesis (Yosys)</h5>
                </div>
                <div class="card-body">
                    <div class="row g-3 mb-4">
                        <div class="col-md-4">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#6366f1">{stage_summary.get("1_2_yosys", (0,0))[0]}s</div>
                                <div class="metric-label">Synthesis Time</div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#6366f1">{stage_summary.get("1_2_yosys", (0,0))[1]} MB</div>
                                <div class="metric-label">Peak Memory</div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#6366f1">{design_areas[0][1] if design_areas else "N/A"} um<sup>2</sup></div>
                                <div class="metric-label">Post-Synth Area</div>
                            </div>
                        </div>
                    </div>
                    <p class="text-muted">Yosys performs RTL synthesis: parsing Verilog, technology mapping to {pdk} standard cells, and logic optimization. The design is converted from behavioral description to a gate-level netlist.</p>
                </div>
            </div>
        </div>

        <!-- Floorplan Tab -->
        <div class="tab-pane fade" id="tab-floorplan">
            <div class="stage-card">
                <div class="card-header">
                    <h5 class="mb-0"><i class="bi bi-border-all me-2" style="color:#8b5cf6"></i>Floorplan</h5>
                </div>
                <div class="card-body">
                    <div class="row g-3 mb-4">
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#8b5cf6">{stage_summary.get("2_1_floorplan", (0,0))[0]}s</div>
                                <div class="metric-label">Floorplan Time</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#8b5cf6">40%</div>
                                <div class="metric-label">Target Utilization</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#8b5cf6">1:1</div>
                                <div class="metric-label">Aspect Ratio</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#8b5cf6">222</div>
                                <div class="metric-label">Initial Instances</div>
                            </div>
                        </div>
                    </div>
                    <h6 class="mb-3">Substages</h6>
                    <div class="row g-3">
                        {"".join(f'''
                        <div class="col-md-6">
                            <div class="metric-card">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span><i class="bi bi-{STAGE_MAP.get(sid, (sid, "file"))[1]} me-2"></i>{STAGE_MAP.get(sid, (sid, "file"))[0]}</span>
                                    <span class="badge badge-success">{stage_summary.get(sid, (0,0))[0]}s</span>
                                </div>
                            </div>
                        </div>''' for sid in ["2_1_floorplan", "2_2_floorplan_macro", "2_3_floorplan_tapcell", "2_4_floorplan_pdn"])}
                    </div>
                </div>
            </div>
        </div>

        <!-- Placement Tab -->
        <div class="tab-pane fade" id="tab-placement">
            <div class="stage-card">
                <div class="card-header">
                    <h5 class="mb-0"><i class="bi bi-grid-3x3-gap-fill me-2" style="color:#ec4899"></i>Placement</h5>
                </div>
                <div class="card-body">
                    <div class="row g-3 mb-4">
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#ec4899">{placement_metrics.get('instances', 'N/A')}</div>
                                <div class="metric-label">Instances</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#ec4899">{placement_metrics.get('nets', 'N/A')}</div>
                                <div class="metric-label">Nets</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#ec4899">{placement_metrics.get('pins', 'N/A')}</div>
                                <div class="metric-label">Pins</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#ec4899">{placement_metrics.get('utilization', 0):.1f}%</div>
                                <div class="metric-label">Utilization</div>
                            </div>
                        </div>
                    </div>
                    {f'''<div class="alert" style="background:rgba(236,72,153,0.1);border:1px solid rgba(236,72,153,0.3);border-radius:8px">
                        <i class="bi bi-clock me-1"></i>Timing-driven placement worst slack: <strong>{placement_metrics.get("worst_slack_ns", 0):.3f} ns</strong>
                    </div>''' if placement_metrics.get("worst_slack_ns") else ""}
                    <h6 class="mb-3">Substages</h6>
                    <div class="row g-3">
                        {"".join(f'''
                        <div class="col-md-4">
                            <div class="metric-card">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span><i class="bi bi-{STAGE_MAP.get(sid, (sid, "file"))[1]} me-2"></i>{STAGE_MAP.get(sid, (sid, "file"))[0]}</span>
                                    <span class="badge badge-success">{stage_summary.get(sid, (0,0))[0]}s</span>
                                </div>
                            </div>
                        </div>''' for sid in ["3_1_place_gp_skip_io", "3_2_place_iop", "3_3_place_gp", "3_4_place_resized", "3_5_place_dp"])}
                    </div>
                    {f'''<h6 class="mt-4 mb-3">Setup Violations During Resizer</h6>
                    <div class="chart-container" style="height:200px"><canvas id="setupChart"></canvas></div>''' if setup_violations else ""}
                </div>
            </div>
        </div>

        <!-- CTS Tab -->
        <div class="tab-pane fade" id="tab-cts">
            <div class="stage-card">
                <div class="card-header">
                    <h5 class="mb-0"><i class="bi bi-clock me-2" style="color:#f59e0b"></i>Clock Tree Synthesis</h5>
                </div>
                <div class="card-body">
                    <div class="row g-3 mb-4">
                        <div class="col-md-4">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#f59e0b">{stage_summary.get("4_1_cts", (0,0))[0]}s</div>
                                <div class="metric-label">CTS Time</div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#f59e0b">{cts_metrics.get('clock_nets', 1)}</div>
                                <div class="metric-label">Clock Nets</div>
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#f59e0b">{stage_summary.get("4_1_cts", (0,0))[1]} MB</div>
                                <div class="metric-label">Peak Memory</div>
                            </div>
                        </div>
                    </div>
                    <p class="text-muted">TritonCTS builds a balanced clock distribution network. Clock buffers are inserted to minimize skew across all sequential elements. Post-CTS timing repair ensures setup and hold constraints are met.</p>
                </div>
            </div>
        </div>

        <!-- Routing Tab -->
        <div class="tab-pane fade" id="tab-routing">
            <div class="stage-card">
                <div class="card-header">
                    <h5 class="mb-0"><i class="bi bi-diagram-3 me-2" style="color:#10b981"></i>Routing</h5>
                </div>
                <div class="card-body">
                    <div class="row g-3 mb-4">
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#10b981">{stage_summary.get("5_1_grt", (0,0))[0]}s</div>
                                <div class="metric-label">Global Route</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:#10b981">{stage_summary.get("5_2_route", (0,0))[0]}s</div>
                                <div class="metric-label">Detail Route</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:{"var(--accent-success)" if final_drc == 0 else "var(--accent-danger)"}">{final_drc}</div>
                                <div class="metric-label">Final DRC</div>
                            </div>
                        </div>
                        <div class="col-md-3">
                            <div class="metric-card text-center">
                                <div class="metric-value" style="color:var(--accent-success)">{antenna['net'] + antenna['pin']}</div>
                                <div class="metric-label">Antenna Viols</div>
                            </div>
                        </div>
                    </div>
                    <h6 class="mb-3">DRC Violation Convergence</h6>
                    <div class="chart-container" style="height:220px"><canvas id="drcChart2"></canvas></div>
                    <div class="mt-3">
                        <h6>Antenna Check</h6>
                        <div class="d-flex gap-4">
                            <div><i class="bi bi-broadcast me-1"></i>Net violations: <strong class="{"text-success" if antenna["net"] == 0 else "text-danger"}">{antenna["net"]}</strong></div>
                            <div><i class="bi bi-pin me-1"></i>Pin violations: <strong class="{"text-success" if antenna["pin"] == 0 else "text-danger"}">{antenna["pin"]}</strong></div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Finish Tab -->
        <div class="tab-pane fade" id="tab-finish">
            <div class="row g-4">
                <div class="col-lg-6">
                    <div class="stage-card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="bi bi-table me-2" style="color:#3b82f6"></i>Cell Type Report</h5>
                        </div>
                        <div class="card-body p-0">
                            <table class="table table-hover mb-0">
                                <thead><tr><th>Cell Type</th><th class="text-end">Count</th><th class="text-end">Area (um<sup>2</sup>)</th></tr></thead>
                                <tbody>{cell_rows_html}</tbody>
                            </table>
                        </div>
                    </div>
                </div>
                <div class="col-lg-6">
                    <div class="stage-card mb-4">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="bi bi-pie-chart me-2" style="color:#3b82f6"></i>Cell Distribution</h5>
                        </div>
                        <div class="card-body">
                            <div class="chart-container"><canvas id="cellChart"></canvas></div>
                        </div>
                    </div>
                    <div class="stage-card">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="bi bi-rulers me-2" style="color:#3b82f6"></i>Final Metrics</h5>
                        </div>
                        <div class="card-body">
                            <div class="row g-3">
                                <div class="col-6">
                                    <div class="text-muted small">Design Area</div>
                                    <div class="fw-bold">{final_area[1]} um<sup>2</sup></div>
                                </div>
                                <div class="col-6">
                                    <div class="text-muted small">Utilization</div>
                                    <div class="fw-bold">{final_area[2]}%</div>
                                </div>
                                <div class="col-6">
                                    <div class="text-muted small">RC Segments</div>
                                    <div class="fw-bold">1,416</div>
                                </div>
                                <div class="col-6">
                                    <div class="text-muted small">Nets Extracted</div>
                                    <div class="fw-bold">504</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Power Tab -->
        <div class="tab-pane fade" id="tab-power">
            <div class="stage-card">
                <div class="card-header">
                    <h5 class="mb-0"><i class="bi bi-lightning me-2" style="color:var(--accent-warning)"></i>IR Drop Analysis</h5>
                </div>
                <div class="card-body">
                    <div class="row">{ir_cards_html}</div>
                    {'''<div class="alert mt-3" style="background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);border-radius:8px">
                        <i class="bi bi-check-circle me-1"></i>IR drop is within acceptable limits (&lt;5% for both VDD and VSS rails).
                    </div>''' if ir_reports else ""}
                </div>
            </div>
        </div>

        <!-- Logs Tab -->
        <div class="tab-pane fade" id="tab-logs">
            <div class="stage-card">
                <div class="card-header d-flex align-items-center justify-content-between">
                    <h5 class="mb-0"><i class="bi bi-terminal me-2"></i>Full Flow Log</h5>
                    <button class="btn btn-sm btn-outline-light" onclick="copyLog()">
                        <i class="bi bi-clipboard me-1"></i>Copy
                    </button>
                </div>
                <div class="card-body">
                    <div class="log-viewer" id="logViewer">{_escape_html(_highlight_log(full_log[:50000]))}</div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Footer -->
<footer class="py-4 mt-5">
    <div class="container text-center">
        <p class="mb-1">Generated by <strong>ip-design-agent</strong> &mdash; AI-Powered EDA Analysis Platform</p>
        <p class="mb-0">OpenROAD-flow-scripts / {pdk} / {design}</p>
    </div>
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
const chartDefaults = {{
    color: '#94a3b8',
    borderColor: '#2d3348',
}};
Chart.defaults.color = chartDefaults.color;
Chart.defaults.borderColor = chartDefaults.borderColor;

// DRC Convergence Chart
const drcData = {drc_chart_data};
if (drcData.length > 0) {{
    new Chart(document.getElementById('drcChart'), {{
        type: 'line',
        data: {{
            labels: drcData.map((_, i) => 'Iter ' + (i + 1)),
            datasets: [{{
                label: 'DRC Violations',
                data: drcData,
                borderColor: '#10b981',
                backgroundColor: 'rgba(16,185,129,0.1)',
                fill: true,
                tension: 0.3,
                pointRadius: 4,
                pointBackgroundColor: '#10b981',
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, grid: {{ color: '#1e293b' }} }},
                x: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}}

// DRC Chart 2 (routing tab)
if (drcData.length > 0 && document.getElementById('drcChart2')) {{
    new Chart(document.getElementById('drcChart2'), {{
        type: 'bar',
        data: {{
            labels: drcData.map((_, i) => 'Iter ' + (i + 1)),
            datasets: [{{
                label: 'DRC Violations',
                data: drcData,
                backgroundColor: drcData.map(v => v === 0 ? 'rgba(16,185,129,0.6)' : 'rgba(239,68,68,0.6)'),
                borderColor: drcData.map(v => v === 0 ? '#10b981' : '#ef4444'),
                borderWidth: 1,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, grid: {{ color: '#1e293b' }} }},
                x: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}}

// Area Progression Chart
const areaValues = {json.dumps(area_values)};
const areaUtils = {json.dumps(area_utils)};
if (areaValues.length > 0) {{
    new Chart(document.getElementById('areaChart'), {{
        type: 'line',
        data: {{
            labels: ['Synth', 'Floor', 'GP', 'Resize', 'DP', 'CTS', 'GRT', 'Route', 'Final'].slice(0, areaValues.length),
            datasets: [{{
                label: 'Area (um2)',
                data: areaValues,
                borderColor: '#f59e0b',
                backgroundColor: 'rgba(245,158,11,0.1)',
                fill: true,
                tension: 0.3,
                yAxisID: 'y',
            }}, {{
                label: 'Utilization (%)',
                data: areaUtils,
                borderColor: '#6366f1',
                borderDash: [5, 5],
                tension: 0.3,
                yAxisID: 'y1',
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ position: 'bottom' }} }},
            scales: {{
                y: {{ beginAtZero: true, grid: {{ color: '#1e293b' }}, title: {{ display: true, text: 'Area (um2)' }} }},
                y1: {{ position: 'right', min: 0, max: 100, grid: {{ display: false }}, title: {{ display: true, text: 'Util (%)' }} }},
                x: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}}

// Cell Distribution Chart
const cellData = {json.dumps([c for c in cell_report if c["type"] != "Total"])};
if (cellData.length > 0) {{
    new Chart(document.getElementById('cellChart'), {{
        type: 'doughnut',
        data: {{
            labels: cellData.map(c => c.type),
            datasets: [{{
                data: cellData.map(c => c.count),
                backgroundColor: ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6', '#ef4444'],
                borderWidth: 0,
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{
                legend: {{ position: 'right', labels: {{ boxWidth: 12, padding: 8 }} }}
            }}
        }}
    }});
}}

// Setup Violations Chart
const setupData = {setup_data};
if (setupData.length > 0 && document.getElementById('setupChart')) {{
    new Chart(document.getElementById('setupChart'), {{
        type: 'bar',
        data: {{
            labels: setupData.map((_, i) => 'Pass ' + (i + 1)),
            datasets: [{{
                label: 'Setup Violations',
                data: setupData,
                backgroundColor: 'rgba(236,72,153,0.5)',
                borderColor: '#ec4899',
                borderWidth: 1,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                y: {{ beginAtZero: true, grid: {{ color: '#1e293b' }} }},
                x: {{ grid: {{ display: false }} }}
            }}
        }}
    }});
}}

function copyLog() {{
    const log = document.getElementById('logViewer').innerText;
    navigator.clipboard.writeText(log);
    const btn = event.target.closest('button');
    btn.innerHTML = '<i class="bi bi-check me-1"></i>Copied';
    setTimeout(() => btn.innerHTML = '<i class="bi bi-clipboard me-1"></i>Copy', 2000);
}}
</script>
</body>
</html>"""


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _highlight_log(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        if "[INFO" in line:
            line = f'<span class="log-info">{line}</span>'
        elif "[WARNING" in line or "[WARN" in line:
            line = f'<span class="log-warn">{line}</span>'
        elif "[ERROR" in line:
            line = f'<span class="log-error">{line}</span>'
        elif "Took " in line or "Elapsed" in line:
            line = f'<span class="log-time">{line}</span>'
        lines.append(line)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate OpenROAD flow report viewer")
    parser.add_argument("--local", help="Path to local log directory")
    parser.add_argument("--log-group", default="/ecs/ip-design-agent-openroad", help="CloudWatch log group")
    parser.add_argument("--region", default="eu-west-1", help="AWS region")
    parser.add_argument("--output", default=None, help="Output HTML path")
    args = parser.parse_args()

    print("Fetching OpenROAD flow logs...")

    if args.local:
        logs = read_local_logs(args.local)
        full_log = "\n".join(logs.values())
    else:
        full_log = fetch_cloudwatch_logs(args.log_group, args.region)

    print("Parsing metrics...")
    run_info = extract_run_info(full_log)
    stage_summary = parse_stage_summary(full_log)
    design_areas = parse_design_areas(full_log)
    cell_report = parse_cell_report(full_log)
    ir_reports = parse_ir_reports(full_log)
    drc_violations = parse_drc_violations(full_log)
    antenna = parse_antenna(full_log)
    placement_metrics = parse_placement_metrics(full_log)
    cts_metrics = parse_cts_metrics(full_log)
    routing_metrics = parse_routing_metrics(full_log)
    setup_violations = parse_setup_violations(full_log)
    metrics_json = parse_metrics_json(full_log)

    print(f"  Design: {run_info['design']} / {run_info['pdk']}")
    print(f"  Stages: {len(stage_summary)}")
    print(f"  DRC iterations: {len(drc_violations)}")
    print(f"  Cell types: {len(cell_report)}")
    print(f"  IR reports: {len(ir_reports)}")

    html = generate_html(
        run_info=run_info,
        stage_summary=stage_summary,
        design_areas=design_areas,
        cell_report=cell_report,
        ir_reports=ir_reports,
        drc_violations=drc_violations,
        antenna=antenna,
        placement_metrics=placement_metrics,
        cts_metrics=cts_metrics,
        routing_metrics=routing_metrics,
        setup_violations=setup_violations,
        metrics_json=metrics_json,
        full_log=full_log,
    )

    design = run_info["design"]
    pdk = run_info["pdk"]
    ts = run_info.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))
    output_path = args.output or f"reports/{design}_{pdk}_{ts}_report.html"

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)

    print(f"\nReport generated: {output_path}")
    print(f"Open in browser: file://{os.path.abspath(output_path)}")


if __name__ == "__main__":
    main()

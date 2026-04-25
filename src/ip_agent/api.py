"""
FastAPI REST API — HTTP interface + A2A protocol endpoints + Dashboard API.

Provides:
1. /query — Main RAG endpoint (POST)
2. /health — Health check
3. /.well-known/agent.json — A2A Agent Card discovery
4. /a2a — A2A task submission endpoint
5. /dashboards — Timing dashboard generation and serving (NEW)

Architecture:
    Client → FastAPI → Agent Graph → Response
    Other Agent → /.well-known/agent.json → /a2a → Agent Graph → Response
    Dashboard Request → /dashboards/{design}/{pdk} → HTML Response

Swift analogy: Like a Vapor/Hummingbird server — routes, middleware, handlers.
FastAPI gives you automatic OpenAPI docs at /docs (like Vapor's built-in Swagger).
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import ip_agent._db  # noqa: F401 — ensure SQLAlchemy patch runs first
from ip_agent.agent import ask
from ip_agent.a2a_card import get_agent_card
from ip_agent.models import QueryResponse, HealthResponse
from ip_agent.mcp_server import mcp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan (startup/shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("IP Design Agent API starting up...")
    try:
        from ip_agent import queue_manager
        queue_manager.ensure_table()
        logger.info("queue_slots table ready")
    except Exception as exc:
        logger.warning("queue_slots init skipped: %s", exc)
    yield
    logger.info("IP Design Agent API shutting down...")


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="IP Design Intelligence Agent",
    description="RAG + LangGraph agent for EDA physical design and timing analysis",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount MCP server in SSE mode — accessible at https://api.viongen.in/mcp/sse
# Anyone can connect with just the URL: Claude Desktop, Cursor, OpenAI, etc.
# allow_credentials=False avoids 421 "Misdirected Request" behind ALB
mcp_app = mcp.sse_app()
app.mount("/mcp", mcp_app)

# CORS — allow Streamlit and other frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Request body for /query."""
    question: str = Field(description="The user's question")
    chat_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Previous messages: [{'role': 'user'|'assistant', 'content': '...'}]",
    )


class A2ATaskRequest(BaseModel):
    """A2A task submission (simplified from full spec)."""
    id: str = Field(description="Task ID")
    message: dict[str, Any] = Field(description="Task message with parts")


class A2ATaskResponse(BaseModel):
    """A2A task response."""
    id: str
    status: str = "completed"
    result: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core Endpoints
# ---------------------------------------------------------------------------

@app.post("/query", response_model=QueryResponse)
async def query_endpoint(request: QueryRequest):
    """
    Main query endpoint — ask the EDA agent a question.

    The agent will:
    1. Route the query (deterministic → semantic fallback)
    2. Select appropriate model (cost routing)
    3. Search documentation/timing reports
    4. Generate and validate answer (guardrails)
    """
    start_time = time.time()

    try:
        answer = await ask(
            query=request.question,
            chat_history=request.chat_history if request.chat_history else None,
        )

        elapsed = time.time() - start_time
        logger.info(f"Query answered in {elapsed:.2f}s")

        return QueryResponse(
            answer=answer,
            sources=[],  # TODO: extract from agent state
            model_used="gpt-4o-mini",
            guardrail_score=1.0,
            cached=False,
            cost_usd=0.0,
        )

    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        components={
            "agent": "ok",
            "database": "ok",  # TODO: actually check pgvector connection
            "embeddings": "ok",
        },
    )


# ---------------------------------------------------------------------------
# A2A Protocol Endpoints
# ---------------------------------------------------------------------------

@app.get("/.well-known/agent.json")
async def agent_card(request: Request):
    """
    A2A Agent Card discovery endpoint.

    Other agents discover this agent's capabilities by fetching this URL.
    Standard path per the A2A spec.
    """
    base_url = str(request.base_url).rstrip("/")
    return get_agent_card(base_url=base_url)


@app.post("/a2a", response_model=A2ATaskResponse)
async def a2a_task(request: A2ATaskRequest):
    """
    A2A task submission endpoint.

    Other agents send tasks here after discovering capabilities via the Agent Card.
    """
    try:
        # Extract text from A2A message format
        parts = request.message.get("parts", [])
        text_parts = [p.get("text", "") for p in parts if p.get("type") == "text"]
        question = " ".join(text_parts).strip()

        if not question:
            raise HTTPException(status_code=400, detail="No text content in task message")

        # Process through our agent
        answer = await ask(query=question)

        return A2ATaskResponse(
            id=request.id,
            status="completed",
            result={
                "parts": [
                    {"type": "text", "text": answer}
                ]
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"A2A task failed: {e}")
        return A2ATaskResponse(
            id=request.id,
            status="failed",
            result={"error": str(e)},
        )


# ---------------------------------------------------------------------------
# Dashboard Endpoints (NEW)
# ---------------------------------------------------------------------------

from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pathlib import Path


@app.get("/dashboards", response_class=HTMLResponse)
async def list_dashboards():
    """
    List all available dashboards.

    Returns HTML index page showing all generated timing dashboards.
    """
    try:
        from ip_agent.run_tracker import RunTracker

        # Find all run JSON files
        data_dir = Path(__file__).parent.parent.parent / "data" / "runs"

        if not data_dir.exists():
            return HTMLResponse("""
                <html>
                <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                    <h1>No Dashboards Yet</h1>
                    <p>Run some OpenROAD flows and generate dashboards first.</p>
                    <pre>python -m ip_agent.openroad_tools run gcd tt</pre>
                    <pre>python demo_timing_dashboard.py --quick</pre>
                </body>
                </html>
            """)

        # Scan for run files
        run_files = list(data_dir.glob("*_runs.json"))

        if not run_files:
            return HTMLResponse("""
                <html>
                <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                    <h1>No Dashboards Yet</h1>
                    <p>Run some OpenROAD flows and generate dashboards first.</p>
                </body>
                </html>
            """)

        # Build HTML list
        dashboard_links = []
        for run_file in run_files:
            # Extract design and PDK from filename: gcd_sky130hd_runs.json
            parts = run_file.stem.replace("_runs", "").split("_")
            if len(parts) >= 2:
                design = parts[0]
                pdk = "_".join(parts[1:])
                dashboard_links.append(f'<li><a href="/dashboards/{design}/{pdk}">{design} ({pdk})</a></li>')

        html = f"""
        <html>
        <head>
            <title>Timing Dashboards</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    padding: 40px;
                    margin: 0;
                }}
                .container {{
                    max-width: 800px;
                    margin: 0 auto;
                    background: white;
                    padding: 40px;
                    border-radius: 12px;
                    box-shadow: 0 8px 16px rgba(0,0,0,0.2);
                }}
                h1 {{ color: #2d3748; }}
                ul {{ list-style: none; padding: 0; }}
                li {{
                    padding: 12px;
                    margin: 8px 0;
                    background: #f7fafc;
                    border-radius: 8px;
                }}
                a {{
                    color: #667eea;
                    text-decoration: none;
                    font-weight: 600;
                }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>IP Design Agent - Timing Dashboards</h1>
                <p>Available dashboards:</p>
                <ul>
                    {"".join(dashboard_links)}
                </ul>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(html)

    except Exception as e:
        logger.error(f"Failed to list dashboards: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dashboards/{design}/{pdk}", response_class=HTMLResponse)
async def get_dashboard(design: str, pdk: str):
    """
    Generate and return timing dashboard for a design.

    Args:
        design: Design name (e.g., "gcd", "aes", "ibex")
        pdk: PDK name (e.g., "sky130hd", "asap7")

    Returns:
        HTML dashboard with interactive Plotly charts

    Example:
        GET /dashboards/gcd/sky130hd
    """
    try:
        from ip_agent.report_visualizer import ReportVisualizer

        # Generate dashboard
        visualizer = ReportVisualizer(design, pdk)
        html_path = visualizer.generate_dashboard()

        # Read and return HTML
        html_content = html_path.read_text()

        logger.info(f"Served dashboard: {design}/{pdk}")

        return HTMLResponse(
            content=html_content,
            headers={
                "Cache-Control": "public, max-age=300",  # Cache for 5 minutes
                "X-Design": design,
                "X-PDK": pdk,
            }
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"No run data found for {design}/{pdk}. Run flows first."
        )
    except Exception as e:
        logger.error(f"Dashboard generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/dashboards/{design}/{pdk}/data", response_class=JSONResponse)
async def get_dashboard_data(design: str, pdk: str):
    """
    Get raw run data as JSON (for API access).

    Returns:
        JSON with all run metrics, summary, trends
    """
    try:
        from ip_agent.run_tracker import RunTracker

        tracker = RunTracker(design, pdk)
        runs = tracker.get_all_runs()

        if not runs:
            raise HTTPException(
                status_code=404,
                detail=f"No run data found for {design}/{pdk}"
            )

        summary = tracker.get_summary()

        return {
            "design": design,
            "pdk": pdk,
            "runs": [r.to_dict() for r in runs],
            "summary": summary,
            "trends": {
                "wns": tracker.get_trend("wns"),
                "violations": tracker.get_trend("violations"),
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboards/{design}/{pdk}/upload")
async def upload_to_s3(design: str, pdk: str):
    """
    Generate dashboard and upload to S3.

    Requires AWS credentials and S3 bucket configured.
    Returns S3 URL where dashboard is accessible.

    This endpoint is used by the CI/CD pipeline to publish dashboards.
    """
    try:
        import boto3
        import os
        from ip_agent.report_visualizer import ReportVisualizer

        # Generate dashboard
        visualizer = ReportVisualizer(design, pdk)
        html_path = visualizer.generate_dashboard()

        # Upload to S3
        s3_client = boto3.client('s3')
        bucket_name = os.getenv("DASHBOARD_S3_BUCKET", "ip-design-agent-dashboards-prod")
        s3_key = f"{design}_{pdk}_dashboard.html"

        s3_client.upload_file(
            str(html_path),
            bucket_name,
            s3_key,
            ExtraArgs={
                'ContentType': 'text/html',
                'CacheControl': 'public, max-age=300',
            }
        )

        # Get CloudFront URL
        cloudfront_domain = os.getenv("CLOUDFRONT_DOMAIN")
        if cloudfront_domain:
            dashboard_url = f"https://{cloudfront_domain}/{s3_key}"
        else:
            dashboard_url = f"https://{bucket_name}.s3.amazonaws.com/{s3_key}"

        logger.info(f"Uploaded dashboard to S3: {dashboard_url}")

        return {
            "success": True,
            "url": dashboard_url,
            "s3_bucket": bucket_name,
            "s3_key": s3_key,
        }

    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Flow Management Endpoints
# ---------------------------------------------------------------------------


class StageRequest(BaseModel):
    design: str = Field(default="gcd")
    pdk: str = Field(default="sky130hd")
    stage: str = Field(description="Stage: synth, floorplan, place, cts, route, finish")


class TclCommandRequest(BaseModel):
    design: str = Field(default="gcd")
    pdk: str = Field(default="sky130hd")
    command: str = Field(description="Tcl command to execute")


@app.post("/flow/run-stage")
async def run_stage(request: StageRequest):
    """Submit a single OpenROAD stage to the job queue."""
    try:
        from ip_agent.flow_manager import FlowManager
        fm = FlowManager(request.design, request.pdk)
        job_id = fm.submit_stage(request.stage)
        return {"job_id": job_id, "status": "pending", "stage": request.stage}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to submit stage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/flow/run-tcl")
async def run_tcl_command(request: TclCommandRequest):
    """Submit a Tcl command to the job queue."""
    try:
        from ip_agent.flow_manager import FlowManager
        fm = FlowManager(request.design, request.pdk)
        job_id = fm.submit_tcl_command(request.command)
        return {"job_id": job_id, "status": "pending"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to submit Tcl command: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/flow/status/{job_id}")
async def get_job_status(job_id: str):
    """Get job status and metrics."""
    from ip_agent.flow_manager import FlowManager
    fm = FlowManager()
    status = fm.get_status(job_id)
    metrics = fm.get_metrics(job_id) if status in ("complete", "failed") else None
    return {"job_id": job_id, "status": status, "metrics": metrics}


@app.get("/flow/logs/{job_id}")
async def get_job_logs(job_id: str, offset: int = 0):
    """Stream log output from byte offset."""
    from ip_agent.flow_manager import FlowManager
    fm = FlowManager()
    log_content, new_offset = fm.get_log_tail(job_id, offset)
    status = fm.get_status(job_id)
    return {"log": log_content, "offset": new_offset, "status": status}


@app.get("/flow/jobs")
async def list_flow_jobs(limit: int = 20):
    """List recent flow jobs."""
    from ip_agent.flow_manager import FlowManager
    fm = FlowManager()
    return {"jobs": fm.list_jobs(limit)}


@app.get("/flow/runner/status")
async def runner_status():
    """Return OpenROAD ECS runner status: running, starting, stopped, or unknown."""
    from ip_agent.flow_manager import check_runner_status
    return {"status": check_runner_status()}


@app.post("/flow/runner/start")
async def runner_start():
    """Scale OpenROAD ECS service to desiredCount=1."""
    from ip_agent.flow_manager import start_runner
    ok = start_runner()
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to start runner (no ECS access or not on AWS)")
    return {"started": True}


@app.post("/flow/runner/stop")
async def runner_stop():
    """Scale OpenROAD ECS service to desiredCount=0."""
    from ip_agent.flow_manager import stop_runner
    ok = stop_runner()
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to stop runner (no ECS access or not on AWS)")
    return {"stopped": True}


# ---------------------------------------------------------------------------
# Queue — time-slot access to the shared OpenROAD runner
# ---------------------------------------------------------------------------


class _QueueIdBody(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=128,
                            description="Anonymous UUID or email of the student")


@app.post("/queue/claim")
async def queue_claim(body: _QueueIdBody):
    """Take the runner slot if free, otherwise join the queue."""
    try:
        from ip_agent import queue_manager
        slot = queue_manager.claim_slot(body.identifier)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"queue error: {exc}") from exc
    return slot.to_json()


@app.post("/queue/release")
async def queue_release(body: _QueueIdBody):
    """Leave the queue or end the active slot early."""
    try:
        from ip_agent import queue_manager
        removed = queue_manager.release_slot(body.identifier)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"queue error: {exc}") from exc
    return {"removed": removed}


@app.get("/queue/state/{identifier}")
async def queue_state(identifier: str):
    """Return queue view for one student: status, position, ETA, seconds_remaining."""
    if not identifier or len(identifier) > 128:
        raise HTTPException(status_code=400, detail="Invalid identifier")
    try:
        from ip_agent import queue_manager
        view = queue_manager.state_for(identifier)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"queue error: {exc}") from exc
    return view.to_json()


@app.post("/queue/cleanup")
async def queue_cleanup():
    """Force expire-and-promote cycle. Usually called by a background task."""
    try:
        from ip_agent import queue_manager
        removed = queue_manager.cleanup_expired()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"queue error: {exc}") from exc
    return {"expired": removed}


@app.get("/flow/terminal", response_class=HTMLResponse)
async def flow_terminal(design: str = "gcd", pdk: str = "sky130hd"):
    """
    Browser-based interactive terminal for OpenROAD Tcl commands.

    Renders an xterm.js terminal. Commands are submitted via /flow/run-tcl
    and results are polled from /flow/status/{job_id} + /flow/logs/{job_id}.
    """
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenROAD Terminal — {design} / {pdk}</title>
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d1117; font-family: monospace; height: 100vh; display: flex; flex-direction: column; }}
  #header {{
    background: #161b22; border-bottom: 1px solid #30363d;
    padding: 10px 16px; display: flex; align-items: center; gap: 12px;
  }}
  #header h2 {{ color: #e6edf3; font-size: 14px; font-weight: 600; }}
  #header .chip {{
    background: #1f2937; color: #8b949e; border: 1px solid #30363d;
    border-radius: 12px; padding: 3px 10px; font-size: 12px;
  }}
  #status-chip {{
    border-radius: 12px; padding: 3px 10px; font-size: 12px; border: 1px solid transparent;
  }}
  #terminal-wrap {{ flex: 1; padding: 8px; overflow: hidden; }}
  #terminal {{ height: 100%; }}
</style>
</head>
<body>
<div id="header">
  <h2>OpenROAD Terminal</h2>
  <span class="chip">{design}</span>
  <span class="chip">{pdk}</span>
  <span id="status-chip" style="background:#1f2937;color:#8b949e;border-color:#30363d;">
    checking...
  </span>
  <span style="color:#8b949e;font-size:11px;margin-left:auto">
    Allowed: report_checks, report_timing, size_cell, insert_buffer, ...
  </span>
</div>
<div id="terminal-wrap">
  <div id="terminal"></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js"></script>
<script>
const DESIGN = "{design}";
const PDK = "{pdk}";
const BASE = window.location.origin;

const term = new Terminal({{
  theme: {{
    background: '#0d1117', foreground: '#e6edf3',
    cursor: '#58a6ff', selection: 'rgba(88,166,255,0.3)',
    green: '#3fb950', red: '#f85149', yellow: '#d29922',
    cyan: '#39c5cf',
  }},
  fontFamily: "'Cascadia Code', 'Fira Code', 'Courier New', monospace",
  fontSize: 13,
  lineHeight: 1.4,
  cursorBlink: true,
  allowTransparency: true,
}});

const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.open(document.getElementById('terminal'));
fitAddon.fit();
window.addEventListener('resize', () => fitAddon.fit());

let inputBuffer = '';
let history = [];
let histIdx = -1;
let busy = false;

const PROMPT = '\\x1b[36mopenroad\\x1b[0m\\x1b[90m>\\x1b[0m ';

function writePrompt() {{
  term.write('\\r\\n' + PROMPT);
  inputBuffer = '';
}}

function setStatus(text, color) {{
  const chip = document.getElementById('status-chip');
  chip.textContent = text;
  chip.style.color = color;
  chip.style.borderColor = color + '44';
  chip.style.background = color + '11';
}}

async function checkRunnerStatus() {{
  try {{
    const r = await fetch(BASE + '/flow/runner/status');
    const d = await r.json();
    if (d.status === 'running') setStatus('🟢 Runner running', '#3fb950');
    else if (d.status === 'starting') setStatus('🟡 Runner starting', '#d29922');
    else if (d.status === 'stopped') setStatus('🔴 Runner stopped', '#f85149');
    else setStatus('⚪ Status unknown', '#8b949e');
  }} catch (e) {{
    setStatus('⚪ Status unknown', '#8b949e');
  }}
}}

async function runCommand(cmd) {{
  if (!cmd.trim()) {{ writePrompt(); return; }}
  busy = true;
  history.unshift(cmd);
  histIdx = -1;

  term.write('\\x1b[90m  → submitting...\\x1b[0m');

  let job_id;
  try {{
    const r = await fetch(BASE + '/flow/run-tcl', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ design: DESIGN, pdk: PDK, command: cmd }}),
    }});
    if (!r.ok) {{
      const err = await r.json();
      term.write('\\r\\n\\x1b[31mError: ' + (err.detail || 'request failed') + '\\x1b[0m');
      writePrompt(); busy = false; return;
    }}
    const d = await r.json();
    job_id = d.job_id;
  }} catch (e) {{
    term.write('\\r\\n\\x1b[31mNetwork error: ' + e.message + '\\x1b[0m');
    writePrompt(); busy = false; return;
  }}

  // Poll for completion
  let offset = 0;
  let dots = 0;
  term.write('\\r\\x1b[2K\\x1b[90m  ⏳ waiting for runner');
  const poll = setInterval(async () => {{
    try {{
      const lr = await fetch(BASE + '/flow/logs/' + job_id + '?offset=' + offset);
      const ld = await lr.json();

      if (ld.log) {{
        if (dots === 0) term.write('\\r\\x1b[2K');
        ld.log.split('\\n').forEach(line => {{
          if (line) term.write('\\r\\n  ' + line.replace(/\\x1b/g, '\\x1b'));
        }});
        offset = ld.offset;
        dots = 0;
      }} else {{
        dots++;
        term.write('.');
      }}

      if (ld.status === 'complete') {{
        clearInterval(poll);
        term.write('\\r\\n\\x1b[32m  ✓ done\\x1b[0m');
        writePrompt(); busy = false;
      }} else if (ld.status === 'failed') {{
        clearInterval(poll);
        term.write('\\r\\n\\x1b[31m  ✗ failed\\x1b[0m');
        writePrompt(); busy = false;
      }}
    }} catch (e) {{
      dots++;
      term.write('.');
    }}
  }}, 600);

  // Safety timeout 5 minutes
  setTimeout(() => {{
    clearInterval(poll);
    if (busy) {{ term.write('\\r\\n\\x1b[33m  timeout\\x1b[0m'); writePrompt(); busy = false; }}
  }}, 300000);
}}

term.onKey(e => {{
  const {{ key, domEvent }} = e;
  const code = domEvent.keyCode;

  if (busy) return;

  if (code === 13) {{ // Enter
    term.write('\\r\\n');
    runCommand(inputBuffer.trim());
  }} else if (code === 8) {{ // Backspace
    if (inputBuffer.length > 0) {{
      inputBuffer = inputBuffer.slice(0, -1);
      term.write('\\b \\b');
    }}
  }} else if (code === 38) {{ // Up arrow
    if (history.length > 0) {{
      histIdx = Math.min(histIdx + 1, history.length - 1);
      const h = history[histIdx];
      term.write('\\r' + PROMPT + h + ' '.repeat(Math.max(0, inputBuffer.length - h.length)));
      term.write('\\r' + PROMPT + h);
      inputBuffer = h;
    }}
  }} else if (code === 40) {{ // Down arrow
    histIdx = Math.max(histIdx - 1, -1);
    const h = histIdx >= 0 ? history[histIdx] : '';
    term.write('\\r' + PROMPT + h + ' '.repeat(Math.max(0, inputBuffer.length - h.length)));
    term.write('\\r' + PROMPT + h);
    inputBuffer = h;
  }} else if (code === 67 && domEvent.ctrlKey) {{ // Ctrl+C
    inputBuffer = '';
    term.write('^C');
    writePrompt();
  }} else if (key.length === 1) {{
    inputBuffer += key;
    term.write(key);
  }}
}});

// Startup banner
term.write('\\x1b[1;36m  OpenROAD Interactive Terminal\\x1b[0m\\r\\n');
term.write('\\x1b[90m  Design: {design}  PDK: {pdk}\\x1b[0m\\r\\n');
term.write('\\x1b[90m  Commands are executed in the OpenROAD container via the job queue.\\x1b[0m\\r\\n');
term.write('\\x1b[90m  Type a command and press Enter. Use ↑/↓ for history.\\x1b[0m\\r\\n');
writePrompt();

checkRunnerStatus();
setInterval(checkRunnerStatus, 10000);
</script>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/flow/dashboard/{design}/{pdk}", response_class=HTMLResponse)
async def flow_progress_dashboard(design: str, pdk: str):
    """
    Flow progress dashboard — per-stage stats sheet.

    Shows all 6 stages (Synth→Floorplan→Place→CTS→Route→Finish) with status,
    runtime, WNS, DRC, area. Auto-refreshes every 10s.
    """
    try:
        from ip_agent.flow_dashboard import generate_flow_dashboard
        from ip_agent.config import SHARED_DATA_PATH
        shared_dir = Path(SHARED_DATA_PATH)
        html = generate_flow_dashboard(design, pdk, shared_dir)
        return HTMLResponse(html)
    except Exception as e:
        logger.error(f"Flow dashboard failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/flow/report/{job_id}", response_class=HTMLResponse)
async def get_flow_report(job_id: str):
    """
    Serve generated stage HTML report.

    Reports are written to /shared/reports/ by the Streamlit UI after
    a stage completes. If no pre-generated report exists, generate one
    on the fly from the job's output.log.
    """
    from ip_agent.config import SHARED_DATA_PATH

    shared_reports = Path(SHARED_DATA_PATH) / "reports"
    shared_reports.mkdir(parents=True, exist_ok=True)

    for f in shared_reports.glob(f"*{job_id}*_report.html"):
        return HTMLResponse(
            content=f.read_text(),
            headers={"Cache-Control": "public, max-age=3600"},
        )

    for f in sorted(shared_reports.glob("*_report.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        if job_id in f.name:
            return HTMLResponse(
                content=f.read_text(),
                headers={"Cache-Control": "public, max-age=3600"},
            )

    from ip_agent.flow_manager import FlowManager
    fm = FlowManager()
    status = fm.get_status(job_id)
    if status != "complete":
        raise HTTPException(status_code=404, detail=f"Job {job_id} status is '{status}', not complete")

    full_log, _ = fm.get_log_tail(job_id, 0)
    if not full_log or len(full_log) < 100:
        raise HTTPException(status_code=404, detail=f"No log output for job {job_id}")

    try:
        import sys, importlib
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        grv = importlib.import_module("generate_report_viewer")

        run_info = grv.extract_run_info(full_log)
        if run_info["design"] == "unknown":
            run_info["design"] = "gcd"
            run_info["pdk"] = "sky130hd"

        html = grv.generate_html(
            run_info=run_info,
            stage_summary=grv.parse_stage_summary(full_log),
            design_areas=grv.parse_design_areas(full_log),
            cell_report=grv.parse_cell_report(full_log),
            ir_reports=grv.parse_ir_reports(full_log),
            drc_violations=grv.parse_drc_violations(full_log),
            antenna=grv.parse_antenna(full_log),
            placement_metrics=grv.parse_placement_metrics(full_log),
            cts_metrics=grv.parse_cts_metrics(full_log),
            routing_metrics=grv.parse_routing_metrics(full_log),
            setup_violations=grv.parse_setup_violations(full_log),
            metrics_json=grv.parse_metrics_json(full_log),
            full_log=full_log,
        )

        report_path = shared_reports / f"{job_id}_report.html"
        report_path.write_text(html)

        return HTMLResponse(
            content=html,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception as e:
        logger.error(f"Report generation failed for {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

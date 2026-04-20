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
app.mount("/mcp", mcp.sse_app())

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

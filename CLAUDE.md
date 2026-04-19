# CLAUDE.md — ip-design-agent

## What This Project Is

RAG + LangGraph agentic AI for semiconductor physical design and timing analysis.
Built as a demo project by **Gursimran Sodhi** targeting Synopsys AI engineering roles.

**Purpose:** Demonstrate production-grade AI applied to VLSI industry problems — not a
generic chatbot, but a domain-specific agent that understands timing closure, DRC, and
MCMM multi-corner analysis.

---

## Project Structure (37 files)

```
ip-design-agent/
├── .env.example                    # Template — copy to .env, fill in keys
├── .gitignore
├── pyproject.toml                  # Dependencies (Python 3.11+, hatch build)
├── Dockerfile                      # python:3.12-slim
├── docker-compose.yml              # 4 services: db, api, ui, mcp
├── app.py                          # Streamlit demo UI (port 8501)
├── demo_multi_agent.py             # 3-agent timing closure demo (interview showcase)
├── demo_timing_dashboard.py        # Timing dashboard demo with OpenROAD integration (NEW)
├── test_dashboard_standalone.py    # Standalone dashboard generator (NEW)
├── src/
│   ├── __init__.py
│   └── ip_agent/
│       ├── __init__.py
│       ├── config.py               # .env loading, all tuneable constants
│       ├── models.py               # Pydantic: TimingPath, TimingReport, AgentState, etc.
│       ├── router.py               # Deterministic routing (8 regex rules, priority-ordered)
│       ├── retriever.py            # Hybrid search: pgvector + BM25 + RRF
│       ├── tools.py                # 6 @tool functions for the LangGraph agent
│       ├── agent.py                # LangGraph StateGraph (5 nodes, conditional edges)
│       ├── ingest.py               # Ingestion: parse .rpt, load .md/.txt, embed, store
│       ├── etl.py                  # Production ETL: GitHub download, dedup, batch embed
│       ├── eda_bridge.py           # Whitelisted subprocess wrapper (OpenSTA/OpenROAD)
│       ├── openroad_tools.py       # Live OpenROAD flow execution (400 lines) (NEW)
│       ├── run_tracker.py          # Track timing metrics across ECO iterations (380 lines) (NEW)
│       ├── report_visualizer.py    # Generate HTML dashboards with Plotly (450 lines) (NEW)
│       ├── guardrails.py           # 3-layer validation (hallucination, domain, format)
│       ├── cost_router.py          # Model routing, semantic cache, token budget
│       ├── specialists.py          # 3 specialist agents: TimingAgent, DRCAgent, PhysicalAgent
│       ├── orchestrator.py         # Multi-agent LangGraph coordination
│       ├── mcp_server.py           # FastMCP server (4 tools + 1 resource)
│       ├── api.py                  # FastAPI: /query, /health, /dashboards, /a2a (UPDATED)
│       └── a2a_card.py             # Agent Card for A2A discovery
├── data/
│   ├── docs/
│   │   ├── opensta_commands.md     # OpenSTA command reference
│   │   └── openroad_flow.md        # OpenROAD flow documentation
│   ├── sample_reports/
│   │   ├── setup_report.rpt        # 3 paths (1 MET, 2 VIOLATED: -0.05ns, -0.14ns)
│   │   ├── drc_report.rpt          # 5 violations (1 CRITICAL, 3 ERROR, 1 WARNING)
│   │   └── cell_usage.rpt          # 462 cells, 7 on critical paths
│   └── runs/                       # JSON run tracking data (NEW)
│       └── gcd_sky130hd_runs.json  # Example: 3 ECO iterations
├── reports/                        # Generated dashboard HTML files (NEW)
│   └── sample_timing_dashboard.html
├── tests/
│   ├── __init__.py
│   ├── test_retriever.py           # TestDeterministicRouter (9 test cases)
│   ├── test_agent.py               # TestAgentGraph + TestAgentState
│   └── eval_ragas.py               # RAGAS evaluation (4 EDA test cases)
└── terraform/                      # AWS deployment (eu-west-1 Dublin)
    ├── main.tf, ecs.tf, rds.tf, secrets.tf, ecr.tf, cloudwatch.tf
    ├── s3_dashboards.tf            # S3 bucket for dashboard hosting (200 lines) (NEW)
    ├── cloudfront_dashboards.tf    # CDN distribution (150 lines) (NEW)
    ├── variables.tf, outputs.tf, deploy.sh
    └── (in ../ip-design-agent-terraform/ until consolidated)
```

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Agent framework | LangGraph (StateGraph) | Graph-based, production-standard, maps to hardware background |
| RAG pipeline | LangChain | Document loading, text splitting, tool binding |
| Vector DB | pgvector (PostgreSQL) | Reuses existing Postgres knowledge from Supabase |
| Embeddings | OpenAI text-embedding-3-small | 1536 dimensions, cost-effective |
| LLM | GPT-4o-mini (simple) / GPT-4o (complex) | Cost routing selects per query |
| Keyword search | BM25Retriever | Exact match for EDA commands like set_input_delay |
| Fusion | EnsembleRetriever (RRF) | Merges vector + keyword ranked lists |
| MCP | FastMCP | Expose tools to Claude Desktop / Cursor |
| API | FastAPI | REST + A2A endpoints |
| UI | Streamlit | Chat interface with sidebar |
| Visualization | Plotly | Interactive timing dashboard charts |
| EDA Tools | OpenROAD-flow-scripts | Live flow execution with sky130 PDK |
| Containers | Docker + docker-compose | 4 services (db, api, ui, mcp) |
| Cloud (App) | Terraform → AWS ECS Fargate + RDS | Dublin region (eu-west-1) |
| Cloud (Dashboards) | Terraform → AWS S3 + CloudFront | ~$1/month static hosting |

---

## Architecture — Query Flow

```
Query → [Deterministic Router] → regex match? → direct route
              ↓ no match
        [Cost Router] → select gpt-4o-mini or gpt-4o
              ↓
        [LangGraph Agent + 6 Tools] → hybrid search (pgvector + BM25)
              ↓
        [Guardrails] → pass? → return answer
                     → fail? → retry once with feedback
```

### LangGraph Nodes
1. **router** — `deterministic_router_node()`: 8 regex rules, priority 50-100
2. **model_selector** — `model_selector_node()`: cheap vs standard model
3. **agent** — `agent_node()`: LLM with 6 bound tools
4. **tools** — `ToolNode(ALL_TOOLS)`: executes tool calls
5. **guardrails** — `guardrail_node()`: validates response

### Multi-Agent Orchestration (demo_multi_agent.py)
```
timing_analysis → drc_check → physical_fix → merge → END
```
- **TimingAgent** (specialists.py) — parses .rpt, finds violations, WNS/TNS
- **DRCAgent** (specialists.py) — parses DRC report, maps congested regions
- **PhysicalAgent** (specialists.py) — generates ECO fixes (DRC-aware)
- Context flows between agents: DRC congestion → Physical uses conservative sizing

---

## Key Design Decisions

1. **Hybrid search, not pure vector** — EDA queries mix natural language ("how to fix timing")
   with exact keywords ("set_input_delay"). BM25 catches exact matches that vector search misses.

2. **Deterministic router fires BEFORE LLM** — "report_checks" MUST route to OpenSTA docs.
   Regex rules are 100% reliable, zero cost, auditable. LLM fallback only for ambiguous queries.

3. **3 specialist agents, not 1 generalist** — mirrors real EDA: PrimeTime (timing) +
   ICV/Calibre (DRC) + ICC2 (physical) must coordinate. The key insight: Physical Agent
   receives DRC context BEFORE generating fixes.

4. **pgvector over Pinecone/Chroma** — reuses Postgres knowledge, single database for
   both vector search and metadata queries.

5. **EDA bridge uses whitelisted commands** — no arbitrary shell execution. Only
   ALLOWED_OPENSTA_COMMANDS and ALLOWED_OPENROAD_COMMANDS can run.

6. **Live OpenROAD integration via MCP tools** — openroad_tools.py wraps OpenROAD-flow-scripts
   with MCP @tool decorators. Agent can execute real flows (synthesis → place → route → STA)
   with sky130 PDK, not just parse dummy reports. Demonstrates EDA tool integration.

7. **Timing dashboard visualization** — run_tracker.py stores metrics across ECO iterations in
   JSON. report_visualizer.py generates interactive HTML with Plotly charts tracking WNS,
   violations, DRC, area. Shows improvement trends visually (e.g., -0.52ns → +0.08ns).

8. **AWS S3+CloudFront for dashboards** — separate from main app deployment. Static HTML files
   hosted on S3, served via CloudFront CDN in Dublin region (~$1/month). Live URLs can be
   shared during interviews: "Here's the dashboard: https://d123.cloudfront.net/..."

---

## Running the Project

### Local Development
```bash
# 1. Environment
cd ~/Documents/JobhuntAI/ip-design-agent
cp .env.example .env  # Fill in OPENAI_API_KEY, DATABASE_URL

# 2. Install
uv venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Database
createdb ip_design_db
psql ip_design_db -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 4. Ingest sample data
python -m ip_agent.ingest

# 5. Run
streamlit run app.py              # UI at localhost:8501
uvicorn ip_agent.api:app          # API at localhost:8001
python demo_multi_agent.py        # 3-agent timing closure demo
python demo_timing_dashboard.py --quick  # Generate timing dashboard (sample data)
python test_dashboard_standalone.py      # Standalone dashboard demo

# 6. Test
pytest tests/ -v
```

### Docker
```bash
docker compose up -d
# UI: http://localhost:8501
# API: http://localhost:8001
# Health: http://localhost:8001/health
# A2A: http://localhost:8001/.well-known/agent.json
```

### Terraform (AWS)
```bash
# Main app deployment (ECS + RDS)
cd terraform/
terraform init && terraform plan    # Preview
terraform apply                     # Deploy to eu-west-1

# Dashboard deployment (S3 + CloudFront) - separate, ~$1/month
terraform apply \
  -target=aws_s3_bucket.dashboards \
  -target=aws_cloudfront_distribution.dashboards
terraform output dashboard_url      # Get live URL
```

---

## Environment Variables (.env)

```
OPENAI_API_KEY=sk-...              # Required
DATABASE_URL=postgresql+psycopg://ondevtratech@localhost:5432/ip_design_db  # Required (note: +psycopg driver prefix)
LANGCHAIN_API_KEY=lsv2_...         # Optional (LangSmith tracing)
LANGCHAIN_TRACING_V2=true          # Optional
LANGCHAIN_PROJECT=ip-design-agent  # Optional
```

---

## Known Issues & Fixes Applied

### 1. langchain-postgres v0.0.17 SQLAlchemy metadata conflict (FIXED)

**Error:** `Table 'langchain_pg_collection' is already defined for this MetaData instance`

**Root cause:** `langchain_postgres.vectorstores` defines `Base = declarative_base()` at module
level and re-registers `CollectionStore`/`EmbeddingStore` table classes each time
`_get_embedding_collection_store()` is called from different modules. When multiple files
import `PGVector` (retriever.py, ingest.py, etl.py), SQLAlchemy throws because the same
table name is registered twice against the same `Base.metadata`.

**Fix:** `src/ip_agent/_db.py` pre-calls `_get_embedding_collection_store()` at import time
to populate its internal `_classes` cache before any other module imports `PGVector`.
This prevents the function from re-defining ORM classes on subsequent calls. `__init__.py`
imports `_db` first to ensure the pre-call happens. All modules use the shared
`get_vector_store()` singleton from `_db.py` instead of creating their own `PGVector` instances.

**Evolution:** Initially tried monkey-patching `sqlalchemy.Table.__init__` with
`extend_existing=True`, but the error actually originates in `Table.__new__` → `Table._new`.
Even patching `_new` only revealed a deeper issue: duplicate declarative class registration
causing `Multiple classes found for path "EmbeddingStore"`. The final fix is simpler and
more robust: pre-call the caching function so classes are only created once.

**Do NOT:**
- Remove the `_db.py` pre-call — it prevents the conflict
- Remove the `import ip_agent._db` line from `__init__.py`
- Create `PGVector()` directly in any module — always use `get_vector_store()`
- Use `uvicorn --reload` in development (triggers extra re-imports that worsen the issue)

### 2. Shell env overrides .env file (FIXED)

**Error:** `openai.AuthenticationError: Error code: 401 - Incorrect API key`

**Root cause:** `load_dotenv()` does NOT override existing environment variables. If
`OPENAI_API_KEY` is already set in the shell (e.g. from `.zshrc` or another project),
the `.env` file value is silently ignored.

**Fix:** Changed `config.py` to use `load_dotenv(override=True)` so `.env` always wins.

### 3. DRC violations mixed with timing violations (FIXED)

**Error:** Asking "what are the timing violations?" returned DRC results (Metal spacing,
Via enclosure, Metal short) mixed with actual timing data.

**Root cause:** `ingest.py` tagged ALL `.rpt` files as `source_type: "timing_report"`
regardless of content. DRC and cell usage reports got the same type tag.

**Fix:** Added `_classify_report()` function in `ingest.py` that classifies `.rpt` files as
`timing_report`, `drc_report`, or `cell_report` based on filename patterns and content
inspection. After code change, must re-ingest: `psql ip_design_db -c "DELETE FROM
langchain_pg_embedding;" && python -m ip_agent.ingest`.

### 4. Timing violations not detected in tool output (FIXED)

**Error:** `analyze_timing_violations` tool returned "No violations found" even though the
database contained VIOLATED paths with slack -0.05ns and -0.14ns.

**Root cause:** The tool checked for `"violation" in doc.page_content.lower()` but the
actual report content says `"VIOLATED"` (past tense). The substring "violation" is NOT
present in "violated".

**Fix:** Updated the check in `tools.py` to look for `"violated"`, `"violation"`,
`"negative"`, AND negative slack values (`"-0."`) in the content.

### 5. api.py SQLAlchemy patch not loading (FIXED)

**Error:** Running `uvicorn ip_agent.api:app` failed with the metadata conflict error
even though `__init__.py` imports `_db.py`.

**Root cause:** When uvicorn loads `ip_agent.api` as a module path, the `__init__.py`
patch may not run early enough depending on Python's import resolution order.

**Fix:** Added explicit `import ip_agent._db` at the top of `api.py` to ensure the
patch runs before any other imports in the API module.

### 6. Deprecated langchain imports (FIXED)

`langchain.schema` moved to `langchain_core.documents` and `EnsembleRetriever` moved to
`langchain_classic.retrievers` in newer LangChain versions. All imports updated.

### 7. pgvector extension for PostgreSQL 16 (FIXED)

Homebrew's `pgvector` bottle targets pg17/pg18 only. Must compile from source:
```bash
cd /tmp && git clone --branch v0.8.2 https://github.com/pgvector/pgvector.git
cd pgvector && make PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config
make install PG_CONFIG=/opt/homebrew/opt/postgresql@16/bin/pg_config
```

### 8. FastMCP constructor API change (FIXED)

**Error:** `TypeError: FastMCP.__init__() got an unexpected keyword argument 'description'`

**Root cause:** `mcp[cli]>=1.0.0` changed `FastMCP.__init__` — the `description` parameter
was renamed to `instructions`.

**Fix:** Changed `mcp_server.py` from `description=...` to `instructions=...`.

### 9. Streamlit async + uvloop incompatibility (FIXED)

**Error:** `ValueError: Can't patch loop of type <class 'uvloop.Loop'>`

**Root cause:** Streamlit uses uvloop internally. `nest_asyncio` cannot patch uvloop.

**Fix:** Removed `nest_asyncio`. Instead, run async coroutines in a `ThreadPoolExecutor`
thread with its own `asyncio.run()`:
```python
def run_async(coro):
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()
```

---

## Testing Guide — How to Verify Everything Works

### Quick Smoke Test (2 minutes)
```bash
source .venv/bin/activate

# 1. Unit tests (14 tests — router, agent graph, state model)
pytest tests/ -v

# 2. Start API server
uvicorn ip_agent.api:app --host 0.0.0.0 --port 8001 &

# 3. Health check
curl http://localhost:8001/health

# 4. Start Streamlit UI
streamlit run app.py --server.port 8501 &
open http://localhost:8501
```

### FastAPI Endpoint Tests
```bash
# Health check — verifies database, agent, embeddings are OK
curl -s http://localhost:8001/health | python3 -m json.tool
# Expected: {"status": "healthy", "components": {"agent": "ok", "database": "ok", "embeddings": "ok"}}

# Query endpoint — real LLM call, costs ~$0.001
curl -s -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the timing violations?"}' | python3 -m json.tool
# Expected: {"answer": "...", "model_used": "gpt-4o-mini", "guardrail_score": 1.0, ...}

# Query with chat history
curl -s -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I fix them?", "chat_history": [{"role": "user", "content": "What are the timing violations?"}, {"role": "assistant", "content": "Found 2 setup violations..."}]}'
```

### A2A Protocol Tests (Agent-to-Agent)
```bash
# Discovery — other agents find your capabilities via well-known URL
curl -s http://localhost:8001/.well-known/agent.json | python3 -m json.tool
# Expected: AgentCard with name, skills (search, analyze, suggest, explain), capabilities

# Task delegation — another agent sends you a task
curl -s -X POST http://localhost:8001/a2a \
  -H "Content-Type: application/json" \
  -d '{"id": "test-1", "message": {"role": "user", "parts": [{"type": "text", "text": "Explain WNS and TNS"}]}}' | python3 -m json.tool
# Expected: {"id": "test-1", "status": "completed", "result": {"parts": [{"type": "text", "text": "..."}]}}
```

### MCP Server Tests (Model Context Protocol)
```bash
# Verify MCP server imports and registers tools
python -c "
from ip_agent.mcp_server import mcp
print(f'Server: {mcp.name}')
for name in mcp._tool_manager._tools:
    print(f'  Tool: {name}')
"
# Expected: 4 tools: search_eda_docs, search_timing_data, get_fix_suggestion, explain_concept

# Run MCP server (stdio mode — for Claude Desktop / Cursor integration)
python -m ip_agent.mcp_server

# Configure in Claude Desktop (~/.config/claude/claude_desktop_config.json):
# {
#   "mcpServers": {
#     "ip-design-agent": {
#       "command": "python",
#       "args": ["-m", "ip_agent.mcp_server"],
#       "cwd": "/path/to/ip-design-agent",
#       "env": {"OPENAI_API_KEY": "sk-..."}
#     }
#   }
# }
```

### Multi-Agent Timing Closure Demo
```bash
# Full 3-agent orchestrator (Timing → DRC → Physical → Merge)
python demo_multi_agent.py
# Expected output:
#   - TimingAgent finds 2 violations (WNS: -0.140ns, TNS: -0.190ns)
#   - DRCAgent finds 5 violations (1 CRITICAL, 3 ERROR, 1 WARNING), congested=True
#   - PhysicalAgent generates 7 ECO commands (conservative sizing due to DRC)
#   - fix_timing.tcl script with size_cell commands
```

### Streamlit UI Tests
```bash
streamlit run app.py --server.port 8501
open http://localhost:8501
```
**Chat tab:** Type "What are the timing violations?" — see answer + collapsible execution trace
**Timing Closure tab:**
1. Select a block from the dropdown (15 sample blocks: block_alu, block_fpu, block_pcie_phy, etc.)
2. Click "Run Timing Closure" to see step-by-step agent execution
3. See before/after comparison with cell-level changes
4. Download the ECO Tcl script

### Docker Tests
```bash
docker compose up -d
curl http://localhost:8001/health                    # FastAPI
curl http://localhost:8001/.well-known/agent.json    # A2A discovery
curl -X POST http://localhost:8001/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How do I fix setup violations?"}'
open http://localhost:8501                           # Streamlit UI
docker compose down
```

---

## Build Guide Completion Status

All 12 days from `build_guide.html` are **COMPLETE**:

| Day | Topic | Status | Verified |
|-----|-------|--------|----------|
| 1 | Environment Setup | DONE | .venv, pyproject.toml, .env, PostgreSQL 16 + pgvector |
| 2 | config.py + models.py + router.py | DONE | 8 regex rules, 14 tests pass |
| 3 | retriever.py — Hybrid Search | DONE | pgvector + BM25 + RRF working |
| 4-5 | ingest.py + etl.py — Ingestion | DONE | 41 chunks ingested (14 docs + 27 reports) |
| 6-7 | tools.py + agent.py — LangGraph Agent | DONE | 6 tools, 5 nodes, conditional edges |
| 8 | MCP Server + A2A + FastAPI | DONE | 4 MCP tools, /a2a endpoint, /query, /health |
| 9 | Streamlit UI + EDA Bridge | DONE | 2-tab UI (Chat + Timing Closure), eda_bridge.py |
| 10 | Guardrails + Cost Router + Orchestrator | DONE | 3-layer guardrails, cost routing, 3-agent orchestrator |
| 11 | Tests + RAGAS Evaluation | DONE | 14 tests passing, eval_ragas.py ready |
| 12 | Docker + Deploy + GitHub | DONE | Docker build OK, pushed to github.com/guris12/ipdesignagentEDA |

### Verified Test Results (April 19, 2026)
- **pytest:** 14/14 tests passing
- **FastAPI /health:** `{"status": "healthy", "components": {"agent": "ok", "database": "ok", "embeddings": "ok"}}`
- **FastAPI /query:** Returns timing violation analysis with guardrail_score 1.0
- **A2A /.well-known/agent.json:** Returns AgentCard with 4 skills
- **A2A /a2a task:** Returns completed task with WNS/TNS explanation
- **MCP server:** 4 tools registered (search_eda_docs, search_timing_data, get_fix_suggestion, explain_concept)
- **demo_multi_agent.py:** 7 ECO commands generated (DRC-aware conservative sizing)
- **Streamlit UI:** Chat tab + Timing Closure tab with before/after comparison

---

## Key Files to Understand

**Start here when resuming work:**
- `agent.py` — the core LangGraph pipeline (5 nodes, conditional edges)
- `specialists.py` — 3 specialist agents (the interview differentiator)
- `orchestrator.py` — multi-agent coordination via LangGraph StateGraph
- `retriever.py` — hybrid search (pgvector + BM25 + RRF)
- `tools.py` — 6 @tool functions the agent can invoke

**OpenROAD integration & dashboards (NEW):**
- `openroad_tools.py` — MCP tools for live OpenROAD flow execution (400 lines)
- `run_tracker.py` — Track timing metrics across ECO iterations (380 lines)
- `report_visualizer.py` — Generate HTML dashboards with Plotly (450 lines)
- `demo_timing_dashboard.py` — End-to-end timing closure workflow demo (350 lines)
- `test_dashboard_standalone.py` — Standalone dashboard generator (290 lines)

**Production patterns:**
- `guardrails.py` — 3-layer validation (895 lines)
- `cost_router.py` — model routing + semantic cache + token budget (1,096 lines)
- `etl.py` — production ETL with GitHub download, dedup, batch processing

**Integration layer:**
- `api.py` — FastAPI with /query, /health, /dashboards, A2A endpoints
- `mcp_server.py` — FastMCP with 4 tools exposed to Claude Desktop/Cursor
- `eda_bridge.py` — safe subprocess wrapper for OpenSTA/OpenROAD

**AWS deployment (Terraform):**
- `terraform/s3_dashboards.tf` — S3 bucket for dashboard hosting (200 lines)
- `terraform/cloudfront_dashboards.tf` — CDN distribution (150 lines)

---

## The VLSI Problem This Solves

**Pain point:** Engineers have Tcl scripts for automated ECO, but those scripts are blind —
they see one corner, one domain at a time. A fix in ss corner breaks hold in ff corner.
A buffer insertion causes DRC violations in congested regions. Engineers discover this after
12-hour STA re-runs.

**What the agent does:** Indexes ALL corner reports + DRC results into pgvector. Three
specialist agents share context before generating any ECO. The Physical Agent won't insert
a buffer if the DRC Agent says the region is congested. It won't aggressively upsize if
cross-corner data shows tight hold margin.

**Result:** ECO that's safe across all corners from the start. Iterations drop from 5-10
down to 2-3. The 2-8 hours of human analysis between STA runs → 30 seconds.

---

## What NOT to Do

- Do NOT suggest CrewAI/AutoGen — LangGraph was chosen deliberately (graph-based, production)
- Do NOT suggest Kubernetes — ECS Fargate is sufficient for this scale
- Do NOT suggest fine-tuning LLMs — RAG + tools is the right pattern here
- Do NOT suggest Pinecone/Chroma — pgvector reuses existing Postgres expertise
- Do NOT apply for the Synopsys role before the demo is on GitHub
- Do NOT build the MCMM Timing Closure Agent (v2) before core phases are complete
- Do NOT add inline styles to HTML documentation — use styles.css

---

## Phase 2 — Live OpenROAD + AI Training Platform on AWS

**Status:** PLANNED — build when invited for interview, or before May 6 apply date
**Estimated effort:** 8-12 hours
**Monthly AWS cost:** ~$15-25/month (small instances, sufficient for demo designs)

### The Vision — Not Just a Demo, a Training Platform

This isn't just "run a flow and analyze" — it's an **interactive EDA training platform**
where users learn physical design by doing:

1. **Run a real P&R flow** on a sample design (GCD, RISC-V core) with sky130 PDK
2. **See real violations** — the AI agent explains what each violation means and why
3. **Learn to fix them** — agent walks the user through ECO strategies step by step
4. **Apply the fix** — ECO Tcl script fed back, re-run, see WNS improve
5. **Track progress** — dashboard shows timing convergence across iterations

**Target users:**
- New PD engineers learning timing closure (onboarding tool)
- University students studying VLSI (educational platform)
- Synopsys customers learning OpenROAD/OpenSTA (training product)
- Interview demo showing Gursimran can build AI + EDA products

This reframes the project from "portfolio demo" → "product prototype" — exactly what
a Principal AI Flow Development Engineer should be thinking about.

### Architecture

```
┌──────────────────────────────────┐       ┌──────────────────────────────────┐
│  ECS Task 1: OpenROAD Runner     │       │  ECS Task 2: ip-design-agent     │
│                                  │       │                                  │
│  - OpenROAD-flow-scripts         │  EFS  │  - FastAPI + Streamlit           │
│  - sky130 PDK                    │──────→│  - Reads .rpt from shared volume │
│  - Runs synthesis → P&R → STA    │volume │  - MCP tools ingest new reports  │
│  - Dumps .rpt to /data/reports/  │       │  - Agent analyzes + teaches      │
│  - Receives fix_timing.tcl back  │←──────│  - Generates ECO Tcl script      │
│                                  │       │  - Tracks learning progress      │
└──────────────────────────────────┘       └──────────────────────────────────┘
         ↑                                          ↑
    t4g.medium (2 vCPU, 4GB)                 t4g.small (2 vCPU, 2GB)
    Spot (~$0.013/hr)                        On-demand (~$0.017/hr)
```

**Why small instances are enough:**
- `gcd` design is ~400 cells — runs in ~5-7 min even on t4g.medium
- `ibex` (15K cells) takes ~20-25 min on t4g.medium — still fine for training
- Agent is lightweight (FastAPI + LLM API calls) — t4g.small is plenty
- This is training, not production tapeout — users expect to wait a few minutes

### Training Platform Features

**Guided Learning Mode (Streamlit UI):**
```
┌─────────────────────────────────────────────────────────┐
│  🎓 EDA Training Platform                               │
│                                                         │
│  Lesson 1: Understanding Timing Reports                 │
│  ┌───────────────────────────────────────────────────┐  │
│  │ ▶ Run OpenROAD flow on GCD design (sky130 PDK)   │  │
│  │   [Run Flow]  Design: [gcd ▼]  PDK: [sky130hd ▼] │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  Step 1/5: Flow complete! 3 timing paths generated.     │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 🤖 Agent: "I found 2 setup violations. Let me    │  │
│  │ explain what this means..."                       │  │
│  │                                                   │  │
│  │ Q: "What is slack and why is -0.14ns bad?"        │  │
│  │ A: "Slack = required time - arrival time. When    │  │
│  │ negative, data arrives AFTER the clock edge..."   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  Step 2/5: Let's fix the worst violation.               │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 🤖 Agent: "The worst path goes through FA_X1.    │  │
│  │ We can upsize it. But first, check DRC..."        │  │
│  │                                                   │  │
│  │ [Apply ECO]  [Skip to next lesson]  [Ask why]     │  │
│  └───────────────────────────────────────────────────┘  │
│                                                         │
│  📊 Your Progress: Lesson 1 ████████░░ 80%              │
│  WNS: -0.14ns → -0.02ns (after 2 ECO iterations)       │
└─────────────────────────────────────────────────────────┘
```

**Training Lessons (built-in curriculum):**

| Lesson | Topic | Design | What User Learns |
|--------|-------|--------|-----------------|
| 1 | Understanding Timing Reports | gcd | Read .rpt files, slack, WNS/TNS |
| 2 | Setup Violation Fixing | gcd | Cell upsizing, buffer insertion |
| 3 | DRC-Aware ECO | gcd | Why fixes can break DRC, congestion |
| 4 | Multi-Corner Analysis | gcd | Same path, different corners |
| 5 | Full Timing Closure | ibex | End-to-end on a real RISC-V core |

### AWS Infrastructure (Terraform)

```
eu-west-1 (Dublin)
├── VPC + Subnets (existing from Phase 1)
├── ECS Cluster
│   ├── Service: openroad-runner (Fargate Spot, t4g.medium)
│   │   └── Docker: openroad/flow-ubuntu22.04-builder + sky130
│   ├── Service: ip-design-agent (Fargate, t4g.small)
│   │   └── Docker: ip-design-agent (existing Dockerfile)
│   └── Service: streamlit-ui (Fargate, t4g.micro)
│       └── Docker: ip-design-agent (streamlit command)
├── RDS PostgreSQL 16 + pgvector (existing from Phase 1)
├── EFS (Elastic File System) — shared volume for .rpt files
│   └── /data/reports/ — OpenROAD writes, Agent reads
├── ALB (Application Load Balancer)
│   ├── api.yourdomain.com → ip-design-agent:8001
│   └── train.yourdomain.com → streamlit:8501
├── S3 + CloudFront (existing — dashboards + training progress)
└── CloudWatch — logs, metrics, alarms
```

### New Terraform Files Needed

```
terraform/
├── ... (existing 13 files)
├── efs.tf                    # EFS file system + mount targets + access points
├── ecs_openroad.tf           # OpenROAD runner ECS task + service (Fargate Spot)
├── ecr_openroad.tf           # ECR repo for OpenROAD Docker image
└── ecs_agent_updated.tf      # Update agent task to mount EFS volume
```

### Docker Images

**Image 1: OpenROAD Runner** (~3-4 GB)
```dockerfile
# Dockerfile.openroad
FROM openroad/flow-ubuntu22.04-builder:latest

# sky130 PDK is included in OpenROAD-flow-scripts
RUN git clone --depth 1 https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git /flow
WORKDIR /flow

# Pre-download sky130 PDK (avoids runtime download)
RUN make DESIGN_CONFIG=designs/sky130hd/gcd/config.mk synth || true

# Shared volume mount point
VOLUME /data/reports

# Entry point: run a design and dump reports
COPY run_flow.sh /run_flow.sh
RUN chmod +x /run_flow.sh
ENTRYPOINT ["/run_flow.sh"]
CMD ["gcd", "sky130hd"]
```

**run_flow.sh** (entry point script):
```bash
#!/bin/bash
DESIGN=${1:-gcd}
PDK=${2:-sky130hd}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=/data/reports/${DESIGN}_${PDK}_${TIMESTAMP}

echo "=== Running OpenROAD flow: ${DESIGN} / ${PDK} ==="
cd /flow

# Run full flow: synth → floorplan → place → CTS → route → STA
make DESIGN_CONFIG=designs/${PDK}/${DESIGN}/config.mk

# Copy reports to shared volume
mkdir -p ${OUTPUT_DIR}
cp -r results/${PDK}/${DESIGN}/base/*.rpt ${OUTPUT_DIR}/ 2>/dev/null || true
cp -r logs/${PDK}/${DESIGN}/base/*.log ${OUTPUT_DIR}/ 2>/dev/null || true

# Signal completion
echo "DONE" > ${OUTPUT_DIR}/.complete
echo "=== Reports written to ${OUTPUT_DIR} ==="
ls -la ${OUTPUT_DIR}/
```

**Image 2: ip-design-agent** (existing, needs EFS mount + production mode)
- Already have `Dockerfile` — just add EFS volume mount in ECS task definition
- Switch `eda_bridge.py` from `demo_mode=True` to `demo_mode=False`
- Add file watcher in `openroad_tools.py` to detect new `.rpt` files on EFS

### Sample Designs Available (OpenROAD-flow-scripts)

| Design | Cells | Runtime (t4g.medium) | Difficulty | Use Case |
|--------|-------|---------------------|------------|----------|
| `gcd` | ~400 | ~5-7 min | Beginner | Quick training (GCD algorithm) |
| `ibex` | ~15K | ~20-25 min | Intermediate | RISC-V core (impressive) |
| `aes_cipher` | ~20K | ~25-30 min | Intermediate | Crypto block |
| `jpeg` | ~40K | ~40-50 min | Advanced | Large design (show scale) |

**Recommended for training:** Start with `gcd` (fast feedback loop), graduate to `ibex`

### AWS Cost Estimate (Small Instances)

| Resource | Spec | $/hr | $/month (24/7) | Interview week |
|----------|------|------|----------------|----------------|
| OpenROAD Runner | t4g.medium Spot | ~$0.013 | ~$9 | ~$2 |
| ip-design-agent | t4g.small | ~$0.017 | ~$12 | ~$3 |
| Streamlit UI | t4g.micro | ~$0.008 | ~$6 | ~$1.50 |
| RDS PostgreSQL | db.t4g.micro | ~$0.016 | ~$12 | ~$3 |
| EFS | 1 GB | — | ~$0.30 | ~$0.10 |
| ALB | — | ~$0.023 | ~$16 | ~$4 |
| S3 + CloudFront | dashboards | — | ~$1 | ~$0.25 |
| **Total** | | | **~$56/month** | **~$14 for 1 week** |

**Compared to original plan:** $125/month → $56/month (55% savings).
Small instances are fine — GCD takes 5-7 min on t4g.medium, perfectly acceptable
for a training platform where users are learning between iterations.

### Implementation Steps (8-12 hours)

**Step 1: OpenROAD Docker Image (2 hours)**
- Write `Dockerfile.openroad` based on `openroad/flow-ubuntu22.04-builder`
- Write `run_flow.sh` entry point
- Test locally: `docker build -t openroad-runner -f Dockerfile.openroad .`
- Run: `docker run -v /tmp/reports:/data/reports openroad-runner gcd sky130hd`
- Verify `.rpt` files in `/tmp/reports/`

**Step 2: Wire Agent to Read Real Reports (2 hours)**
- Update `openroad_tools.py`: add `watch_reports_dir()` MCP tool
- Update `eda_bridge.py`: `demo_mode=False` reads from EFS path
- Update `ingest.py`: add `ingest_from_directory(path)` for live reports
- Test locally with reports from Step 1

**Step 3: Terraform — EFS + OpenROAD ECS (3 hours)**
- Write `efs.tf`: file system, mount targets, security group
- Write `ecs_openroad.tf`: task definition with EFS mount, Fargate Spot (t4g.medium)
- Write `ecr_openroad.tf`: ECR repo for OpenROAD image
- Update existing `ecs.tf`: add EFS mount to agent task (t4g.small)
- Add API endpoint: `POST /run-flow` triggers OpenROAD ECS task

**Step 4: Build + Push + Deploy (2 hours)**
- Push OpenROAD image to ECR
- Update agent image with EFS support
- `terraform apply`
- Verify both services running

**Step 5: End-to-End Test (1-2 hours)**
- Hit live URL: `https://api.yourdomain.com/health`
- Trigger flow: `POST /run-flow {"design": "gcd", "pdk": "sky130hd"}`
- Wait 5-7 minutes for OpenROAD to complete on t4g.medium
- Query agent: "What are the timing violations in the latest run?"
- Agent reads real `.rpt` from EFS, analyzes, returns real violations
- Run Timing Closure → get real ECO script
- Feed back → re-run → show improvement on dashboard

### What This Proves in Interview

| They See | What It Proves |
|----------|---------------|
| Real OpenROAD flow running on AWS | Can integrate with actual EDA tools |
| Real timing reports (not sample data) | Agent handles production data |
| ECO fed back → re-run → improvement | **Closed-loop automation** |
| Training mode with guided lessons | **Product thinking**, not just tech demo |
| sky130 PDK on RISC-V core | Knows open-source EDA ecosystem |
| Small instances, cost-optimized | Cost-conscious engineering |
| Terraform IaC, `terraform destroy` | Production deployment mindset |
| "Users can learn PD with this" | Sees AI as **enabler for humans**, not replacement |

### Live Demo Script (for interview)

```
"Let me show you the system running live on AWS — it's actually a training
platform for learning timing closure..."

1. Open https://train.yourdomain.com (Streamlit)
2. "I'll trigger a real OpenROAD flow on the GCD design with sky130 PDK"
   → Click "Run OpenROAD Flow" → show ECS task starting
3. "While that runs (~5 min on a small instance), let me show the training mode"
   → Walk through Lesson 1: "The agent explains what slack means..."
4. "Flow complete — now the user sees REAL violations, not textbook examples"
   → Chat: "Analyze the latest OpenROAD run"
   → Agent reads real .rpt from EFS, explains each violation
5. "The 3-agent orchestrator shows how a senior engineer would approach this"
   → Timing Closure tab → real ECO script with explanations
6. "Feed the ECO back → re-run → the user SEES timing improve"
   → Dashboard shows WNS improving across iterations
7. "A new PD engineer could use this on day 1 to learn the closure loop"
   → "And it costs $14/week to run — cheaper than any training course"
8. "All Terraform — reproducible, teardown in seconds"
```

### Future Training Platform Features (if productized)

- **User accounts** — track progress across sessions (Cognito + DynamoDB)
- **Leaderboard** — who closed timing in fewest iterations
- **Custom designs** — upload your own Verilog, run through the flow
- **Multi-corner training** — Lesson 4+ uses ss/ff/tt corners
- **Slack integration** — training bot in #new-engineers channel
- **LMS integration** — SCORM export for Synopsys internal training

### When to Build

- **NOW:** Plan documented — DONE
- **After interview invitation:** Build Steps 1-5 (8-12 hours)
- **2-3 days before interview:** Deploy to AWS, test live
- **After interview:** Keep running if productizing, else `terraform destroy`
- **Pitch to Synopsys:** "I built this as a training tool — imagine this for your customers"

---

## Related Files Outside This Directory

| Location | Contents |
|----------|----------|
| `~/Documents/JobhuntAI/CLAUDE.md` | Parent project CLAUDE.md with full context |
| `~/Documents/JobhuntAI/build_guide.html` | Step-by-step build guide (all code snippets) |
| `~/Documents/JobhuntAI/project_plan.html` | Architecture diagrams, phase cards, production flow |
| `~/Documents/JobhuntAI/mcp_a2a_guide.html` | MCP/A2A explanation with EDA analogies |
| `~/Documents/JobhuntAI/ip-design-agent-terraform/` | Terraform files (13 files including S3+CloudFront) |
| `~/Documents/JobhuntAI/ip-design-agent-code/` | guardrails.py + cost_router.py source |
| `~/Documents/JobhuntAI/DEPLOYMENT_COMPLETE_SUMMARY.md` | AWS deployment summary with dashboard details |
| `~/Documents/JobhuntAI/DASHBOARD_DEPLOYMENT.md` | Complete dashboard deployment guide (500 lines) |

---

## Who This Is For

**Gursimran Sodhi** — 18 years experience: 12 years semiconductor PD (Intel Dublin, NVIDIA,
AMD, PMC-Sierra) + 5+ years AI product development. Primary languages: TypeScript and Swift.
Python proficiency demonstrated via this project.

When explaining Python concepts, use Swift analogies:
- Pydantic = Codable
- f-strings = string interpolation
- list comprehensions = filter/map
- pathlib = Bundle URLs
- TypedDict = struct with protocol conformance
- async/await = Swift async/await (nearly identical)

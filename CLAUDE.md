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

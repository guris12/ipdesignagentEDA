# IP Design Intelligence Agent

RAG + LangGraph agentic AI for semiconductor physical design and timing analysis, built on OpenROAD/OpenSTA EDA tools.

## What It Does

An AI agent that indexes EDA documentation and timing reports into a vector database, then answers natural language questions about timing violations, DRC issues, and EDA tool usage with full source traceability.

**The VLSI problem it solves:** Engineers running ECO iterations see one corner, one domain at a time. A fix in one corner breaks hold in another. This agent indexes ALL corner reports + DRC results, and three specialist agents share context before generating any ECO recommendation.

### Key Features

- **Hybrid search** (pgvector + BM25 + Reciprocal Rank Fusion) — EDA queries mix natural language with exact command names
- **Deterministic routing** — 8 regex rules route queries before the LLM, ensuring "report_checks" always hits OpenSTA docs
- **Cost routing** — gpt-4o-mini for simple lookups, gpt-4o for complex analysis
- **3 specialist agents** — Timing, DRC, Physical — mirror real EDA tool separation (PrimeTime + Calibre + ICC2)
- **3-layer guardrails** — hallucination detection, EDA domain accuracy, output format validation
- **MCP server** — expose EDA search tools to Claude Desktop / Cursor
- **A2A protocol** — agent-to-agent discovery and task delegation
- **Live OpenROAD integration** — execute real flows with sky130 PDK via MCP tools
- **Interactive timing dashboards** — track WNS, violations, DRC across ECO iterations with Plotly

## Architecture

```
Query --> [Deterministic Router] --> regex match? --> direct route
               | no match
         [Cost Router] --> select gpt-4o-mini or gpt-4o
               |
         [LangGraph Agent + 6 Tools] --> hybrid search (pgvector + BM25)
               |
         [Guardrails] --> pass? --> return answer
                       --> fail? --> retry once with feedback
```

### LangGraph Nodes
1. **router** — 8 regex rules, priority 50-100
2. **model_selector** — cheap vs standard model
3. **agent** — LLM with 6 bound tools
4. **tools** — executes tool calls against pgvector
5. **guardrails** — validates response quality

### Multi-Agent Orchestration
```
timing_analysis --> drc_check --> physical_fix --> merge --> END
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent framework | LangGraph (StateGraph) |
| RAG pipeline | LangChain |
| Vector DB | pgvector (PostgreSQL) |
| Embeddings | OpenAI text-embedding-3-small |
| LLM | GPT-4o-mini / GPT-4o (cost-routed) |
| Keyword search | BM25Retriever |
| MCP | FastMCP |
| API | FastAPI |
| UI | Streamlit |
| Visualization | Plotly |
| EDA Tools | OpenROAD-flow-scripts + sky130 PDK |
| Containers | Docker + docker-compose |
| Cloud | Terraform -> AWS ECS Fargate + RDS (eu-west-1) |

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 16 with pgvector extension
- OpenAI API key

### Setup

```bash
# 1. Clone and install
git clone https://github.com/guris12/ipdesignagentEDA.git
cd ipdesignagentEDA
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Environment
cp .env.example .env
# Edit .env with your OPENAI_API_KEY and DATABASE_URL

# 3. Database
createdb ip_design_db
psql ip_design_db -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 4. Ingest sample data
python -m ip_agent.ingest

# 5. Run
streamlit run app.py              # UI at localhost:8501
uvicorn ip_agent.api:app          # API at localhost:8001
```

### Docker

```bash
docker compose up -d
# UI: http://localhost:8501
# API: http://localhost:8001
# Health: http://localhost:8001/health
```

## Project Structure

```
ip-design-agent/
├── app.py                      # Streamlit demo UI with execution trace
├── demo_multi_agent.py         # 3-agent timing closure demo
├── demo_timing_dashboard.py    # Timing dashboard demo
├── src/ip_agent/
│   ├── _db.py                  # Shared PGVector store (singleton)
│   ├── config.py               # .env loading, constants
│   ├── models.py               # Pydantic data models
│   ├── router.py               # Deterministic routing (8 regex rules)
│   ├── retriever.py            # Hybrid search (pgvector + BM25 + RRF)
│   ├── tools.py                # 6 @tool functions for the agent
│   ├── agent.py                # LangGraph StateGraph (5 nodes)
│   ├── ingest.py               # Ingestion pipeline (.rpt, .md, .txt)
│   ├── etl.py                  # Production ETL (GitHub download, dedup)
│   ├── guardrails.py           # 3-layer validation
│   ├── cost_router.py          # Model routing + semantic cache
│   ├── specialists.py          # 3 specialist agents
│   ├── orchestrator.py         # Multi-agent LangGraph coordination
│   ├── openroad_tools.py       # Live OpenROAD flow execution
│   ├── run_tracker.py          # ECO iteration tracking
│   ├── report_visualizer.py    # Plotly dashboard generation
│   ├── mcp_server.py           # FastMCP server
│   ├── api.py                  # FastAPI REST + A2A endpoints
│   ├── eda_bridge.py           # Safe subprocess wrapper
│   └── a2a_card.py             # Agent Card for A2A discovery
├── data/sample_reports/        # Sample .rpt timing/DRC/cell reports
├── tests/                      # pytest + RAGAS evaluation
└── terraform/                  # AWS deployment (ECS + RDS + S3 + CloudFront)
```

## Sample Queries

- "What are the timing violations?"
- "How do I fix setup violations?"
- "Show me report_checks syntax"
- "What is clock skew?"
- "Explain WNS and TNS"

## Related Research

**Paper:** "Comparative Analysis of Retrieval Methods for RAG over Electronic Design Automation Documentation"
- Published on Zenodo: [DOI: 10.5281/zenodo.19583451](https://doi.org/10.5281/zenodo.19583451)
- Submitted to MLCAD 2026 (ACM/IEEE ML for CAD symposium)

## License

MIT

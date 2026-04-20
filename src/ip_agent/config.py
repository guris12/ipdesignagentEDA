"""
Configuration management for ip-design-agent.
Loads from .env file and provides typed settings.
"""

import json
import os
from dotenv import load_dotenv

load_dotenv(override=True)

# --- API Keys ---
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
LANGCHAIN_API_KEY = os.environ.get("LANGCHAIN_API_KEY", "")

# --- Database ---
# Supports both direct DATABASE_URL (.env) and ECS-style DB_HOST + DB_CREDENTIALS
def _build_database_url() -> str:
    if "DATABASE_URL" in os.environ:
        return os.environ["DATABASE_URL"]
    db_host = os.environ.get("DB_HOST", "")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "ip_agent_db")
    creds_json = os.environ.get("DB_CREDENTIALS", "")
    if creds_json:
        creds = json.loads(creds_json)
        user = creds.get("username", "ip_agent")
        pw = creds.get("password", "")
        return f"postgresql+psycopg://{user}:{pw}@{db_host}:{db_port}/{db_name}"
    db_user = os.environ.get("DB_USERNAME", "ip_agent")
    db_pass = os.environ.get("DB_PASSWORD", "")
    return f"postgresql+psycopg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

DATABASE_URL = _build_database_url()

# --- Embedding ---
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# --- Retrieval ---
TOP_K_RESULTS = 5
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
BM25_K = 5
HYBRID_VECTOR_WEIGHT = 0.5
HYBRID_BM25_WEIGHT = 0.5

# --- Models ---
MODEL_CHEAP = "gpt-4o-mini"
MODEL_STANDARD = "gpt-4o"

# --- Agent ---
COLLECTION_NAME = "ip_design_docs"
MAX_AGENT_ITERATIONS = 10

# --- OpenROAD Integration (Phase 0) ---
OPENROAD_PATH = os.environ.get("OPENROAD_PATH", "")  # e.g., ~/OpenROAD-flow-scripts
# If not set, defaults to ~/OpenROAD-flow-scripts in openroad_tools.py

# --- EFS Shared Volume (agent <-> OpenROAD communication) ---
SHARED_DATA_PATH = os.environ.get("SHARED_DATA_PATH", "/shared")

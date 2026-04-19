"""
Configuration management for ip-design-agent.
Loads from .env file and provides typed settings.
"""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# --- API Keys ---
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
LANGCHAIN_API_KEY = os.environ.get("LANGCHAIN_API_KEY", "")
DATABASE_URL = os.environ["DATABASE_URL"]

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

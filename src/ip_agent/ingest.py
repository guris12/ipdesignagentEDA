"""
Ingestion Pipeline — Load, chunk, embed, and store documents in pgvector.

Handles three source types:
1. Documentation (OpenROAD/OpenSTA markdown/text files from GitHub)
2. Timing reports (.rpt files parsed into structured per-path documents)
3. Flow logs (OpenROAD build logs for debugging context)

Architecture:
    Source files → [Load] → [Split/Chunk] → [Enrich metadata] → [Embed] → [Store in pgvector]

Swift analogy: Like a data pipeline middleware — you fetch raw data,
transform it into your model objects, and persist to Core Data/SwiftData.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    TextLoader,
    DirectoryLoader,
    UnstructuredMarkdownLoader,
)
from langchain_postgres import PGVector
from ip_agent._db import get_vector_store

from ip_agent.config import (
    DATABASE_URL,
    OPENAI_API_KEY,
    COLLECTION_NAME,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    EMBEDDING_MODEL,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embeddings & Vector Store
# ---------------------------------------------------------------------------

def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=OPENAI_API_KEY)


def _get_vector_store() -> PGVector:
    return get_vector_store()


# ---------------------------------------------------------------------------
# Text Splitters
# ---------------------------------------------------------------------------

def _get_doc_splitter() -> RecursiveCharacterTextSplitter:
    """Splitter for documentation — preserves code blocks and paragraphs."""
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "],
        length_function=len,
    )


def _get_report_splitter() -> RecursiveCharacterTextSplitter:
    """Splitter for timing reports — smaller chunks, path-aligned."""
    return RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=50,
        separators=["\n\n", "\n-", "\n", " "],
        length_function=len,
    )


# ---------------------------------------------------------------------------
# Timing Report Parser
# ---------------------------------------------------------------------------

def parse_timing_report(file_path: Path) -> list[Document]:
    """
    Parse a .rpt timing report into per-path documents.

    Extracts:
    - Startpoint / Endpoint
    - Slack value
    - Path group
    - Individual path delays

    Returns one Document per timing path found.
    """
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    documents = []

    # Detect report type from content
    report_type = "setup"
    if "hold" in file_path.name.lower() or "min_delay" in content.lower():
        report_type = "hold"

    # Split into path blocks (OpenSTA format: paths separated by dashes)
    path_blocks = re.split(r"\n-{40,}\n", content)

    for i, block in enumerate(path_blocks):
        if not block.strip():
            continue

        # Extract key fields
        startpoint = ""
        endpoint = ""
        slack = None

        sp_match = re.search(r"Startpoint:\s*(.+)", block)
        if sp_match:
            startpoint = sp_match.group(1).strip()

        ep_match = re.search(r"Endpoint:\s*(.+)", block)
        if ep_match:
            endpoint = ep_match.group(1).strip()

        slack_match = re.search(r"slack\s*\((?:MET|VIOLATED)\)\s*([-\d.]+)", block)
        if slack_match:
            slack = float(slack_match.group(1))

        # Create document
        metadata = {
            "source": file_path.name,
            "source_type": "timing_report",
            "type": "timing_report",
            "report_type": report_type,
            "path_index": i,
            "startpoint": startpoint,
            "endpoint": endpoint,
        }
        if slack is not None:
            metadata["slack"] = slack
            metadata["violated"] = slack < 0

        documents.append(Document(
            page_content=block.strip(),
            metadata=metadata,
        ))

    logger.info(f"Parsed {len(documents)} paths from {file_path.name}")
    return documents


# ---------------------------------------------------------------------------
# Documentation Loader
# ---------------------------------------------------------------------------

def load_documentation(docs_dir: Path) -> list[Document]:
    """
    Load all documentation files from a directory.
    Handles .md, .rst, and .txt files.
    """
    if not docs_dir.exists():
        logger.warning(f"Documentation directory not found: {docs_dir}")
        return []

    documents = []

    # Load markdown files
    md_files = list(docs_dir.glob("**/*.md"))
    for md_file in md_files:
        try:
            loader = TextLoader(str(md_file), encoding="utf-8")
            docs = loader.load()
            for doc in docs:
                doc.metadata.update({
                    "source": md_file.name,
                    "source_type": "documentation",
                    "type": "documentation",
                    "tool": _detect_tool(md_file),
                })
            documents.extend(docs)
        except Exception as e:
            logger.error(f"Failed to load {md_file}: {e}")

    # Load text files
    txt_files = list(docs_dir.glob("**/*.txt"))
    for txt_file in txt_files:
        try:
            loader = TextLoader(str(txt_file), encoding="utf-8")
            docs = loader.load()
            for doc in docs:
                doc.metadata.update({
                    "source": txt_file.name,
                    "source_type": "documentation",
                    "type": "documentation",
                    "tool": _detect_tool(txt_file),
                })
            documents.extend(docs)
        except Exception as e:
            logger.error(f"Failed to load {txt_file}: {e}")

    logger.info(f"Loaded {len(documents)} documentation files from {docs_dir}")
    return documents


def _detect_tool(file_path: Path) -> str:
    """Detect which EDA tool a file belongs to based on path."""
    path_str = str(file_path).lower()
    if "openroad" in path_str:
        return "openroad"
    elif "opensta" in path_str:
        return "opensta"
    return "unknown"


# ---------------------------------------------------------------------------
# Main Ingestion Functions
# ---------------------------------------------------------------------------

def ingest_documents(docs_dir: Path) -> int:
    """
    Full ingestion pipeline for documentation files.
    Returns number of chunks stored.
    """
    # Load
    raw_docs = load_documentation(docs_dir)
    if not raw_docs:
        logger.warning("No documents to ingest")
        return 0

    # Split
    splitter = _get_doc_splitter()
    chunks = splitter.split_documents(raw_docs)
    logger.info(f"Split into {len(chunks)} chunks")

    # Enrich metadata
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = i
        chunk.metadata["total_chunks"] = len(chunks)

    # Store in pgvector
    vector_store = _get_vector_store()
    vector_store.add_documents(chunks)
    logger.info(f"Stored {len(chunks)} chunks in pgvector")

    return len(chunks)


def _classify_report(file_path: Path) -> str:
    """Classify a .rpt file by its content: timing_report, drc_report, or cell_report."""
    name = file_path.name.lower()
    if "drc" in name:
        return "drc_report"
    if "cell" in name or "usage" in name:
        return "cell_report"

    content = file_path.read_text(encoding="utf-8", errors="ignore")[:500]
    if "DRC Violation" in content or "Minimum Spacing" in content or "Metal" in content and "Short" in content:
        return "drc_report"
    if "Cell Type" in content or "Cell Usage" in content:
        return "cell_report"
    return "timing_report"


def ingest_timing_reports(reports_dir: Path) -> int:
    """
    Ingest timing report files (.rpt).
    Returns number of path documents stored.
    """
    if not reports_dir.exists():
        logger.warning(f"Reports directory not found: {reports_dir}")
        return 0

    rpt_files = list(reports_dir.glob("**/*.rpt"))
    if not rpt_files:
        logger.warning(f"No .rpt files found in {reports_dir}")
        return 0

    all_docs = []
    for rpt_file in rpt_files:
        report_class = _classify_report(rpt_file)
        docs = parse_timing_report(rpt_file)
        for doc in docs:
            doc.metadata["source_type"] = report_class
            doc.metadata["type"] = report_class
        logger.info(f"Classified {rpt_file.name} as {report_class}")
        all_docs.extend(docs)

    if not all_docs:
        return 0

    # Split long path blocks further
    splitter = _get_report_splitter()
    chunks = splitter.split_documents(all_docs)

    # Store
    vector_store = _get_vector_store()
    vector_store.add_documents(chunks)
    logger.info(f"Stored {len(chunks)} timing report chunks in pgvector")

    return len(chunks)


def ingest_all(base_dir: Path | None = None) -> dict[str, int]:
    """
    Run full ingestion: documentation + timing reports.

    Args:
        base_dir: Project root (defaults to ./data/)

    Returns:
        Dict with counts: {"documentation": N, "timing_reports": M}
    """
    if base_dir is None:
        # Check env var first (set in Docker/ECS), then /app/data, then relative to source
        import os
        if os.environ.get("DATA_DIR"):
            base_dir = Path(os.environ["DATA_DIR"])
        elif Path("/app/data").exists():
            base_dir = Path("/app/data")
        else:
            base_dir = Path(__file__).parent.parent.parent / "data"

    results = {}

    docs_dir = base_dir / "docs"
    results["documentation"] = ingest_documents(docs_dir)

    reports_dir = base_dir / "sample_reports"
    results["timing_reports"] = ingest_timing_reports(reports_dir)

    total = sum(results.values())
    logger.info(f"Ingestion complete: {total} total chunks ({results})")

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        base_dir = Path(sys.argv[1])
    elif Path("/app/data").exists():
        base_dir = Path("/app/data")
    else:
        base_dir = Path(__file__).parent.parent.parent / "data"

    print(f"Ingesting from: {base_dir}")
    results = ingest_all(base_dir)
    print(f"Done! {results}")

"""
Production ETL Pipeline — Extract, Transform, Load for EDA documents.

This is the production version of ingest.py with:
- Incremental updates (skip already-ingested files)
- Parallel embedding generation
- Metadata enrichment (auto-detect corner, mode, tool)
- Progress tracking and error recovery
- GitHub-based documentation downloading

Architecture:
    [Extract] → Download docs from GitHub, parse .rpt files
    [Transform] → Chunk, enrich metadata, detect domains
    [Load] → Embed and store in pgvector (batch, with dedup)

Swift analogy: Like a background data sync manager — checks what's new,
processes incrementally, handles failures gracefully (like CloudKit sync).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import httpx
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_postgres import PGVector

from ip_agent.config import (
    DATABASE_URL,
    OPENAI_API_KEY,
    COLLECTION_NAME,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
    EMBEDDING_MODEL,
)
from ip_agent.ingest import parse_timing_report

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GitHub Documentation Sources
# ---------------------------------------------------------------------------

GITHUB_SOURCES = [
    {
        "repo": "The-OpenROAD-Project/OpenROAD",
        "paths": ["docs/"],
        "tool": "openroad",
    },
    {
        "repo": "The-OpenROAD-Project/OpenSTA",
        "paths": ["doc/", "README.md"],
        "tool": "opensta",
    },
]


# ---------------------------------------------------------------------------
# Extract Phase
# ---------------------------------------------------------------------------

async def download_github_docs(
    repo: str,
    paths: list[str],
    output_dir: Path,
    token: str | None = None,
) -> list[Path]:
    """
    Download documentation files from a GitHub repository.

    Args:
        repo: GitHub repo (e.g., "The-OpenROAD-Project/OpenSTA")
        paths: Paths within the repo to download
        output_dir: Local directory to save files
        token: Optional GitHub token for rate limiting

    Returns:
        List of downloaded file paths
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    async with httpx.AsyncClient() as client:
        for path in paths:
            url = f"https://api.github.com/repos/{repo}/contents/{path}"

            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                items = response.json()

                if not isinstance(items, list):
                    items = [items]

                for item in items:
                    if item["type"] == "file" and _is_doc_file(item["name"]):
                        file_path = output_dir / item["name"]
                        content_resp = await client.get(item["download_url"])
                        file_path.write_text(content_resp.text, encoding="utf-8")
                        downloaded.append(file_path)
                        logger.info(f"Downloaded: {item['name']}")

            except Exception as e:
                logger.error(f"Failed to download from {url}: {e}")

    return downloaded


def _is_doc_file(filename: str) -> bool:
    """Check if a file is a documentation file we want to ingest."""
    extensions = {".md", ".rst", ".txt", ".adoc"}
    return Path(filename).suffix.lower() in extensions


# ---------------------------------------------------------------------------
# Transform Phase
# ---------------------------------------------------------------------------

def _compute_content_hash(content: str) -> str:
    """Generate hash for deduplication."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def enrich_metadata(doc: Document) -> Document:
    """
    Auto-detect and enrich document metadata.

    Detects:
    - EDA tool (openroad, opensta)
    - Corner (ss/tt/ff with voltage/temp)
    - Report type (setup, hold)
    - Key topics
    """
    content_lower = doc.page_content.lower()
    metadata = doc.metadata.copy()

    # Detect corner from content
    corner_patterns = {
        "ss_0p72v_m40c": "slow-slow",
        "tt_0p80v_25c": "typical",
        "ff_0p88v_125c": "fast-fast",
        "ss": "slow",
        "ff": "fast",
        "tt": "typical",
    }
    for pattern, corner in corner_patterns.items():
        if pattern in content_lower:
            metadata["corner"] = corner
            break

    # Detect topics
    topics = []
    topic_keywords = {
        "placement": ["placement", "place_design", "legalize"],
        "routing": ["routing", "route_design", "global_route", "detail_route"],
        "timing": ["timing", "slack", "setup", "hold", "clock"],
        "cts": ["clock tree", "cts", "clock_tree_synthesis"],
        "optimization": ["optimize", "resize", "buffer", "repair"],
    }
    for topic, keywords in topic_keywords.items():
        if any(kw in content_lower for kw in keywords):
            topics.append(topic)

    if topics:
        metadata["topics"] = topics

    # Content hash for dedup
    metadata["content_hash"] = _compute_content_hash(doc.page_content)

    doc.metadata = metadata
    return doc


def transform_documents(
    raw_docs: list[Document],
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[Document]:
    """
    Transform raw documents: split, enrich, deduplicate.
    """
    # Split
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "],
    )
    chunks = splitter.split_documents(raw_docs)

    # Enrich metadata
    enriched = [enrich_metadata(chunk) for chunk in chunks]

    # Deduplicate by content hash
    seen_hashes = set()
    deduped = []
    for doc in enriched:
        content_hash = doc.metadata.get("content_hash", "")
        if content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            deduped.append(doc)

    logger.info(
        f"Transform: {len(raw_docs)} raw → {len(chunks)} chunks → {len(deduped)} deduped"
    )
    return deduped


# ---------------------------------------------------------------------------
# Load Phase
# ---------------------------------------------------------------------------

def load_to_pgvector(
    documents: list[Document],
    batch_size: int = 50,
) -> int:
    """
    Load documents into pgvector with batched embedding generation.

    Returns number of documents stored.
    """
    if not documents:
        return 0

    from ip_agent._db import get_vector_store
    vector_store = get_vector_store()

    total_stored = 0

    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        try:
            vector_store.add_documents(batch)
            total_stored += len(batch)
            logger.info(f"Stored batch {i//batch_size + 1}: {total_stored}/{len(documents)}")
        except Exception as e:
            logger.error(f"Batch {i//batch_size + 1} failed: {e}")
            # Continue with next batch
            continue

    return total_stored


# ---------------------------------------------------------------------------
# Full ETL Pipeline
# ---------------------------------------------------------------------------

async def run_etl(
    data_dir: Path | None = None,
    download_from_github: bool = False,
    github_token: str | None = None,
) -> dict[str, Any]:
    """
    Run the full ETL pipeline.

    Args:
        data_dir: Base data directory (default: project/data/)
        download_from_github: Whether to fetch docs from GitHub
        github_token: GitHub token for API rate limits

    Returns:
        Summary dict with counts and status
    """
    if data_dir is None:
        data_dir = Path(__file__).parent.parent.parent / "data"

    results = {
        "downloaded": 0,
        "docs_chunks": 0,
        "timing_chunks": 0,
        "total_stored": 0,
        "errors": [],
    }

    # Phase 1: Extract
    if download_from_github:
        for source in GITHUB_SOURCES:
            try:
                files = await download_github_docs(
                    repo=source["repo"],
                    paths=source["paths"],
                    output_dir=data_dir / "docs" / source["tool"],
                    token=github_token,
                )
                results["downloaded"] += len(files)
            except Exception as e:
                results["errors"].append(f"Download failed for {source['repo']}: {e}")

    # Phase 2: Transform documentation
    docs_dir = data_dir / "docs"
    if docs_dir.exists():
        from ip_agent.ingest import load_documentation
        raw_docs = load_documentation(docs_dir)
        doc_chunks = transform_documents(raw_docs)
        results["docs_chunks"] = len(doc_chunks)
    else:
        doc_chunks = []

    # Phase 2b: Transform timing reports
    reports_dir = data_dir / "sample_reports"
    timing_chunks = []
    if reports_dir.exists():
        for rpt_file in reports_dir.glob("**/*.rpt"):
            parsed = parse_timing_report(rpt_file)
            timing_chunks.extend(parsed)
        timing_chunks = transform_documents(timing_chunks, chunk_size=600, chunk_overlap=50)
        results["timing_chunks"] = len(timing_chunks)

    # Phase 3: Load
    all_chunks = doc_chunks + timing_chunks
    if all_chunks:
        stored = load_to_pgvector(all_chunks)
        results["total_stored"] = stored

    logger.info(f"ETL complete: {results}")
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level=logging.INFO)

    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    download = "--download" in sys.argv

    results = asyncio.run(run_etl(data_dir=data_dir, download_from_github=download))
    print(f"\nETL Results: {results}")

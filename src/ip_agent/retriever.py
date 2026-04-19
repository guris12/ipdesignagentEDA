"""
Hybrid Retriever: pgvector (semantic) + BM25 (keyword) + Reciprocal Rank Fusion.

Why hybrid?
- Vector search finds semantically similar content ("how to fix timing" matches "setup violation repair")
- BM25 finds exact keywords ("set_input_delay" matches documents containing that exact command)
- EDA queries need BOTH: natural language questions + exact command/term lookups

Architecture:
  Query → [Vector Search] ──┐
                             ├── RRF Fusion → Reranked Results
  Query → [BM25 Search]  ───┘
"""

from ip_agent._db import get_vector_store
from langchain_postgres import PGVector
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever

from ip_agent.config import (
    DATABASE_URL, OPENAI_API_KEY, COLLECTION_NAME,
    TOP_K_RESULTS, HYBRID_VECTOR_WEIGHT, HYBRID_BM25_WEIGHT
)


def _get_vector_store() -> PGVector:
    return get_vector_store()


# --- Simple Vector Search (baseline) ---

def search(query: str, top_k: int = TOP_K_RESULTS) -> list[Document]:
    """Pure vector similarity search."""
    return _get_vector_store().similarity_search(query, k=top_k)


def search_with_score(query: str, top_k: int = TOP_K_RESULTS) -> list[tuple[Document, float]]:
    """Vector search returning (document, similarity_score) pairs."""
    return _get_vector_store().similarity_search_with_score(query, k=top_k)


# --- Hybrid Search (vector + BM25 + RRF) ---

class HybridRetriever:
    """
    Combines dense retrieval (pgvector) with sparse retrieval (BM25)
    using Reciprocal Rank Fusion for final ranking.

    This is critical for EDA queries:
    - "How to fix hold violations?" → Vector search excels (semantic)
    - "set_input_delay command syntax" → BM25 excels (exact keyword)
    - Combined → Best of both worlds
    """

    def __init__(self, documents: list[Document] | None = None):
        self._vector_store = _get_vector_store()
        self._documents = documents
        self._ensemble: EnsembleRetriever | None = None

    def _build_ensemble(self, top_k: int) -> EnsembleRetriever:
        """Build ensemble retriever with vector + BM25."""
        vector_retriever = self._vector_store.as_retriever(
            search_kwargs={"k": top_k}
        )

        if self._documents:
            bm25_retriever = BM25Retriever.from_documents(
                self._documents, k=top_k
            )
        else:
            # Fall back to vector-only if no documents loaded for BM25
            return vector_retriever

        return EnsembleRetriever(
            retrievers=[vector_retriever, bm25_retriever],
            weights=[HYBRID_VECTOR_WEIGHT, HYBRID_BM25_WEIGHT],
        )

    def search(self, query: str, top_k: int = TOP_K_RESULTS) -> list[Document]:
        """Hybrid search with RRF fusion."""
        ensemble = self._build_ensemble(top_k)
        return ensemble.invoke(query)

    def search_filtered(
        self,
        query: str,
        source_type: str | None = None,
        top_k: int = TOP_K_RESULTS,
    ) -> list[Document]:
        """
        Hybrid search with metadata filtering.

        Args:
            source_type: Filter by "documentation" or "timing_report"
        """
        results = self.search(query, top_k=top_k * 2)

        if source_type:
            results = [
                doc for doc in results
                if doc.metadata.get("type") == source_type
            ]

        return results[:top_k]


# --- Module-level instance for convenience ---

_hybrid_retriever: HybridRetriever | None = None


def get_hybrid_retriever(documents: list[Document] | None = None) -> HybridRetriever:
    """Get or create the hybrid retriever singleton."""
    global _hybrid_retriever
    if _hybrid_retriever is None:
        _hybrid_retriever = HybridRetriever(documents)
    return _hybrid_retriever


def hybrid_search(query: str, top_k: int = TOP_K_RESULTS) -> list[Document]:
    """Convenience function for hybrid search."""
    return get_hybrid_retriever().search(query, top_k)


def hybrid_search_filtered(
    query: str,
    source_type: str | None = None,
    top_k: int = TOP_K_RESULTS,
) -> list[Document]:
    """Convenience function for filtered hybrid search."""
    return get_hybrid_retriever().search_filtered(query, source_type, top_k)

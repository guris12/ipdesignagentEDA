"""Shared PGVector store — single instance for entire process.

Fixes langchain_postgres v0.0.17 bug: _get_embedding_collection_store()
re-defines ORM classes on every PGVector() call, but the `_classes` cache
guard fails when the function is called from different import paths, because
the module-level `_classes` variable gets shadowed. We fix this by calling the
function once at import time so it populates its own cache.
"""
import langchain_postgres.vectorstores as _vs

_vs._get_embedding_collection_store()

from langchain_openai import OpenAIEmbeddings  # noqa: E402
from langchain_postgres import PGVector  # noqa: E402
from ip_agent.config import DATABASE_URL, OPENAI_API_KEY, COLLECTION_NAME, EMBEDDING_MODEL  # noqa: E402

_store: PGVector | None = None


def get_vector_store() -> PGVector:
    global _store
    if _store is None:
        _store = PGVector(
            embeddings=OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=OPENAI_API_KEY),
            collection_name=COLLECTION_NAME,
            connection=DATABASE_URL,
        )
    return _store

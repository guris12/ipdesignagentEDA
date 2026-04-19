"""
cost_router.py — Cost/performance optimization through model routing, semantic
caching, and token budget management for the IP Design Intelligence Agent.

In production AI systems, not every question needs GPT-4o. A glossary lookup
("What is WNS?") is just as good with GPT-4o-mini at 1/17th the cost. This
module routes queries to the right model, caches repeated questions, and tracks
spend — the kind of thing Synopsys would absolutely need at scale.

Swift analogy: Think of this like a URLSession configuration layer. You wouldn't
use the same timeout/cache policy for every network request. Some go through a
fast CDN cache, others need a full server round-trip. This module is that layer
for LLM calls.

Usage:
    router = CostRouter()
    result = await router.route_and_call(question, contexts)
    print(result.answer, result.cost)

Architecture:
    1. Semantic Cache  — check if we've seen this question before (embedding similarity)
    2. Model Router    — classify question difficulty -> pick cheap or expensive model
    3. Token Budget    — enforce per-session/per-user spend limits
    4. Cost Tracker    — log every call with model, tokens, cost, latency
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Model pricing (as of 2026-Q1, OpenAI pricing)
# ---------------------------------------------------------------------------

class ModelTier(str, Enum):
    """Available model tiers, cheapest to most expensive."""
    MINI = "gpt-4o-mini"       # $0.15 / 1M input, $0.60 / 1M output
    STANDARD = "gpt-4o"        # $2.50 / 1M input, $10.00 / 1M output


# Pricing per 1M tokens (input, output) in USD
MODEL_PRICING: dict[str, tuple[float, float]] = {
    ModelTier.MINI: (0.15, 0.60),
    ModelTier.STANDARD: (2.50, 10.00),
}

# Embedding model pricing
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_PRICE_PER_1M = 0.02  # $0.02 / 1M tokens

# Default token budget per session
DEFAULT_SESSION_TOKEN_BUDGET = 500_000    # ~$1.25 worst case with GPT-4o
DEFAULT_SESSION_COST_BUDGET = 2.00        # $2.00 hard cap per session


# ---------------------------------------------------------------------------
# Pydantic Models (Swift Codable equivalents)
# ---------------------------------------------------------------------------

class QueryDifficulty(str, Enum):
    """Classification of question complexity.

    Swift analogy: Like an enum with associated routing logic — similar to
    how you'd define APIEndpoint cases in your networking layer.
    """
    EASY = "easy"       # Glossary, syntax, single-fact lookups
    MEDIUM = "medium"   # Multi-step but single-domain questions
    HARD = "hard"       # Cross-domain reasoning, timing path analysis, debugging


class CacheEntry(BaseModel):
    """A cached question-answer pair with its embedding."""
    question: str
    answer: str
    embedding: list[float] = Field(description="Embedding vector for semantic matching")
    model_used: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hit_count: int = Field(default=0, description="Number of times this cache entry was used")
    question_hash: str = Field(
        default="",
        description="MD5 hash for fast exact-match lookup before embedding comparison",
    )

    def model_post_init(self, __context: Any) -> None:
        """Compute hash on creation — like Swift's `init` with computed properties."""
        if not self.question_hash:
            self.question_hash = hashlib.md5(
                self.question.strip().lower().encode()
            ).hexdigest()


class TokenUsage(BaseModel):
    """Token usage for a single LLM call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    embedding_tokens: int = 0


class CostRecord(BaseModel):
    """Cost record for a single query — logged to LangSmith and local tracker."""
    query_id: str = Field(description="Unique ID for this query")
    question: str
    model_used: str
    difficulty: QueryDifficulty
    tokens: TokenUsage
    cost_usd: float = Field(description="Total cost in USD for this query")
    latency_ms: float = Field(description="End-to-end latency in milliseconds")
    cache_hit: bool = Field(default=False)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionBudget(BaseModel):
    """
    Tracks token and cost budget for a session or user.

    Swift analogy: Like a `class` with `@Published` properties that you'd
    observe in SwiftUI — except here we check budget before each LLM call.
    """
    session_id: str
    max_tokens: int = DEFAULT_SESSION_TOKEN_BUDGET
    max_cost_usd: float = DEFAULT_SESSION_COST_BUDGET
    tokens_used: int = 0
    cost_used: float = 0.0
    queries_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.max_tokens - self.tokens_used)

    @property
    def cost_remaining(self) -> float:
        return max(0.0, self.max_cost_usd - self.cost_used)

    @property
    def is_within_budget(self) -> bool:
        return self.tokens_remaining > 0 and self.cost_remaining > 0.0

    def consume(self, tokens: int, cost: float) -> None:
        """Record token and cost consumption."""
        self.tokens_used += tokens
        self.cost_used += cost
        self.queries_count += 1


class RouteResult(BaseModel):
    """Result from the cost router — includes the answer plus all metadata."""
    answer: str
    model_used: str
    difficulty: QueryDifficulty
    cost_usd: float
    tokens: TokenUsage
    latency_ms: float
    cache_hit: bool
    guardrail_note: str | None = Field(
        default=None,
        description="If budget was exceeded or model was downgraded, explain why",
    )


# ---------------------------------------------------------------------------
# Model Router — classify question difficulty
# ---------------------------------------------------------------------------

# Keywords/patterns that indicate question difficulty.
# These are tuned for the EDA domain.
EASY_INDICATORS: list[str] = [
    # Glossary lookups
    "what is", "what are", "define", "definition of", "meaning of",
    "what does", "stands for", "abbreviation",
    # Simple syntax
    "syntax for", "syntax of", "how to run", "command for",
    "what command", "which command",
    # Single-fact
    "default value", "default setting", "file format", "file extension",
]

HARD_INDICATORS: list[str] = [
    # Multi-step reasoning
    "why is", "why does", "explain why", "root cause",
    "debug", "troubleshoot", "diagnose",
    # Cross-domain analysis
    "compare", "difference between", "trade-off", "tradeoff",
    "versus", "vs", "pros and cons",
    # Timing path analysis (complex)
    "critical path", "worst path", "fix timing", "closure",
    "all failing paths", "violating paths", "multiple violations",
    "setup and hold", "cross-domain", "multi-corner",
    # Design-level questions
    "floorplan strategy", "power grid", "clock tree",
    "optimization", "reduce area", "reduce power",
    # Requires synthesis of multiple docs
    "step by step", "complete flow", "end to end",
    "workflow for", "best practice",
]


def classify_difficulty(question: str) -> QueryDifficulty:
    """
    Classify a question's difficulty to determine which model to use.

    This is a lightweight keyword-based classifier. For a production system,
    you could train a small classifier or use GPT-4o-mini itself to classify
    (at ~$0.0001 per classification).

    Swift analogy: Like a `switch` statement on the question's content,
    falling through to a default case.

    Args:
        question: The user's question text.

    Returns:
        QueryDifficulty — EASY, MEDIUM, or HARD.
    """
    q_lower = question.lower().strip()
    word_count = len(q_lower.split())

    # Very short questions are usually simple lookups
    if word_count <= 5:
        # Unless they contain hard indicators
        if any(ind in q_lower for ind in HARD_INDICATORS):
            return QueryDifficulty.MEDIUM
        return QueryDifficulty.EASY

    # Check for hard indicators first (they take priority)
    hard_score = sum(1 for ind in HARD_INDICATORS if ind in q_lower)
    easy_score = sum(1 for ind in EASY_INDICATORS if ind in q_lower)

    if hard_score >= 2:
        return QueryDifficulty.HARD
    if hard_score == 1 and easy_score == 0:
        return QueryDifficulty.HARD
    if easy_score >= 1 and hard_score == 0:
        return QueryDifficulty.EASY

    # Long questions with multiple clauses tend to be harder
    if word_count > 25:
        return QueryDifficulty.HARD
    if word_count > 15:
        return QueryDifficulty.MEDIUM

    return QueryDifficulty.MEDIUM


def select_model(difficulty: QueryDifficulty, budget: SessionBudget) -> ModelTier:
    """
    Select the appropriate model based on difficulty and remaining budget.

    If budget is running low, downgrade to cheaper model regardless of difficulty.

    Args:
        difficulty: The classified question difficulty.
        budget: Current session budget state.

    Returns:
        The model tier to use.
    """
    # Budget-aware downgrade: if less than 20% budget remains, force cheap model
    budget_ratio = budget.cost_remaining / budget.max_cost_usd if budget.max_cost_usd > 0 else 0
    if budget_ratio < 0.20:
        logger.info("Budget low (%.1f%% remaining) — forcing GPT-4o-mini", budget_ratio * 100)
        return ModelTier.MINI

    model_map = {
        QueryDifficulty.EASY: ModelTier.MINI,
        QueryDifficulty.MEDIUM: ModelTier.MINI,      # MEDIUM uses mini too — good enough
        QueryDifficulty.HARD: ModelTier.STANDARD,
    }
    return model_map[difficulty]


# ---------------------------------------------------------------------------
# Semantic Cache
# ---------------------------------------------------------------------------

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Compute cosine similarity between two vectors.

    Pure Python implementation — no numpy needed. For production with many
    cached entries, you'd use pgvector's built-in similarity search instead.

    Swift analogy: Like `vDSP.dotProduct()` from Accelerate framework,
    but in plain Python.
    """
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = sum(a * a for a in vec_a) ** 0.5
    magnitude_b = sum(b * b for b in vec_b) ** 0.5

    if magnitude_a == 0.0 or magnitude_b == 0.0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


class SemanticCache:
    """
    In-memory semantic cache for question-answer pairs.

    Before calling the LLM, check if a semantically similar question was already
    answered. Uses embedding similarity with a configurable threshold.

    For production, this should be backed by pgvector (which you already have)
    so cache persists across restarts and scales to thousands of entries.

    Swift analogy: Like NSCache but with semantic matching instead of exact keys.
    The "key" is an embedding vector, and "matching" uses cosine similarity
    instead of `==`.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.95,
        max_entries: int = 1000,
    ):
        """
        Args:
            similarity_threshold: Minimum cosine similarity to count as a cache hit.
                0.95 is strict (nearly identical questions only).
                0.90 would catch paraphrases but risks wrong answers.
            max_entries: Maximum cache size. Oldest entries evicted when full.
        """
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self._entries: list[CacheEntry] = []
        self._stats = {"hits": 0, "misses": 0}

    @property
    def hit_rate(self) -> float:
        """Cache hit rate as a fraction (0.0 to 1.0)."""
        total = self._stats["hits"] + self._stats["misses"]
        return self._stats["hits"] / total if total > 0 else 0.0

    @property
    def size(self) -> int:
        return len(self._entries)

    def lookup(self, question: str, embedding: list[float]) -> CacheEntry | None:
        """
        Check if a semantically similar question exists in cache.

        First tries exact hash match (fast), then falls back to embedding
        similarity (slower but catches paraphrases).

        Args:
            question: The user's question.
            embedding: The question's embedding vector.

        Returns:
            CacheEntry if found, None if cache miss.
        """
        # Fast path: exact hash match
        q_hash = hashlib.md5(question.strip().lower().encode()).hexdigest()
        for entry in self._entries:
            if entry.question_hash == q_hash:
                entry.hit_count += 1
                self._stats["hits"] += 1
                logger.info("Cache HIT (exact match): '%s'", question[:60])
                return entry

        # Slow path: semantic similarity
        best_entry: CacheEntry | None = None
        best_score = 0.0

        for entry in self._entries:
            score = cosine_similarity(embedding, entry.embedding)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry and best_score >= self.similarity_threshold:
            best_entry.hit_count += 1
            self._stats["hits"] += 1
            logger.info(
                "Cache HIT (semantic, score=%.4f): '%s' matched '%s'",
                best_score, question[:40], best_entry.question[:40],
            )
            return best_entry

        self._stats["misses"] += 1
        logger.debug("Cache MISS (best score=%.4f): '%s'", best_score, question[:60])
        return None

    def store(
        self,
        question: str,
        answer: str,
        embedding: list[float],
        model_used: str,
    ) -> None:
        """
        Store a new question-answer pair in the cache.

        If cache is full, evict the least-used entry (LFU policy).

        Args:
            question: The original question.
            answer: The generated answer.
            embedding: The question's embedding vector.
            model_used: Which model generated the answer.
        """
        # Evict if at capacity
        if len(self._entries) >= self.max_entries:
            # Evict least-frequently-used entry
            self._entries.sort(key=lambda e: e.hit_count)
            evicted = self._entries.pop(0)
            logger.debug("Cache evicted: '%s' (hits=%d)", evicted.question[:40], evicted.hit_count)

        entry = CacheEntry(
            question=question,
            answer=answer,
            embedding=embedding,
            model_used=model_used,
        )
        self._entries.append(entry)
        logger.debug("Cache stored: '%s'", question[:60])

    def clear(self) -> None:
        """Clear all cache entries and reset stats."""
        self._entries.clear()
        self._stats = {"hits": 0, "misses": 0}


# ---------------------------------------------------------------------------
# Token Budget Manager
# ---------------------------------------------------------------------------

class TokenBudgetManager:
    """
    Manages per-session and per-user token/cost budgets.

    Prevents runaway costs by enforcing hard limits. Logs usage so you can
    track spend over time (feeds into LangSmith traces).

    Swift analogy: Like an in-app purchase manager that checks balance
    before allowing a transaction.
    """

    def __init__(self):
        self._sessions: dict[str, SessionBudget] = {}
        self._cost_history: list[CostRecord] = []

    def get_or_create_session(
        self,
        session_id: str,
        max_tokens: int = DEFAULT_SESSION_TOKEN_BUDGET,
        max_cost_usd: float = DEFAULT_SESSION_COST_BUDGET,
    ) -> SessionBudget:
        """Get existing session budget or create a new one."""
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionBudget(
                session_id=session_id,
                max_tokens=max_tokens,
                max_cost_usd=max_cost_usd,
            )
        return self._sessions[session_id]

    def check_budget(self, session_id: str) -> tuple[bool, str]:
        """
        Check if the session has remaining budget.

        Returns:
            (has_budget, message) — message explains why if budget exhausted.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return True, "No session found — creating with default budget."

        if not session.is_within_budget:
            if session.tokens_remaining <= 0:
                return False, (
                    f"Token budget exhausted: {session.tokens_used:,} / "
                    f"{session.max_tokens:,} tokens used."
                )
            if session.cost_remaining <= 0:
                return False, (
                    f"Cost budget exhausted: ${session.cost_used:.4f} / "
                    f"${session.max_cost_usd:.2f} spent."
                )
        return True, "Budget OK."

    def record_usage(
        self,
        session_id: str,
        cost_record: CostRecord,
    ) -> None:
        """Record token usage and cost for a query."""
        session = self.get_or_create_session(session_id)
        session.consume(
            tokens=cost_record.tokens.total_tokens,
            cost=cost_record.cost_usd,
        )
        self._cost_history.append(cost_record)

        logger.info(
            "Session %s: used %d tokens ($%.4f) — total: %d tokens ($%.4f) — %d queries",
            session_id,
            cost_record.tokens.total_tokens,
            cost_record.cost_usd,
            session.tokens_used,
            session.cost_used,
            session.queries_count,
        )

    def get_session_summary(self, session_id: str) -> dict[str, Any]:
        """Get a summary of session usage for display/logging."""
        session = self._sessions.get(session_id)
        if session is None:
            return {"error": f"Session {session_id} not found"}

        return {
            "session_id": session_id,
            "queries": session.queries_count,
            "tokens_used": session.tokens_used,
            "tokens_remaining": session.tokens_remaining,
            "cost_used": f"${session.cost_used:.4f}",
            "cost_remaining": f"${session.cost_remaining:.4f}",
            "budget_utilization": f"{(session.cost_used / session.max_cost_usd * 100):.1f}%",
        }

    def get_cost_history(
        self,
        session_id: str | None = None,
        last_n: int = 20,
    ) -> list[CostRecord]:
        """Get recent cost records, optionally filtered by session."""
        records = self._cost_history
        if session_id:
            records = [r for r in records if r.query_id.startswith(session_id)]
        return records[-last_n:]


# ---------------------------------------------------------------------------
# Cost Calculator
# ---------------------------------------------------------------------------

def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    embedding_tokens: int = 0,
) -> float:
    """
    Calculate the USD cost for an LLM call.

    Args:
        model: Model name (e.g., "gpt-4o", "gpt-4o-mini").
        prompt_tokens: Number of input tokens.
        completion_tokens: Number of output tokens.
        embedding_tokens: Number of tokens used for embedding (if any).

    Returns:
        Total cost in USD.
    """
    input_price, output_price = MODEL_PRICING.get(model, MODEL_PRICING[ModelTier.STANDARD])

    cost = (
        (prompt_tokens / 1_000_000) * input_price
        + (completion_tokens / 1_000_000) * output_price
        + (embedding_tokens / 1_000_000) * EMBEDDING_PRICE_PER_1M
    )

    return round(cost, 6)


# ---------------------------------------------------------------------------
# CostRouter — Main orchestrator
# ---------------------------------------------------------------------------

class CostRouter:
    """
    The main cost optimization router. Combines caching, model routing,
    token budgeting, and cost tracking into a single interface.

    This is the primary class you interact with. It replaces a direct
    `ChatOpenAI.invoke()` call with a budget-aware, cached, model-routed call.

    Usage:
        router = CostRouter()
        result = router.route_and_call(
            question="What is WNS?",
            contexts=["WNS stands for Worst Negative Slack..."],
            session_id="user_123",
        )

    Swift analogy: This is like a `NetworkManager` class that wraps URLSession,
    handles caching (URLCache), picks the right server (load balancer), and
    logs analytics — all behind a simple `request()` method.
    """

    def __init__(
        self,
        cache_threshold: float = 0.95,
        cache_max_entries: int = 1000,
        default_session_budget_usd: float = DEFAULT_SESSION_COST_BUDGET,
        default_session_budget_tokens: int = DEFAULT_SESSION_TOKEN_BUDGET,
    ):
        self.cache = SemanticCache(
            similarity_threshold=cache_threshold,
            max_entries=cache_max_entries,
        )
        self.budget_manager = TokenBudgetManager()
        self.default_session_budget_usd = default_session_budget_usd
        self.default_session_budget_tokens = default_session_budget_tokens
        self._query_counter = 0

    def _generate_query_id(self, session_id: str) -> str:
        """Generate a unique query ID for tracking."""
        self._query_counter += 1
        return f"{session_id}_{self._query_counter}_{int(time.time())}"

    def _get_embedding(self, text: str) -> tuple[list[float], int]:
        """
        Get embedding for a text string using OpenAI.

        Returns:
            (embedding_vector, token_count)

        NOTE: This requires the `openai` package and OPENAI_API_KEY in env.
        In tests, mock this method to avoid API calls.
        """
        from openai import OpenAI
        client = OpenAI()  # reads OPENAI_API_KEY from environment

        response = client.embeddings.create(
            input=text,
            model=EMBEDDING_MODEL,
        )

        embedding = response.data[0].embedding
        token_count = response.usage.total_tokens
        return embedding, token_count

    def _call_llm(
        self,
        question: str,
        contexts: list[str],
        model: str,
        system_prompt: str | None = None,
    ) -> tuple[str, TokenUsage]:
        """
        Call the LLM with the question and context.

        Returns:
            (answer_text, token_usage)

        NOTE: This requires `langchain-openai` and OPENAI_API_KEY in env.
        """
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage, SystemMessage

        default_system = (
            "You are an expert physical design and static timing analysis assistant. "
            "Answer using ONLY the provided context. Cite sources. "
            "Use precise EDA terminology."
        )

        llm = ChatOpenAI(model=model, temperature=0)

        context_block = "\n---\n".join(contexts) if contexts else "No context provided."

        messages = [
            SystemMessage(content=system_prompt or default_system),
            HumanMessage(content=(
                f"CONTEXT:\n{context_block}\n\n"
                f"QUESTION: {question}\n\n"
                f"Answer the question using the context above. Cite sources."
            )),
        ]

        response = llm.invoke(messages)

        # Extract token usage from response metadata
        usage_meta = response.response_metadata.get("token_usage", {})
        token_usage = TokenUsage(
            prompt_tokens=usage_meta.get("prompt_tokens", 0),
            completion_tokens=usage_meta.get("completion_tokens", 0),
            total_tokens=usage_meta.get("total_tokens", 0),
        )

        return response.content, token_usage

    def route_and_call(
        self,
        question: str,
        contexts: list[str],
        session_id: str = "default",
        system_prompt: str | None = None,
        force_model: str | None = None,
    ) -> RouteResult:
        """
        The main entry point: route the question through cache, model selection,
        budget check, LLM call, and cost tracking.

        Args:
            question: The user's question.
            contexts: Retrieved context documents from RAG.
            session_id: Session/user ID for budget tracking.
            system_prompt: Optional custom system prompt.
            force_model: If set, skip model routing and use this model.

        Returns:
            RouteResult with answer, cost, model used, and metadata.
        """
        start_time = time.time()
        query_id = self._generate_query_id(session_id)
        guardrail_note: str | None = None

        # Ensure session exists
        budget = self.budget_manager.get_or_create_session(
            session_id,
            max_tokens=self.default_session_budget_tokens,
            max_cost_usd=self.default_session_budget_usd,
        )

        # --- Step 1: Budget check ---
        has_budget, budget_msg = self.budget_manager.check_budget(session_id)
        if not has_budget:
            elapsed_ms = (time.time() - start_time) * 1000
            return RouteResult(
                answer=(
                    "Session budget exhausted. Please start a new session "
                    "or contact an administrator to increase your limit.\n\n"
                    f"Details: {budget_msg}"
                ),
                model_used="none",
                difficulty=QueryDifficulty.EASY,
                cost_usd=0.0,
                tokens=TokenUsage(),
                latency_ms=elapsed_ms,
                cache_hit=False,
                guardrail_note=budget_msg,
            )

        # --- Step 2: Get embedding for the question ---
        embedding, embed_tokens = self._get_embedding(question)

        # --- Step 3: Check semantic cache ---
        cached = self.cache.lookup(question, embedding)
        if cached is not None:
            elapsed_ms = (time.time() - start_time) * 1000

            # Cache hit — only cost is the embedding call
            cost = calculate_cost("", 0, 0, embedding_tokens=embed_tokens)
            token_usage = TokenUsage(embedding_tokens=embed_tokens)

            # Record minimal cost
            record = CostRecord(
                query_id=query_id,
                question=question,
                model_used="cache",
                difficulty=QueryDifficulty.EASY,
                tokens=token_usage,
                cost_usd=cost,
                latency_ms=elapsed_ms,
                cache_hit=True,
            )
            self.budget_manager.record_usage(session_id, record)

            return RouteResult(
                answer=cached.answer,
                model_used=f"cache (original: {cached.model_used})",
                difficulty=QueryDifficulty.EASY,
                cost_usd=cost,
                tokens=token_usage,
                latency_ms=elapsed_ms,
                cache_hit=True,
            )

        # --- Step 4: Classify difficulty and select model ---
        difficulty = classify_difficulty(question)
        if force_model:
            model = force_model
        else:
            model = select_model(difficulty, budget)

            # If budget is low and we'd normally use GPT-4o, note the downgrade
            if difficulty == QueryDifficulty.HARD and model == ModelTier.MINI:
                guardrail_note = (
                    "Question classified as HARD but downgraded to GPT-4o-mini "
                    "due to low remaining budget."
                )

        logger.info(
            "Query routed: difficulty=%s model=%s question='%s'",
            difficulty.value, model, question[:60],
        )

        # --- Step 5: Call the LLM ---
        answer, token_usage = self._call_llm(question, contexts, model, system_prompt)
        token_usage.embedding_tokens = embed_tokens

        # --- Step 6: Calculate cost ---
        cost = calculate_cost(
            model=model,
            prompt_tokens=token_usage.prompt_tokens,
            completion_tokens=token_usage.completion_tokens,
            embedding_tokens=token_usage.embedding_tokens,
        )

        elapsed_ms = (time.time() - start_time) * 1000

        # --- Step 7: Record cost and usage ---
        record = CostRecord(
            query_id=query_id,
            question=question,
            model_used=model,
            difficulty=difficulty,
            tokens=token_usage,
            cost_usd=cost,
            latency_ms=elapsed_ms,
            cache_hit=False,
        )
        self.budget_manager.record_usage(session_id, record)

        # --- Step 8: Cache the result ---
        self.cache.store(
            question=question,
            answer=answer,
            embedding=embedding,
            model_used=model,
        )

        return RouteResult(
            answer=answer,
            model_used=model,
            difficulty=difficulty,
            cost_usd=cost,
            tokens=token_usage,
            latency_ms=elapsed_ms,
            cache_hit=False,
            guardrail_note=guardrail_note,
        )

    def get_stats(self, session_id: str = "default") -> dict[str, Any]:
        """
        Get combined stats for display in the Streamlit UI or LangSmith.

        Returns a dict with cache stats, budget stats, and recent cost history.
        """
        session_summary = self.budget_manager.get_session_summary(session_id)
        recent_costs = self.budget_manager.get_cost_history(session_id, last_n=5)

        return {
            "cache": {
                "size": self.cache.size,
                "hit_rate": f"{self.cache.hit_rate:.1%}",
            },
            "session": session_summary,
            "recent_queries": [
                {
                    "question": r.question[:60],
                    "model": r.model_used,
                    "cost": f"${r.cost_usd:.6f}",
                    "tokens": r.tokens.total_tokens,
                    "cache_hit": r.cache_hit,
                    "latency": f"{r.latency_ms:.0f}ms",
                }
                for r in recent_costs
            ],
        }


# ---------------------------------------------------------------------------
# LangGraph Integration — Cost-aware model selection node
# ---------------------------------------------------------------------------

# Module-level router instance (shared across the agent's graph)
_default_router: CostRouter | None = None


def get_router() -> CostRouter:
    """Get or create the default CostRouter instance."""
    global _default_router
    if _default_router is None:
        _default_router = CostRouter()
    return _default_router


def cost_router_node(state: dict) -> dict:
    """
    LangGraph node that replaces direct LLM calls with cost-routed calls.

    Expected state keys:
        messages: list — conversation messages (last HumanMessage is the question)
        retrieved_contexts: list[str] — RAG-retrieved context chunks
        session_id: str (optional) — for budget tracking

    Returns updated state with the model's answer appended to messages,
    plus cost metadata.

    Wire into your LangGraph:
        graph.add_node("cost_router", cost_router_node)
        # Replace the direct "agent" -> LLM call with:
        graph.add_edge("retrieve", "cost_router")
        graph.add_edge("cost_router", "guardrails")
    """
    router = get_router()

    messages = state.get("messages", [])
    contexts = state.get("retrieved_contexts", [])
    session_id = state.get("session_id", "default")

    # Extract the question from the last human message
    question = ""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            question = msg.content
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            question = msg.get("content", "")
            break

    if not question:
        return state

    # Route and call
    result = router.route_and_call(
        question=question,
        contexts=contexts,
        session_id=session_id,
    )

    # Create an AI message with the answer
    from langchain_core.messages import AIMessage
    ai_message = AIMessage(content=result.answer)

    return {
        **state,
        "messages": messages + [ai_message],
        "cost_metadata": result.model_dump(),
        "model_used": result.model_used,
        "query_cost_usd": result.cost_usd,
    }


# ---------------------------------------------------------------------------
# Streamlit UI Helper — display cost dashboard
# ---------------------------------------------------------------------------

def render_cost_sidebar(router: CostRouter, session_id: str = "default") -> None:
    """
    Render cost tracking information in the Streamlit sidebar.

    Call this from your app.py:
        from ip_agent.cost_router import CostRouter, render_cost_sidebar
        router = CostRouter()
        render_cost_sidebar(router, session_id)

    NOTE: Only call this inside a Streamlit app context.
    """
    import streamlit as st

    stats = router.get_stats(session_id)
    session = stats.get("session", {})

    st.sidebar.markdown("---")
    st.sidebar.subheader("Cost Dashboard")

    col1, col2 = st.sidebar.columns(2)
    col1.metric("Queries", session.get("queries", 0))
    col2.metric("Cache Hit Rate", stats["cache"]["hit_rate"])

    col3, col4 = st.sidebar.columns(2)
    col3.metric("Cost", session.get("cost_used", "$0"))
    col4.metric("Remaining", session.get("cost_remaining", "$0"))

    if stats["recent_queries"]:
        st.sidebar.markdown("**Recent queries:**")
        for q in stats["recent_queries"]:
            icon = "HIT" if q["cache_hit"] else q["model"]
            st.sidebar.text(f"{icon} | {q['cost']} | {q['latency']}")


# ---------------------------------------------------------------------------
# __main__ — Usage example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 70)
    print("COST ROUTER — EXAMPLE (no API calls, demonstrating routing logic)")
    print("=" * 70)

    # --- Demonstrate difficulty classification ---
    test_questions = [
        ("What is WNS?", QueryDifficulty.EASY),
        ("What is the syntax for report_checks?", QueryDifficulty.EASY),
        ("How do I fix setup violations in my critical path?", QueryDifficulty.HARD),
        ("Compare setup and hold timing — what are the trade-offs in clock skew optimization?", QueryDifficulty.HARD),
        ("What cells are in the timing path?", QueryDifficulty.EASY),
        ("Step by step, how do I debug a multi-corner timing closure issue with cross-domain clocking?", QueryDifficulty.HARD),
        ("What is the default value for clock uncertainty?", QueryDifficulty.EASY),
    ]

    print("\n--- Difficulty Classification ---")
    for question, expected in test_questions:
        actual = classify_difficulty(question)
        match = "OK" if actual == expected else "MISMATCH"
        model = select_model(actual, SessionBudget(session_id="test"))
        print(f"  [{match}] {actual.value:6s} -> {model.value:15s} | {question}")

    # --- Demonstrate cost calculation ---
    print("\n--- Cost Calculation Examples ---")
    scenarios = [
        ("GPT-4o-mini: 1000 input, 500 output", ModelTier.MINI, 1000, 500),
        ("GPT-4o:      1000 input, 500 output", ModelTier.STANDARD, 1000, 500),
        ("GPT-4o-mini: 5000 input, 2000 output", ModelTier.MINI, 5000, 2000),
        ("GPT-4o:      5000 input, 2000 output", ModelTier.STANDARD, 5000, 2000),
    ]
    for label, model, prompt_tok, comp_tok in scenarios:
        cost = calculate_cost(model, prompt_tok, comp_tok)
        print(f"  {label} = ${cost:.6f}")

    # --- Demonstrate semantic cache ---
    print("\n--- Semantic Cache Demo ---")
    cache = SemanticCache(similarity_threshold=0.95, max_entries=100)

    # Simulate storing a question with a fake embedding
    fake_embedding = [0.1] * 1536  # real embeddings are 1536-dim
    cache.store(
        question="What is WNS?",
        answer="WNS stands for Worst Negative Slack...",
        embedding=fake_embedding,
        model_used="gpt-4o-mini",
    )
    print(f"  Cache size: {cache.size}")

    # Exact match lookup
    hit = cache.lookup("What is WNS?", fake_embedding)
    print(f"  Exact match lookup: {'HIT' if hit else 'MISS'}")

    # Slightly different embedding (should still hit at 0.95 threshold for near-identical)
    similar_embedding = [0.1] * 1535 + [0.11]
    hit2 = cache.lookup("What does WNS mean?", similar_embedding)
    print(f"  Similar question lookup: {'HIT' if hit2 else 'MISS'}")
    print(f"  Cache hit rate: {cache.hit_rate:.1%}")

    # --- Demonstrate budget manager ---
    print("\n--- Budget Manager Demo ---")
    budget_mgr = TokenBudgetManager()
    session = budget_mgr.get_or_create_session("demo_session", max_cost_usd=1.00)
    print(f"  Session budget: ${session.max_cost_usd:.2f}")
    print(f"  Cost remaining: ${session.cost_remaining:.2f}")

    # Simulate some usage
    for i in range(3):
        record = CostRecord(
            query_id=f"demo_session_{i}",
            question=f"Test question {i}",
            model_used=ModelTier.MINI,
            difficulty=QueryDifficulty.EASY,
            tokens=TokenUsage(prompt_tokens=500, completion_tokens=200, total_tokens=700),
            cost_usd=calculate_cost(ModelTier.MINI, 500, 200),
            latency_ms=150.0,
        )
        budget_mgr.record_usage("demo_session", record)

    summary = budget_mgr.get_session_summary("demo_session")
    print(f"  After 3 queries: {summary}")

    has_budget, msg = budget_mgr.check_budget("demo_session")
    print(f"  Has budget: {has_budget} — {msg}")

    # --- Full router instantiation (no API calls) ---
    print("\n--- CostRouter Instance ---")
    router = CostRouter(
        cache_threshold=0.95,
        default_session_budget_usd=5.00,
    )
    print(f"  Router created with cache threshold={router.cache.similarity_threshold}")
    print(f"  Default session budget: ${router.default_session_budget_usd:.2f}")
    print(f"  To make actual LLM calls, set OPENAI_API_KEY and use router.route_and_call()")

    print("\n" + "=" * 70)
    print("To use with the IP Design Agent, import CostRouter in agent.py")
    print("and replace direct ChatOpenAI calls with router.route_and_call().")
    print("=" * 70)

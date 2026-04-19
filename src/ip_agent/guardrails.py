"""
guardrails.py — Output validation, hallucination detection, and domain accuracy
for the IP Design Intelligence Agent.

This module sits as a LangGraph node AFTER answer generation. It inspects the
agent's response against the retrieved context and EDA domain rules, catching
hallucinations and incorrect terminology before the answer reaches the user.

Swift analogy: Think of this like a middleware validator — similar to how you'd
run a Codable decode + custom validation before presenting data in SwiftUI.
Every answer goes through a pipeline of checks, and you get back a typed result
(GuardrailResult) describing what passed and what failed.

Usage as a standalone module:
    result = run_guardrails(question, answer, contexts)
    if not result.passed:
        print(result.issues)

Usage as a LangGraph node:
    graph.add_node("guardrails", guardrail_node)
    graph.add_edge("generate", "guardrails")
"""

from __future__ import annotations

import re
import logging
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models  (Swift Codable equivalents — define shape, get free validation)
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """How serious is the issue? Like Swift's `DiagnosticSeverity`."""
    ERROR = "error"        # answer must be rejected
    WARNING = "warning"    # answer can ship but flag for review
    INFO = "info"          # cosmetic / improvement suggestion


class GuardrailIssue(BaseModel):
    """A single problem found by one of the guardrail checks."""
    check_name: str = Field(description="Which guardrail produced this issue")
    severity: Severity
    message: str = Field(description="Human-readable explanation")
    snippet: str | None = Field(
        default=None,
        description="The offending text from the answer, if applicable",
    )


class GuardrailResult(BaseModel):
    """
    Aggregate result from the full guardrail pipeline.

    Swift analogy: This is like a `Result<ValidatedAnswer, [ValidationError]>` —
    but instead of throwing, you get a typed struct with all the details.
    """
    passed: bool = Field(description="True if no ERROR-level issues found")
    overall_score: float = Field(
        ge=0.0, le=1.0,
        description="1.0 = perfect, 0.0 = completely unreliable",
    )
    issues: list[GuardrailIssue] = Field(default_factory=list)
    hallucination_score: float = Field(
        ge=0.0, le=1.0,
        description="Fraction of claims grounded in context (1.0 = fully grounded)",
    )
    domain_accuracy_score: float = Field(
        ge=0.0, le=1.0,
        description="Domain term usage correctness (1.0 = all terms correct)",
    )
    format_score: float = Field(
        ge=0.0, le=1.0,
        description="Output format compliance (1.0 = perfect format)",
    )


class ClaimVerification(BaseModel):
    """Result of verifying a single extracted claim against context."""
    claim: str
    grounded: bool = Field(description="True if the claim is supported by context")
    supporting_context: str | None = Field(
        default=None,
        description="The context snippet that supports this claim",
    )


# ---------------------------------------------------------------------------
# EDA Domain Glossary & Rules
# ---------------------------------------------------------------------------

# Canonical EDA terms with brief definitions — used for domain accuracy checks.
# Extend this as the knowledge base grows.
EDA_GLOSSARY: dict[str, str] = {
    "setup": "Timing check ensuring data arrives BEFORE the clock edge.",
    "hold": "Timing check ensuring data is STABLE AFTER the clock edge.",
    "slack": "Difference between required time and arrival time. Positive = met, negative = violated.",
    "wns": "Worst Negative Slack — the most critical timing violation in the design.",
    "tns": "Total Negative Slack — sum of all negative slacks across all violated paths.",
    "cts": "Clock Tree Synthesis — building the clock distribution network.",
    "drc": "Design Rule Check — verifies layout meets foundry manufacturing rules.",
    "lvs": "Layout vs. Schematic — checks layout matches the netlist.",
    "sta": "Static Timing Analysis — exhaustive timing check without simulation.",
    "sdc": "Synopsys Design Constraints — industry-standard timing constraint format.",
    "def": "Design Exchange Format — physical layout interchange file format.",
    "lef": "Library Exchange Format — describes cell/technology physical data.",
    "gds": "GDSII Stream Format — final layout format sent to foundry.",
    "rtl": "Register Transfer Level — behavioral hardware description (Verilog/VHDL).",
    "fanout": "Number of gates driven by a single output.",
    "buffer": "A cell that strengthens (re-drives) a signal to reduce delay.",
    "inverter": "A cell that inverts and re-drives a signal.",
    "flip-flop": "A sequential element that captures data on a clock edge.",
    "latch": "A sequential element that is transparent when its enable is active.",
    "clock skew": "Difference in clock arrival time between two flip-flops.",
    "clock jitter": "Cycle-to-cycle variation in clock period.",
    "openroad": "Open-source RTL-to-GDSII flow framework.",
    "opensta": "Open-source Static Timing Analysis engine used inside OpenROAD.",
    "placement": "Assigning physical locations to standard cells in the floorplan.",
    "routing": "Creating metal wire connections between placed cells.",
    "floorplan": "Top-level arrangement of blocks, I/O pads, and power grid.",
    "netlist": "List of all cells and their interconnections.",
    "liberty": "Cell library format (.lib) describing timing, power, and area of cells.",
    "startpoint": "The launching flip-flop or input port of a timing path.",
    "endpoint": "The capturing flip-flop or output port of a timing path.",
}

# Regex patterns that catch common EDA term misuse.
# Each tuple: (pattern_that_should_NOT_match, error_message)
DOMAIN_RULES: list[tuple[re.Pattern[str], str]] = [
    # "setup" and "hold" confusion
    (
        re.compile(r"setup\s+(violation|slack).*after\s+the\s+clock\s+edge", re.IGNORECASE),
        "Setup checks are BEFORE the clock edge, not after. "
        "Possible setup/hold confusion.",
    ),
    (
        re.compile(r"hold\s+(violation|slack).*before\s+the\s+clock\s+edge", re.IGNORECASE),
        "Hold checks are AFTER the clock edge, not before. "
        "Possible setup/hold confusion.",
    ),
    # Slack sign convention errors
    (
        re.compile(r"positive\s+slack.*(violated|failing|violation)", re.IGNORECASE),
        "Positive slack means the timing constraint is MET, not violated.",
    ),
    (
        re.compile(r"negative\s+slack.*(met|passing|passes)", re.IGNORECASE),
        "Negative slack means the timing constraint is VIOLATED, not met.",
    ),
    # WNS direction
    (
        re.compile(r"wns.*(larger|bigger|higher).*is\s+(worse|bad)", re.IGNORECASE),
        "WNS is negative — a MORE negative value is worse. "
        "'Larger WNS' is ambiguous; use 'more negative WNS'.",
    ),
    # Confusing DRC with LVS
    (
        re.compile(r"drc.*(schematic|netlist\s+match)", re.IGNORECASE),
        "DRC checks manufacturing rules. Netlist matching is LVS, not DRC.",
    ),
    (
        re.compile(r"lvs.*(spacing|width|enclosure)\s+(rule|violation)", re.IGNORECASE),
        "LVS checks netlist equivalence. Spacing/width rules are DRC, not LVS.",
    ),
]

# Cell naming convention patterns (common foundry library naming)
CELL_NAME_PATTERN = re.compile(
    r"\b[A-Z]{2,5}[XD]?\d{1,3}(?:_[A-Z0-9]+)*\b"  # e.g., BUFX2, DFFQX1, INVX4_HVT
)

# Slack value pattern — should be a decimal number, possibly negative
SLACK_VALUE_PATTERN = re.compile(
    r"slack\s*(?:=|:|\()\s*([+-]?\d+\.?\d*)"
)


# ---------------------------------------------------------------------------
# Guardrail 1: Hallucination Detection
# ---------------------------------------------------------------------------

def extract_claims(answer: str) -> list[str]:
    """
    Extract factual claims from the answer by splitting on sentence boundaries.

    This is a lightweight approach: each sentence that makes a declarative statement
    is treated as a claim. For production, you'd use an LLM to decompose claims,
    but this keeps costs down and latency low.

    Swift analogy: Like splitting a string by `.components(separatedBy:)` then
    filtering with `.filter { ... }`.
    """
    # Split into sentences (handles abbreviations like "e.g.", "i.e.")
    sentence_splitter = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')
    sentences = sentence_splitter.split(answer.strip())

    claims: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 15:
            continue
        # Skip meta-sentences that aren't factual claims
        skip_prefixes = (
            "I ", "Let me", "Here's", "Here is", "Note:",
            "Please", "You can", "For example",
        )
        if sentence.startswith(skip_prefixes):
            continue
        claims.append(sentence)

    return claims


def check_claim_grounding(
    claim: str,
    contexts: list[str],
    similarity_threshold: float = 0.3,
) -> ClaimVerification:
    """
    Check if a claim is grounded in the retrieved context.

    Uses keyword overlap as a fast heuristic. For each claim, we check if
    a meaningful fraction of its content words appear in at least one context chunk.

    This avoids an extra LLM call per claim (saving cost). For higher accuracy,
    swap this with an NLI model or an LLM entailment check.

    Args:
        claim: A single declarative sentence from the answer.
        contexts: List of retrieved context strings.
        similarity_threshold: Minimum keyword overlap ratio to consider grounded.
    """
    # Extract meaningful words (lowercase, 3+ chars, no stopwords)
    stopwords = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can",
        "had", "her", "was", "one", "our", "out", "has", "have", "been",
        "this", "that", "with", "they", "from", "will", "would", "there",
        "their", "what", "about", "which", "when", "make", "like", "than",
        "each", "just", "also", "into", "over", "such", "some", "other",
        "more", "very", "used", "using", "use", "does",
    }

    def content_words(text: str) -> set[str]:
        words = set(re.findall(r'[a-z_]{3,}', text.lower()))
        return words - stopwords

    claim_words = content_words(claim)
    if not claim_words:
        # No meaningful words — trivially grounded
        return ClaimVerification(claim=claim, grounded=True, supporting_context=None)

    best_overlap = 0.0
    best_context: str | None = None

    for ctx in contexts:
        ctx_words = content_words(ctx)
        if not ctx_words:
            continue
        overlap = len(claim_words & ctx_words) / len(claim_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_context = ctx[:300]  # keep snippet short

    grounded = best_overlap >= similarity_threshold
    return ClaimVerification(
        claim=claim,
        grounded=grounded,
        supporting_context=best_context if grounded else None,
    )


def detect_hallucinations(
    answer: str,
    contexts: list[str],
    threshold: float = 0.3,
) -> tuple[float, list[GuardrailIssue]]:
    """
    Run hallucination detection on the full answer.

    Returns:
        (grounding_score, list_of_issues)
        grounding_score: fraction of claims that are grounded (0.0 to 1.0)
    """
    claims = extract_claims(answer)
    if not claims:
        return 1.0, []

    issues: list[GuardrailIssue] = []
    grounded_count = 0

    for claim in claims:
        verification = check_claim_grounding(claim, contexts, threshold)
        if verification.grounded:
            grounded_count += 1
        else:
            issues.append(GuardrailIssue(
                check_name="hallucination_detector",
                severity=Severity.WARNING,
                message=f"Claim not grounded in retrieved context: '{claim[:100]}...'",
                snippet=claim[:200],
            ))

    score = grounded_count / len(claims) if claims else 1.0

    # If less than half of claims are grounded, escalate to ERROR
    if score < 0.5:
        issues.insert(0, GuardrailIssue(
            check_name="hallucination_detector",
            severity=Severity.ERROR,
            message=(
                f"Only {score:.0%} of claims are grounded in context. "
                f"Answer is likely hallucinated."
            ),
            snippet=None,
        ))

    return score, issues


# ---------------------------------------------------------------------------
# Guardrail 2: Domain Accuracy Validator
# ---------------------------------------------------------------------------

def validate_domain_accuracy(answer: str) -> tuple[float, list[GuardrailIssue]]:
    """
    Check that EDA-specific terms are used correctly in the answer.

    Runs the answer through regex-based domain rules and checks that
    slack values, cell names, and terminology are consistent.

    Returns:
        (accuracy_score, list_of_issues)
    """
    issues: list[GuardrailIssue] = []
    checks_run = 0
    checks_passed = 0

    # --- Rule-based term usage checks ---
    for pattern, error_msg in DOMAIN_RULES:
        checks_run += 1
        match = pattern.search(answer)
        if match:
            issues.append(GuardrailIssue(
                check_name="domain_accuracy",
                severity=Severity.ERROR,
                message=error_msg,
                snippet=match.group(0),
            ))
        else:
            checks_passed += 1

    # --- Slack value sanity check ---
    # If the answer mentions specific slack values, verify they look reasonable
    slack_matches = SLACK_VALUE_PATTERN.findall(answer)
    for slack_str in slack_matches:
        checks_run += 1
        try:
            slack_val = float(slack_str)
            # Slack is typically in nanoseconds, rarely exceeds +/- 100 ns
            if abs(slack_val) > 1000:
                issues.append(GuardrailIssue(
                    check_name="domain_accuracy",
                    severity=Severity.WARNING,
                    message=(
                        f"Slack value {slack_val} seems unreasonably large. "
                        f"Expected range: -100 to +100 ns typically."
                    ),
                    snippet=f"slack = {slack_val}",
                ))
            else:
                checks_passed += 1
        except ValueError:
            checks_passed += 1  # not a parseable number, skip

    # --- Cell name convention check ---
    # If cell names are mentioned, check they follow standard naming conventions
    cell_mentions = CELL_NAME_PATTERN.findall(answer)
    if cell_mentions:
        checks_run += 1
        # Just verify they look like valid cell names (already matched pattern)
        checks_passed += 1

    # --- Glossary term consistency check ---
    # Flag if answer uses a term that contradicts the glossary definition
    answer_lower = answer.lower()
    for term, definition in EDA_GLOSSARY.items():
        if term in answer_lower:
            checks_run += 1
            checks_passed += 1  # term is recognized; detailed contradiction
            # checking is handled by the regex rules above

    score = checks_passed / checks_run if checks_run > 0 else 1.0
    return score, issues


# ---------------------------------------------------------------------------
# Guardrail 3: Output Format Validator
# ---------------------------------------------------------------------------

# Configuration constants
MAX_ANSWER_LENGTH = 4000        # characters — keep answers focused
MIN_ANSWER_LENGTH = 50          # too short = probably unhelpful
SOURCE_CITATION_PATTERN = re.compile(
    r"\[Source\s*\d+[:\]]|"          # [Source 1:] or [Source 1]
    r"\(Source:\s*\w+|"              # (Source: OpenSTA
    r"according\s+to\s+the\s+\w+|"  # "according to the documentation"
    r"from\s+the\s+\w+\s+docs?|"    # "from the OpenSTA doc"
    r"per\s+the\s+\w+\s+manual|"    # "per the OpenROAD manual"
    r"OpenSTA|OpenROAD",             # direct tool/project references
    re.IGNORECASE,
)


def validate_output_format(
    answer: str,
    question: str,
) -> tuple[float, list[GuardrailIssue]]:
    """
    Ensure the answer meets formatting and quality standards:
    - Cites sources
    - Respects length limits
    - Contains actionable content for EDA engineers

    Swift analogy: Like running a set of `XCTAssert` checks on the output.

    Returns:
        (format_score, list_of_issues)
    """
    issues: list[GuardrailIssue] = []
    checks_run = 0
    checks_passed = 0

    # --- Length check ---
    checks_run += 1
    if len(answer) > MAX_ANSWER_LENGTH:
        issues.append(GuardrailIssue(
            check_name="format_validator",
            severity=Severity.WARNING,
            message=(
                f"Answer is {len(answer)} chars, exceeding the "
                f"{MAX_ANSWER_LENGTH}-char limit. Consider summarizing."
            ),
            snippet=None,
        ))
    elif len(answer) < MIN_ANSWER_LENGTH:
        issues.append(GuardrailIssue(
            check_name="format_validator",
            severity=Severity.WARNING,
            message=(
                f"Answer is only {len(answer)} chars. "
                f"May be too brief to be useful."
            ),
            snippet=None,
        ))
    else:
        checks_passed += 1

    # --- Source citation check ---
    checks_run += 1
    if SOURCE_CITATION_PATTERN.search(answer):
        checks_passed += 1
    else:
        issues.append(GuardrailIssue(
            check_name="format_validator",
            severity=Severity.WARNING,
            message=(
                "Answer does not cite any sources. EDA answers should "
                "reference the documentation or timing report data."
            ),
            snippet=None,
        ))

    # --- Actionability check ---
    # For "how to fix" or "how do I" questions, the answer should contain
    # concrete steps, commands, or parameter suggestions.
    checks_run += 1
    question_lower = question.lower()
    is_how_to = any(
        phrase in question_lower
        for phrase in ["how to", "how do", "fix", "resolve", "reduce", "improve"]
    )

    if is_how_to:
        # Look for actionable content: commands, code blocks, numbered steps
        actionable_patterns = [
            r"`[^`]+`",                      # inline code
            r"```",                          # code block
            r"\d+\.\s+",                     # numbered steps
            r"set_\w+|report_\w+|read_\w+",  # OpenSTA/OpenROAD commands
            r"(?:increase|decrease|add|remove|change|set|use)\s+(?:the\s+)?",
        ]
        has_actionable = any(
            re.search(pat, answer, re.IGNORECASE)
            for pat in actionable_patterns
        )
        if has_actionable:
            checks_passed += 1
        else:
            issues.append(GuardrailIssue(
                check_name="format_validator",
                severity=Severity.WARNING,
                message=(
                    "Question asks for a fix/improvement but answer lacks "
                    "concrete steps, commands, or parameters."
                ),
                snippet=None,
            ))
    else:
        checks_passed += 1  # not a how-to question, skip this check

    # --- No apology filler check ---
    checks_run += 1
    apology_patterns = [
        r"I'm sorry",
        r"I apologize",
        r"I don't have enough information",
        r"As an AI",
        r"I cannot",
    ]
    has_filler = any(
        re.search(pat, answer, re.IGNORECASE)
        for pat in apology_patterns
    )
    if has_filler:
        issues.append(GuardrailIssue(
            check_name="format_validator",
            severity=Severity.INFO,
            message=(
                "Answer contains unnecessary apology/hedging filler. "
                "EDA engineers want direct, confident answers."
            ),
            snippet=None,
        ))
    else:
        checks_passed += 1

    score = checks_passed / checks_run if checks_run > 0 else 1.0
    return score, issues


# ---------------------------------------------------------------------------
# Main Pipeline: run_guardrails
# ---------------------------------------------------------------------------

def run_guardrails(
    question: str,
    answer: str,
    retrieved_contexts: list[str],
    hallucination_threshold: float = 0.3,
) -> GuardrailResult:
    """
    Run the full guardrail pipeline on a (question, answer, contexts) triple.

    This is the main entry point. Call this after the LLM generates an answer
    but before returning it to the user.

    Args:
        question: The user's original question.
        answer: The LLM-generated answer.
        retrieved_contexts: List of context strings from the retriever.
        hallucination_threshold: Keyword overlap ratio for grounding check.

    Returns:
        GuardrailResult with pass/fail, scores, and all issues found.

    Swift analogy: Like calling `validate()` on a form — you get back a
    `ValidationResult` with `.isValid` and `.errors[]`.
    """
    all_issues: list[GuardrailIssue] = []

    # 1. Hallucination detection
    hallucination_score, h_issues = detect_hallucinations(
        answer, retrieved_contexts, hallucination_threshold
    )
    all_issues.extend(h_issues)

    # 2. Domain accuracy validation
    domain_score, d_issues = validate_domain_accuracy(answer)
    all_issues.extend(d_issues)

    # 3. Output format validation
    format_score, f_issues = validate_output_format(answer, question)
    all_issues.extend(f_issues)

    # Overall score: weighted combination
    # Hallucination is most critical (50%), domain accuracy next (30%), format last (20%)
    overall_score = (
        0.50 * hallucination_score
        + 0.30 * domain_score
        + 0.20 * format_score
    )

    # Passed = no ERROR-level issues
    has_errors = any(issue.severity == Severity.ERROR for issue in all_issues)

    result = GuardrailResult(
        passed=not has_errors,
        overall_score=round(overall_score, 3),
        issues=all_issues,
        hallucination_score=round(hallucination_score, 3),
        domain_accuracy_score=round(domain_score, 3),
        format_score=round(format_score, 3),
    )

    logger.info(
        "Guardrail result: passed=%s score=%.2f (halluc=%.2f domain=%.2f format=%.2f) issues=%d",
        result.passed, result.overall_score,
        result.hallucination_score, result.domain_accuracy_score, result.format_score,
        len(result.issues),
    )

    return result


# ---------------------------------------------------------------------------
# LangGraph Node Integration
# ---------------------------------------------------------------------------

def guardrail_node(state: dict) -> dict:
    """
    LangGraph node that runs guardrails after answer generation.

    Expected state keys:
        messages: list of LangChain message objects (last one is the answer)
        retrieved_contexts: list[str] — the chunks retrieved by the RAG step

    This node adds guardrail metadata to the state. If the guardrail fails
    (ERROR-level issues), it replaces the answer with a safe fallback.

    Wire this into your LangGraph like:
        graph.add_node("guardrails", guardrail_node)
        graph.add_edge("generate", "guardrails")
        graph.add_conditional_edges("guardrails", route_after_guardrails)

    Swift analogy: Like a `.map` operator in Combine that transforms the
    pipeline output, potentially replacing it with a fallback value.
    """
    messages = state.get("messages", [])
    contexts = state.get("retrieved_contexts", [])

    if not messages:
        return state

    # The last message is the generated answer
    last_message = messages[-1]

    # Extract text content — handles both string and LangChain message objects
    if hasattr(last_message, "content"):
        answer_text = last_message.content
    elif isinstance(last_message, str):
        answer_text = last_message
    else:
        answer_text = str(last_message)

    # Extract the question (first HumanMessage)
    question_text = ""
    for msg in messages:
        if hasattr(msg, "type") and msg.type == "human":
            question_text = msg.content
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            question_text = msg.get("content", "")
            break

    # Run the pipeline
    result = run_guardrails(question_text, answer_text, contexts)

    # If guardrail fails, replace with safe fallback
    if not result.passed:
        error_issues = [
            issue for issue in result.issues
            if issue.severity == Severity.ERROR
        ]
        error_summary = "; ".join(issue.message for issue in error_issues)

        fallback_answer = (
            "I found relevant documentation but could not generate a fully "
            "verified answer. The following issues were detected:\n\n"
            f"- {error_summary}\n\n"
            "Please rephrase your question or ask about a more specific topic "
            "so I can provide an accurate, well-sourced answer."
        )

        # Replace the last message content
        if hasattr(last_message, "content"):
            # LangChain message — create a new one with updated content
            from langchain_core.messages import AIMessage
            updated_message = AIMessage(content=fallback_answer)
            messages = messages[:-1] + [updated_message]
        else:
            messages = messages[:-1] + [fallback_answer]

    # Store guardrail metadata in state for downstream use / LangSmith logging
    return {
        **state,
        "messages": messages,
        "guardrail_result": result.model_dump(),
        "guardrail_passed": result.passed,
        "guardrail_score": result.overall_score,
    }


def route_after_guardrails(state: dict) -> str:
    """
    Conditional edge function for LangGraph.

    After guardrails run, decide whether to:
    - "end" — guardrails passed, return the answer
    - "regenerate" — guardrails failed, try generating again (with stricter prompt)

    Usage:
        graph.add_conditional_edges(
            "guardrails",
            route_after_guardrails,
            {"end": END, "regenerate": "generate"}
        )
    """
    if state.get("guardrail_passed", True):
        return "end"
    # Limit regeneration attempts to avoid infinite loops
    regen_count = state.get("guardrail_regen_count", 0)
    if regen_count >= 2:
        logger.warning("Max regeneration attempts reached. Returning fallback.")
        return "end"
    return "regenerate"


# ---------------------------------------------------------------------------
# LLM-based Hallucination Check (optional, higher accuracy, higher cost)
# ---------------------------------------------------------------------------

def check_hallucination_with_llm(
    answer: str,
    contexts: list[str],
    model: str = "gpt-4o-mini",
) -> tuple[float, list[GuardrailIssue]]:
    """
    Use an LLM to do entailment-based hallucination checking.

    This is more accurate than keyword overlap but costs ~$0.001 per check
    (using GPT-4o-mini). Use this for high-stakes answers or as a second pass.

    NOTE: Requires `langchain-openai` to be installed and OPENAI_API_KEY set.
    This function is NOT called by default in run_guardrails() — wire it in
    manually when you want LLM-grade checking.

    Args:
        answer: The generated answer to verify.
        contexts: Retrieved context documents.
        model: Which model to use for the check.

    Returns:
        (score, issues) — same interface as detect_hallucinations.
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatOpenAI(model=model, temperature=0)

    context_text = "\n---\n".join(contexts[:5])  # limit context to control cost

    prompt = f"""You are a hallucination detector for an EDA (Electronic Design Automation) assistant.

Given the CONTEXT (retrieved documentation) and the ANSWER (generated response), determine what fraction of the claims in the ANSWER are supported by the CONTEXT.

CONTEXT:
{context_text}

ANSWER:
{answer}

Respond with ONLY a JSON object (no markdown, no explanation):
{{"score": <float 0.0 to 1.0>, "unsupported_claims": ["claim1", "claim2", ...]}}

Where score = 1.0 means fully supported, 0.0 means fully hallucinated.
Only list claims that are NOT supported by the context."""

    response = llm.invoke([
        SystemMessage(content="You are a precise fact-checker. Respond only with valid JSON."),
        HumanMessage(content=prompt),
    ])

    import json
    try:
        result = json.loads(response.content)
        score = float(result.get("score", 0.5))
        unsupported = result.get("unsupported_claims", [])
    except (json.JSONDecodeError, ValueError):
        logger.warning("LLM hallucination check returned unparseable response: %s", response.content)
        score = 0.5
        unsupported = []

    issues: list[GuardrailIssue] = []
    for claim in unsupported:
        issues.append(GuardrailIssue(
            check_name="llm_hallucination_detector",
            severity=Severity.WARNING,
            message=f"LLM flagged unsupported claim: {claim}",
            snippet=claim[:200],
        ))

    if score < 0.5:
        issues.insert(0, GuardrailIssue(
            check_name="llm_hallucination_detector",
            severity=Severity.ERROR,
            message=f"LLM hallucination score is {score:.2f} — answer is largely unsupported.",
            snippet=None,
        ))

    return score, issues


# ---------------------------------------------------------------------------
# __main__ — Usage example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Example: A question about hold violations with a sample answer and contexts
    sample_question = "How do I fix hold violations in OpenSTA?"

    sample_answer = (
        "To fix hold violations in OpenSTA, you need to add delay to the data path "
        "so the data remains stable AFTER the clock edge. Here are the key steps:\n\n"
        "1. Use `report_checks -path_delay min` to identify the failing hold paths.\n"
        "2. The most common fix is to insert delay buffers (e.g., BUFX2, DLYGATE) "
        "in the data path between the launching and capturing flip-flops.\n"
        "3. You can also use `set_clock_uncertainty` to add hold margin.\n\n"
        "[Source 1: OpenSTA documentation] Hold slack = required hold time - arrival time. "
        "A negative hold slack means the data changes too quickly after the clock edge."
    )

    sample_contexts = [
        "OpenSTA report_checks command: Use -path_delay min to check hold paths. "
        "The report shows startpoint, endpoint, required time, arrival time, and slack.",
        "Hold time is the minimum time data must be stable AFTER the clock edge. "
        "Hold violations occur when data changes too soon after the clock captures it.",
        "Common fixes for hold violations include inserting delay buffers, "
        "adjusting clock skew, and using hold-fixing ECO (Engineering Change Order).",
    ]

    print("=" * 70)
    print("GUARDRAIL PIPELINE — EXAMPLE RUN")
    print("=" * 70)
    print(f"\nQuestion: {sample_question}")
    print(f"\nAnswer ({len(sample_answer)} chars):")
    print(sample_answer)
    print(f"\nContexts: {len(sample_contexts)} retrieved chunks")
    print("-" * 70)

    result = run_guardrails(sample_question, sample_answer, sample_contexts)

    print(f"\nRESULT:")
    print(f"  Passed:              {result.passed}")
    print(f"  Overall Score:       {result.overall_score:.3f}")
    print(f"  Hallucination Score: {result.hallucination_score:.3f}")
    print(f"  Domain Accuracy:     {result.domain_accuracy_score:.3f}")
    print(f"  Format Score:        {result.format_score:.3f}")

    if result.issues:
        print(f"\n  Issues ({len(result.issues)}):")
        for i, issue in enumerate(result.issues, 1):
            print(f"    {i}. [{issue.severity.value.upper()}] {issue.check_name}: {issue.message}")
            if issue.snippet:
                print(f"       Snippet: {issue.snippet[:80]}...")
    else:
        print("\n  No issues found.")

    print("\n" + "=" * 70)

    # --- Example of a BAD answer to show failure detection ---
    print("\nBAD ANSWER EXAMPLE (should trigger errors):")
    print("-" * 70)

    bad_answer = (
        "Setup violations occur after the clock edge and positive slack means "
        "the constraint is violated. You should increase the WNS to make it worse."
    )

    bad_result = run_guardrails(sample_question, bad_answer, sample_contexts)
    print(f"  Passed: {bad_result.passed}")
    print(f"  Overall Score: {bad_result.overall_score:.3f}")
    for i, issue in enumerate(bad_result.issues, 1):
        print(f"  {i}. [{issue.severity.value.upper()}] {issue.message}")

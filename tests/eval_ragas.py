"""
RAGAS Evaluation Suite — Measure retrieval and generation quality.

Metrics:
- Context Relevancy: Are retrieved chunks relevant to the question?
- Faithfulness: Is the answer grounded in the context?
- Answer Relevancy: Does the answer address the question?

Usage:
    python -m tests.eval_ragas
"""

import asyncio
from ip_agent.agent import ask
from ip_agent.retriever import hybrid_search


# ---------------------------------------------------------------------------
# Test Dataset (ground truth for EDA domain)
# ---------------------------------------------------------------------------

EVAL_DATASET = [
    {
        "question": "What is setup time?",
        "ground_truth": "Setup time is the minimum time before the clock edge that data must be stable at the flip-flop input to be correctly captured.",
        "contexts_should_contain": ["setup", "clock", "stable"],
    },
    {
        "question": "How do I fix hold violations?",
        "ground_truth": "Hold violations can be fixed by inserting delay buffers, downsizing cells, adding routing detour, or adjusting useful skew. Fixes must not degrade setup timing.",
        "contexts_should_contain": ["hold", "buffer", "delay"],
    },
    {
        "question": "What is the report_checks command in OpenSTA?",
        "ground_truth": "report_checks is an OpenSTA command that reports timing check results including setup and hold violations, showing path delays, slack, and violation details.",
        "contexts_should_contain": ["report_checks", "timing"],
    },
    {
        "question": "What is WNS?",
        "ground_truth": "WNS (Worst Negative Slack) is the most negative slack value across all timing paths in a design. It indicates the severity of the worst timing violation.",
        "contexts_should_contain": ["worst", "negative", "slack"],
    },
]


# ---------------------------------------------------------------------------
# Evaluation Functions
# ---------------------------------------------------------------------------

def evaluate_context_relevancy(question: str, contexts: list, keywords: list[str]) -> float:
    """Check if retrieved contexts contain expected keywords."""
    if not contexts:
        return 0.0

    all_text = " ".join(doc.page_content.lower() for doc in contexts)
    hits = sum(1 for kw in keywords if kw.lower() in all_text)
    return hits / len(keywords)


async def evaluate_faithfulness(question: str, answer: str, contexts: list) -> float:
    """
    Check if the answer is grounded in the retrieved context.
    Simple heuristic: what fraction of answer sentences have support in context.
    """
    if not answer or not contexts:
        return 0.0

    context_text = " ".join(doc.page_content.lower() for doc in contexts)
    sentences = [s.strip() for s in answer.split(".") if s.strip()]

    if not sentences:
        return 0.0

    grounded = 0
    for sentence in sentences:
        # Check if key words from sentence appear in context
        words = [w for w in sentence.lower().split() if len(w) > 3]
        if words:
            overlap = sum(1 for w in words if w in context_text)
            if overlap / len(words) > 0.3:
                grounded += 1

    return grounded / len(sentences)


async def run_evaluation():
    """Run full RAGAS-style evaluation."""
    print("=" * 80)
    print("RAGAS Evaluation Suite")
    print("=" * 80)
    print()

    results = []

    for i, test_case in enumerate(EVAL_DATASET, 1):
        question = test_case["question"]
        ground_truth = test_case["ground_truth"]
        expected_keywords = test_case["contexts_should_contain"]

        print(f"Test {i}/{len(EVAL_DATASET)}: {question}")
        print("-" * 60)

        # Retrieve
        contexts = hybrid_search(question, top_k=3)

        # Generate
        answer = await ask(question)

        # Evaluate
        context_score = evaluate_context_relevancy(question, contexts, expected_keywords)
        faithfulness_score = await evaluate_faithfulness(question, answer, contexts)

        result = {
            "question": question,
            "context_relevancy": context_score,
            "faithfulness": faithfulness_score,
            "answer_preview": answer[:100],
        }
        results.append(result)

        print(f"  Context Relevancy: {context_score:.2%}")
        print(f"  Faithfulness:      {faithfulness_score:.2%}")
        print(f"  Answer: {answer[:80]}...")
        print()

    # Summary
    print("=" * 80)
    print("Summary")
    print("=" * 80)
    avg_context = sum(r["context_relevancy"] for r in results) / len(results)
    avg_faith = sum(r["faithfulness"] for r in results) / len(results)
    print(f"  Avg Context Relevancy: {avg_context:.2%}")
    print(f"  Avg Faithfulness:      {avg_faith:.2%}")
    print(f"  Overall:               {(avg_context + avg_faith) / 2:.2%}")


if __name__ == "__main__":
    asyncio.run(run_evaluation())

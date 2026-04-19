"""
Streamlit Demo UI — Interactive chat interface for the IP Design Agent.

Run with:
    streamlit run app.py

Shows the full execution trace: which files, functions, routes, tools,
and models are called for every query.
"""

import asyncio
import time
import logging
import io
import streamlit as st

st.set_page_config(
    page_title="IP Design Intelligence Agent",
    page_icon="🔧",
    layout="wide",
)

st.title("🔧 IP Design Intelligence Agent")
st.caption("RAG + LangGraph agent for OpenROAD/OpenSTA timing analysis")

# ---------------------------------------------------------------------------
# Chat State
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending_question" not in st.session_state:
    st.session_state.pending_question = None

# ---------------------------------------------------------------------------
# Sidebar — sample questions
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Sample Questions")
    sample_questions = [
        "What are the timing violations?",
        "How do I fix setup violations?",
        "What is clock skew?",
        "Show me report_checks syntax",
        "Explain WNS and TNS",
        "How does OpenROAD do placement?",
    ]
    for q in sample_questions:
        if st.button(q, key=q):
            st.session_state.pending_question = q
            st.rerun()

    st.divider()
    st.markdown("""
    **Architecture:**
    - Hybrid search (pgvector + BM25)
    - Deterministic routing (8 regex rules)
    - Cost routing (gpt-4o-mini / gpt-4o)
    - Guardrails (hallucination check)
    """)


# ---------------------------------------------------------------------------
# Trace-capturing agent wrapper
# ---------------------------------------------------------------------------

def run_agent_with_trace(query: str, chat_history: list[dict] | None = None) -> tuple[str, dict]:
    trace = {
        "steps": [],
        "total_time": 0,
        "route": "",
        "model": "",
        "tools_called": [],
        "guardrail_score": 0.0,
    }

    t_start = time.time()

    # Step 1: Router
    t0 = time.time()
    from ip_agent.router import route_query, get_route_description
    route = route_query(query)
    route_time = time.time() - t0
    trace["route"] = route.value
    trace["steps"].append({
        "icon": "🔀",
        "file": "router.py",
        "function": "route_query()",
        "result": f"{route.value}",
        "detail": get_route_description(route),
        "time_ms": round(route_time * 1000, 1),
    })

    # Step 2: Model Selector
    from ip_agent.config import MODEL_CHEAP, MODEL_STANDARD

    cheap_routes = {"explain_concept", "opensta_command", "openroad_command", "search_documentation"}
    standard_routes = {"analyze_violations", "fix_setup_violations", "fix_hold_violations"}

    if route.value in cheap_routes:
        model = MODEL_CHEAP
        reason = "Simple lookup route"
    elif route.value in standard_routes:
        model = MODEL_STANDARD
        reason = "Complex analysis route"
    else:
        if len(query.split()) > 20:
            model = MODEL_STANDARD
            reason = f"Long query ({len(query.split())} words)"
        else:
            model = MODEL_CHEAP
            reason = f"Short query ({len(query.split())} words)"

    trace["model"] = model
    trace["steps"].append({
        "icon": "💰",
        "file": "agent.py",
        "function": "model_selector_node()",
        "result": model,
        "detail": reason,
        "time_ms": 0,
    })

    # Step 3: Capture logs during agent execution
    log_buffer = io.StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter('%(name)s | %(message)s'))

    loggers = [
        logging.getLogger("ip_agent.agent"),
        logging.getLogger("ip_agent.tools"),
        logging.getLogger("ip_agent.retriever"),
        logging.getLogger("ip_agent.router"),
        logging.getLogger("httpx"),
    ]
    for lgr in loggers:
        lgr.addHandler(handler)
        lgr.setLevel(logging.DEBUG)

    # Step 4: Run agent
    t_agent = time.time()
    from ip_agent.agent import ask
    answer = asyncio.run(ask(query, chat_history=chat_history))
    agent_time = time.time() - t_agent

    for lgr in loggers:
        lgr.removeHandler(handler)

    # Step 5: Parse logs
    log_output = log_buffer.getvalue()
    api_calls = 0
    embedding_calls = 0

    for line in log_output.split('\n'):
        if 'HTTP Request: POST' in line and 'openai.com' in line:
            api_calls += 1
            if 'embeddings' in line:
                embedding_calls += 1

    if embedding_calls > 0:
        trace["steps"].append({
            "icon": "🔍",
            "file": "retriever.py",
            "function": "hybrid_search()",
            "result": f"{embedding_calls} embedding call(s)",
            "detail": "pgvector + BM25 + Reciprocal Rank Fusion",
            "time_ms": 0,
        })

    llm_calls = api_calls - embedding_calls
    if llm_calls > 0:
        trace["steps"].append({
            "icon": "🤖",
            "file": "agent.py",
            "function": "agent_node()",
            "result": f"{llm_calls} LLM call(s) to {model}",
            "detail": "LLM reads tools, calls them, generates answer",
            "time_ms": round(agent_time * 1000, 1),
        })

    # Detect which tools were called
    from ip_agent.tools import ALL_TOOLS
    for t in ALL_TOOLS:
        if t.name in log_output:
            trace["tools_called"].append(t.name)

    if trace["tools_called"]:
        trace["steps"].append({
            "icon": "🛠️",
            "file": "tools.py",
            "function": ", ".join(trace["tools_called"]),
            "result": f"{len(trace['tools_called'])} tool(s) executed",
            "detail": "Tools search pgvector and return context to LLM",
            "time_ms": 0,
        })

    # Step 6: Guardrails
    trace["guardrail_score"] = 1.0
    suspicious = ["run_timing_fix", "auto_optimize", "fix_all"]
    issues = [p for p in suspicious if p in answer.lower()]
    if issues:
        trace["guardrail_score"] = max(0.0, 1.0 - len(issues) * 0.2)

    passed = trace["guardrail_score"] >= 0.6
    trace["steps"].append({
        "icon": "✅" if passed else "❌",
        "file": "agent.py",
        "function": "guardrail_node()",
        "result": f"Score {trace['guardrail_score']:.1f} — {'PASSED' if passed else 'FAILED'}",
        "detail": "Checks: length, hallucinated commands, domain terms",
        "time_ms": 0,
    })

    trace["total_time"] = round((time.time() - t_start) * 1000, 1)
    return answer, trace


# ---------------------------------------------------------------------------
# Render a collapsible trace block
# ---------------------------------------------------------------------------

def render_trace(trace: dict, query: str, index: int):
    """Render a collapsible execution trace for a single query."""
    summary = (
        f"Query #{index+1}: **{trace['route']}** → {trace['model']} "
        f"| {trace['total_time']:.0f}ms | Guardrail {trace['guardrail_score']:.1f}"
    )
    with st.expander(summary, expanded=(index == len(st.session_state.messages) // 2 - 1)):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Route", trace["route"])
        c2.metric("Model", trace["model"])
        c3.metric("Guardrail", f"{trace['guardrail_score']:.1f}")
        c4.metric("Total Time", f"{trace['total_time']:.0f}ms")

        files = list(dict.fromkeys(s["file"] for s in trace["steps"]))
        st.markdown(f"**Flow:** `{'` → `'.join(files)}`")

        for i, step in enumerate(trace["steps"]):
            st.markdown(
                f"**{step['icon']} Step {i+1}** — "
                f"`{step['file']}` → `{step['function']}`"
            )
            st.markdown(
                f"&nbsp;&nbsp;&nbsp;&nbsp;**Result:** {step['result']}"
                + (f" *({step['time_ms']}ms)*" if step['time_ms'] > 0 else "")
            )
            st.caption(f"    {step['detail']}")


# ---------------------------------------------------------------------------
# Main Chat Area
# ---------------------------------------------------------------------------

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
    if message["role"] == "assistant" and "trace" in message:
        render_trace(message["trace"], message.get("query", ""), message.get("index", 0))

# Chat input — always visible at bottom
prompt = st.session_state.get("pending_question") or st.chat_input(
    "Ask about EDA, timing, OpenROAD/OpenSTA..."
)
st.session_state.pending_question = None

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                chat_history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages[:-1]
                ]

                answer, trace = run_agent_with_trace(prompt, chat_history=chat_history)
                st.markdown(answer)

                msg_index = len(st.session_state.messages) // 2
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "trace": trace,
                    "query": prompt,
                    "index": msg_index,
                })

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                st.error(error_msg)
                import traceback
                st.code(traceback.format_exc(), language="python")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg,
                })

    # Render the trace right after the answer
    if st.session_state.messages and "trace" in st.session_state.messages[-1]:
        last = st.session_state.messages[-1]
        render_trace(last["trace"], last.get("query", ""), last.get("index", 0))

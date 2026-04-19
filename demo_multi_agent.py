"""
Demo: Multi-Agent Timing Closure

This script demonstrates the 3-agent orchestration pattern:
    Timing Agent → DRC Agent → Physical Agent → Unified Report + ECO Script

Run:
    python demo_multi_agent.py

This is what you show in the interview to demonstrate:
1. Multi-agent coordination (LangGraph orchestrator)
2. Cross-domain awareness (timing + DRC + physical)
3. Production pattern (A2A-style agent delegation)
4. Real EDA output (Tcl ECO commands)
"""

import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)


async def main():
    print("=" * 70)
    print("  MULTI-AGENT TIMING CLOSURE DEMO")
    print("  3 Specialist Agents Coordinating via LangGraph")
    print("=" * 70)
    print()
    print("Scenario: Broadcom engineer asks:")
    print('  "Close timing on block_alu without introducing DRC violations"')
    print()
    print("Agents involved:")
    print("  1. Timing Agent  — reads timing reports, finds violations")
    print("  2. DRC Agent     — reads DRC reports, maps congested regions")
    print("  3. Physical Agent — generates ECO fixes (DRC-aware)")
    print()
    print("-" * 70)
    print("Running orchestrator...")
    print("-" * 70)
    print()

    from ip_agent.orchestrator import orchestrate_timing_closure

    result = await orchestrate_timing_closure("block_alu")

    print()
    print(result)
    print()
    print("-" * 70)
    print("Demo complete.")
    print()
    print("Key takeaways for interview:")
    print("  - 3 agents coordinated via LangGraph StateGraph")
    print("  - Each agent is a specialist (like PrimeTime, ICC2, ICV)")
    print("  - Context flows between agents (DRC constraints → Physical fixes)")
    print("  - Output includes executable Tcl ECO commands")
    print("  - Same pattern scales to A2A over HTTP (api.py /a2a endpoint)")
    print("-" * 70)


if __name__ == "__main__":
    asyncio.run(main())

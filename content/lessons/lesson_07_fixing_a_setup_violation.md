---
id: 7
title: "Fix your first setup violation"
duration_min: 30
requires_runner: true
summary: "Use the 3-agent orchestrator to get an ECO Tcl script, apply it, and watch WNS improve."
actions:
  - type: open_timing_closure
    label: "Open the Timing Closure lab"
  - type: run_tcl
    design: gcd
    pdk: sky130hd
    command: "report_checks -path_delay max -group_count 5"
    label: "Re-check timing after ECO"
---

## What an ECO is

**ECO** = Engineering Change Order. It's a *targeted* modification to the placed/routed design that fixes a specific problem without re-running the whole flow. ECOs are how real chips close timing in the final week before tapeout.

Common setup-violation ECOs:

- **size_cell** — swap a slow cell for a faster, bigger drive strength.
- **insert_buffer** — add a buffer to reshape a long wire.
- **swap_vt** — move a cell from HVT (slow, low-leakage) to LVT (fast, leaky).
- **resynthesize_path** — a logic-level rewrite (riskier; avoid if possible).

## Why we use 3 agents, not 1

A bad ECO is worse than no ECO. If you upsize a cell in a congested region, you break DRC. If you insert a buffer in a hold-critical region, you break hold. The 3-agent orchestrator checks across three domains **before** writing a single command:

1. **Timing Agent** — finds the WNS path, ranks the cells by delay contribution.
2. **DRC Agent** — checks congestion and spacing around the target region.
3. **Physical Agent** — only then decides what ECO command is safe.

This is how senior PD engineers actually think. The agents just make it explicit.

## The workflow

1. Open the **🔧 Timing Closure** tab (button below opens it).
2. Pick a sample block (gcd-variants or one of the 15 prepared blocks).
3. Click **Run Timing Closure**.
4. Watch all 3 agents run in sequence. Read their reasoning.
5. Download the generated Tcl file, or copy the commands.
6. Come back to the Lab tab and apply them one at a time.
7. Re-run `report_checks` to confirm WNS improved.

## What "good" looks like

A good ECO on gcd-style designs moves WNS from ~ −0.14 ns to ≥ 0 ns in 2–3 commands. If it takes 30 commands, the fix is shotgunning — back up and reconsider.

If WNS gets worse after the ECO, **undo** and try a different cell on the same path. Upsizing isn't always the answer; sometimes a buffer insertion or a Vt swap is better.

## Questions to answer

1. Which cell did the Physical Agent decide to change? Why that cell and not the previous one in the path?
2. Did the DRC Agent's congestion report change the recommendation? (If the region was green, the agent might pick the most aggressive fix; if amber, it'll be conservative.)
3. After applying the ECO, what's your new WNS and TNS?

## Try it

Click the first button to jump to the Timing Closure tab. When you have the ECO script, come back and click the second button to verify timing has improved.

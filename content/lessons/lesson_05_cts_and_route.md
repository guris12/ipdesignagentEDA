---
id: 5
title: "CTS and routing"
duration_min: 30
requires_runner: true
summary: "Build the clock tree and route every wire. This is the longest stage; expect 5–10 minutes on gcd."
actions:
  - type: run_stage
    design: gcd
    pdk: sky130hd
    stage: cts
    label: "Run CTS (clock tree synthesis)"
  - type: run_stage
    design: gcd
    pdk: sky130hd
    stage: route
    label: "Run routing"
---

## Clock tree synthesis (CTS)

Until CTS, your "clock" is an ideal, zero-delay, zero-skew wire. That fantasy does not exist in silicon. **CTS** builds a real, buffered clock tree that:

- Drives every flop in the design.
- Balances skew (arrival time spread across endpoints).
- Keeps insertion delay (total tree depth) manageable.

The tool inserts **clock buffers** (CTS-specific cells like `sky130_fd_sc_hd__clkbuf_*`) along the way. You'll see the buffer count jump by 50–200 on gcd after CTS finishes.

## What changes after CTS

Before CTS the timing report uses an ideal clock. After CTS:
- Every flop has a real arrival time for its clock edge.
- Setup slack often **gets worse** because the clock arrives slightly later at the endpoint than it did under "ideal".
- Hold violations become real for the first time.

This is why you should never declare timing closed before CTS.

## Routing

**Routing** connects every net with real metal wires on real metal layers. Two phases:

1. **Global routing** — plans rough paths through a coarse grid. Identifies congestion.
2. **Detailed routing** — lays real segments on real layers, checking DRC every step.

You'll see the log count DRC violations as routing progresses. A clean design ends with **0 DRC violations** after detailed routing. A busy design may need multiple iterations (routing → detailed route → repair loop).

## What to watch for

- **CTS insertion delay** — usually 0.2–0.5 ns on gcd. Higher = deeper tree = more skew risk.
- **Clock skew** — the spread of clock arrival times. Should be under 100 ps on gcd.
- **Routing DRC count** — should go to 0. If it plateaus above 0, the design is unrouteable with current settings.

## Order matters again

Run **CTS first**, then **routing**. If you skip CTS and route directly, the router has no clock-tree cells to route around and your final timing will be a lie.

## Questions to answer

1. How many clock buffers did CTS insert?
2. Did setup slack improve, stay the same, or get worse after CTS? (It often gets worse — that's normal.)
3. Did routing finish with 0 DRC violations?

## Try it

Run CTS, then routing. Total time on the runner: ~6–8 minutes for gcd. This is the longest chain of stages in your lesson track — be patient, and read the logs as they stream.

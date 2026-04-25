---
id: 2
title: "Reading a real timing report"
duration_min: 15
requires_runner: false
summary: "Open the sample timing report shipped with this project and find the violations yourself. No tool run needed — the .rpt is already here."
actions:
  - type: ask_agent
    question: "What are the timing violations in the sample setup report?"
    label: "Ask the agent to walk through the sample report"
---

## The sample report

This project ships with `data/sample_reports/setup_report.rpt`. It's a real OpenSTA-style setup report with **three paths**: one meets timing, two violate. Your job in this lesson is to read it without any tool help.

## Step 1 — find the summary

Every timing report opens with a summary block. It tells you:

- How many paths were analyzed.
- How many violate.
- WNS and TNS for this corner and this path group.

Look for lines like:
```
WNS  = -0.14 ns
TNS  = -0.19 ns
Paths analyzed: 3
Paths failing: 2
```

If you see `WNS = +0.XX`, everything meets. Close the report and move on. If WNS is negative, scroll down to the individual paths.

## Step 2 — follow the worst path

The report lists paths from most-violated to least-violated. The **first path** is always the WNS path.

Work down the path with three questions:
1. **Startpoint and endpoint** — which flops is the data going between?
2. **Which cells add the most delay?** Look at the `Incr` column. One or two cells usually dominate.
3. **Where is the data arrival time vs required time?** That difference is the slack.

## Step 3 — is it a single bad cell or the whole path?

If one cell contributes 40% of the delay, that's your fix target — upsize it or swap to a faster Vt. If delay is spread evenly across 12 cells, the logic is too deep; you need buffer restructuring or pipelining.

## Step 4 — scroll to the second violating path

Paths that share cells with the WNS path often move together — fix one, the other gets better (or worse). Paths with no overlap need separate fixes. Note the overlap before planning ECO.

## Common traps

- **"I see slack −0.02 ns, that's fine."** No. Any negative slack is a violation. Marginal violations in one corner become catastrophic in another.
- **Confusing setup with hold reports.** Setup reports check `max` path delay; hold reports check `min`. An ECO that fixes setup can create hold violations — always check both.
- **Only looking at WNS.** TNS tells you whether this is a local fix or a whole-block restructure.

## Try it

Click the button below. The agent will walk through `setup_report.rpt` and point out WNS, TNS, and the worst two paths — so you can compare your own reading against the agent's.

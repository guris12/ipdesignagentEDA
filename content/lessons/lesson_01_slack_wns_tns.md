---
id: 1
title: "Slack, WNS, and TNS — the vocabulary of timing"
duration_min: 15
requires_runner: false
summary: "Before you run a single tool, understand what a timing report is actually telling you. This lesson has no tool steps — only the three numbers every PD engineer lives with."
actions: []
---

## Why this lesson exists

Every timing report you will ever read boils down to three numbers: **slack**, **WNS**, and **TNS**. If you can read those three, you can read a timing report. If you can't, no tool will help you.

## Slack — the headline

**Slack** is the time budget on one path.

> slack = required time − arrival time

- `slack > 0` → data arrives **before** the clock edge. The path meets timing.
- `slack < 0` → data arrives **after** the clock edge. **Violation.** The chip will fail at this frequency.

A path with slack of `+0.20 ns` has 200 picoseconds of headroom. A path with slack of `−0.14 ns` is 140 picoseconds too slow — it's broken.

## WNS — the worst path

**WNS (Worst Negative Slack)** is the single most-violated path in the design. It is the slack of the one critical path.

> WNS = min(slack) over all violating paths

If WNS is `−0.14 ns`, your chip cannot close timing at this frequency. You must either:

1. Fix the path (upsize cells, insert buffers, restructure logic), or
2. Slow the clock down.

## TNS — the total pain

**TNS (Total Negative Slack)** is the sum of all negative slacks. It measures *how much work is left*, not *how bad the worst path is*.

> TNS = Σ (slack) over all paths where slack < 0

- WNS = −0.05 ns, TNS = −0.05 ns → **one** marginal violation.
- WNS = −0.05 ns, TNS = −120 ns → **thousands** of marginal violations. Much worse, even though WNS looks identical.

## The mental model

Think of slack as the balance on a single credit card, WNS as your most overdrawn card, and TNS as your total credit-card debt across every card. You need both numbers. Fixing only WNS without watching TNS means the next worst path pops up immediately. Fixing TNS by adding 500 buffers everywhere will break DRC and power.

## What you'll see in a real .rpt file

```
Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)
Endpoint:   reg_b (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type:  max

  Point                                    Incr    Path
  ─────────────────────────────────────────────────────
  clock clk (rise edge)                    0.00    0.00
  clock source latency                     0.12    0.12
  reg_a/CK (DFF_X1)                        0.00    0.12 r
  reg_a/Q (DFF_X1)                         0.25    0.37 f
  U1/ZN (NAND2_X1)                         0.11    0.48 r
  ...
  reg_b/D (DFF_X1)                         0.00    1.04 r
  data arrival time                                1.04

  clock clk (rise edge)                    0.90    0.90
  ...
  data required time                               0.90

  slack (VIOLATED)                                -0.14
```

The `data arrival time` minus the `data required time` is your slack. Everything above it is just accounting — which cells added how much delay, and why this path is critical.

## You're done when

You can read `slack (VIOLATED) -0.14` and immediately say out loud:
- "This path is 140 ps too slow."
- "If this is the worst path, WNS = −0.14 ns."
- "I won't know how many paths violate until I read the summary."

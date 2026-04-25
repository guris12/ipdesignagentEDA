---
id: 8
title: "Why one corner isn't enough"
duration_min: 20
requires_runner: false
summary: "You passed timing at one corner. That's not closure. A quick tour of what multi-corner, multi-mode (MCMM) analysis actually means."
actions:
  - type: ask_agent
    question: "Explain multi-corner multi-mode (MCMM) timing analysis and why setup fixes in ss corner can break hold in ff corner"
    label: "Ask the agent for the multi-corner deep dive"
---

## The lie you've been told so far

For lessons 3 through 7, you've analyzed timing at one corner — probably `tt` (typical voltage, typical temperature, typical process). Real silicon does not run at the typical corner. Real silicon runs across a range of voltage, temperature, and process variation.

A chip that closes timing only at `tt` is a chip that fails in the field.

## What a "corner" actually is

A corner is a combination of:

- **Process**: fast (ff), typical (tt), slow (ss) transistors.
- **Voltage**: high or low supply.
- **Temperature**: −40 °C, 25 °C, 125 °C, …
- **RC (interconnect)**: c-worst, c-best, rc-worst, etc.

So `ss_125C_0p72v_cworst` is *one* corner. A real sign-off flow checks **8–30** corners.

## Which corners check what

| Corner | Primary risk |
|---|---|
| `ss` (slow-slow, low voltage, high temp) | **Setup** violations. Transistors are slow, so data barely reaches the endpoint in time. |
| `ff` (fast-fast, high voltage, low temp) | **Hold** violations. Transistors are fast, so data races past the flop. |
| `tt` | Typical. Most reports look good here even when other corners fail. |

## The dangerous coupling

When you insert a buffer to fix **setup** at `ss`, you also slow the path down at `ff`. That might push a previously-passing hold path at `ff` into violation. This is why naive ECO scripts that fix one corner at a time often oscillate — every fix creates a new violation somewhere else.

The only safe ECOs are **cross-corner aware**: every proposed fix is simulated against all relevant corners before being applied. That's the problem the planned MCMM Timing Closure Agent (v2) will solve.

## Modes add another axis

A **mode** is a functional state of the chip — normal operation, scan test mode, low-power idle, DFT mode. Different modes have different clock frequencies and different active logic. A path that's critical in test mode may not even switch in normal operation, and vice versa.

Real sign-off: N corners × M modes = every one of those MxN combinations must pass.

## The takeaway

You now understand the shape of the problem. Closing timing on one corner of gcd in lessons 3–7 was a valid learning exercise, but it's not what an industrial flow does. Every block you'll ever work on in a real job is analyzed across many corners and modes.

## Where to go from here

- Re-run lesson 6's `report_checks` at `ss` and `ff` corners instead of `tt`. Compare WNS.
- Read the MCMM Timing Closure Agent spec in the project docs — that's the planned v2 upgrade.
- Ask the agent below for a deeper dive; it'll walk through an ss-setup / ff-hold conflict example.

## You're done

Congratulations — you've gone from *what is slack?* to *why multi-corner STA is non-negotiable* in eight lessons. That's roughly the first month of real physical-design onboarding at any company.

Next: pick a bigger design (ibex), re-run the full flow, and see how the numbers change when the cell count goes from 400 to 15,000.

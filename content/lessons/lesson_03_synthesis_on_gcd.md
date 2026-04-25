---
id: 3
title: "Run synthesis on GCD"
duration_min: 20
requires_runner: true
summary: "Your first real OpenROAD run. Synthesize the GCD design against the sky130hd PDK and read the synthesis report."
actions:
  - type: run_stage
    design: gcd
    pdk: sky130hd
    stage: synth
    label: "Run synthesis on gcd + sky130hd"
---

## What synthesis does

**Synthesis** turns Verilog RTL into a gate-level netlist mapped to your PDK's standard-cell library. In one sentence: it picks which physical cells implement each piece of logic.

Inputs:
- Verilog RTL (e.g. `gcd.v`)
- Timing constraints (SDC file — clock period, input/output delays)
- A standard cell library for the target PDK (sky130hd here)

Output:
- A gate-level netlist (`.v`) where every `and2`, `or3`, `dff` is now a specific library cell like `sky130_fd_sc_hd__and2_1`.
- Initial area and timing estimates.

## Why GCD first

`gcd` (greatest common divisor) is **tiny** — about 400 cells once synthesized. On our shared runner it finishes in under a minute. You'll watch the log stream in real time, which makes the abstract word "synthesis" concrete.

## What you'll watch for

When the stage starts, tail the log. You'll see Yosys (the synthesis engine) do:

1. **Parse** — read the Verilog.
2. **Elaborate** — expand modules, parameters, generates.
3. **Optimize** — constant propagation, FSM recoding, dead-code removal.
4. **Technology mapping** — map generic gates to sky130hd cells.
5. **Report** — print area, cell count, estimated timing.

You will see lines like:
```
Number of wires:         412
Number of cells:         398
  sky130_fd_sc_hd__and2_1   47
  sky130_fd_sc_hd__or2_1    32
  sky130_fd_sc_hd__dfxtp_1  18
  ...
```

## Questions to answer after the run

When the stage finishes and the metrics panel populates, write down:

1. **Cell count?** (Expect ~400 for gcd.)
2. **Area (µm²)?**
3. **Did any paths already look tight?** Synthesis gives only an estimate — real timing comes after place and route.

## Try it

Press the run button below. The runner will execute `make DESIGN_CONFIG=designs/sky130hd/gcd/config.mk synth`. Watch the log stream. When it says `DONE`, come back here.

If the runner is busy (someone else is in their slot), you'll see a queue banner on the Lab tab. Wait for your turn — sessions are capped at 20 minutes each.

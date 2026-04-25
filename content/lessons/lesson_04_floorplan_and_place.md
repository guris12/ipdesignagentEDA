---
id: 4
title: "Floorplan and placement"
duration_min: 25
requires_runner: true
summary: "Turn the netlist from lesson 3 into a physical layout. Create the die, place the cells, see where they landed."
actions:
  - type: run_stage
    design: gcd
    pdk: sky130hd
    stage: floorplan
    label: "Run floorplan"
  - type: run_stage
    design: gcd
    pdk: sky130hd
    stage: place
    label: "Run placement"
---

## What floorplan does

**Floorplan** decides:
- Die size and core area.
- Where the I/O pins go.
- Where macros (RAMs, analog IP) sit.
- Power and ground rings around the core.

It's the empty stadium before the players walk in. Get this wrong and nothing later can save you — you'll have no room to route or the clock tree will span the whole die.

## What placement does

**Placement** drops every standard cell somewhere inside the core area. The placer optimizes for:
- **Wirelength** (short nets = lower delay, less power).
- **Timing** (critical-path cells close together).
- **Density** (cells spread evenly, no hot spots).
- **Congestion** (no region so full that routing can't finish).

## The key output: a .def file

After placement, you get a **DEF** (Design Exchange Format) file listing every cell's coordinates. This is the first time you can see a physical chip instead of an abstract netlist. Later in lesson 5 you'll open the GUI and look at this layout directly.

## What to watch in the logs

Floorplan logs are short. You'll see die size, core utilization target, I/O ring setup. Placement logs are longer and more interesting:

```
[INFO GPL-0002] Iteration: 45   HPWL: 412304  Overflow: 0.23
[INFO GPL-0002] Iteration: 46   HPWL: 408991  Overflow: 0.19
[INFO GPL-0002] Iteration: 47   HPWL: 405773  Overflow: 0.15
```

**HPWL** = half-perimeter wirelength. It should decrease each iteration. **Overflow** measures how "packed" the densest region is; the placer keeps iterating until overflow drops below a target.

## Questions to answer

1. What core utilization did floorplan set? (Typical range: 50–70%.)
2. After placement, did HPWL converge or stall?
3. Did the log mention any over-congested regions?

## Order matters

You must run **floorplan first**, then **placement**. The run buttons below are in the right order. If you skip floorplan, placement will fail because there's no die to place into.

## Try it

Click "Run floorplan", wait for `DONE`, then click "Run placement". Total time on the runner: ~3 minutes for gcd.

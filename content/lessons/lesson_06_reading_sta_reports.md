---
id: 6
title: "Reading the post-route STA report"
duration_min: 20
requires_runner: true
summary: "Run the final static timing analysis on the routed design and compare it against the post-synth estimate. Where did the real violations come from?"
actions:
  - type: run_stage
    design: gcd
    pdk: sky130hd
    stage: finish
    label: "Run finish (final STA + reports)"
  - type: run_tcl
    design: gcd
    pdk: sky130hd
    command: "report_checks -path_delay max -format full_clock_expanded"
    label: "report_checks (max paths, full clock expansion)"
---

## Why a post-route STA is different

Every number you've read so far was an estimate based on wire-load models. The post-route STA uses the **real** parasitics extracted from the actual wire geometry — resistance, capacitance, coupling. This is the first report that matches what silicon will do.

Two things typically move:

1. **Setup slack gets worse.** Real wire delay is usually higher than the estimate used at placement.
2. **Hold slack becomes real.** Before routing, hold was approximate; now it's exact.

## The `report_checks` command

In OpenSTA, `report_checks` is the workhorse. Key flags:

- `-path_delay max` — setup (longest paths).
- `-path_delay min` — hold (shortest paths).
- `-format full_clock_expanded` — show every cell and clock edge, not just the summary.
- `-group_count 10` — show the top N worst paths.
- `-endpoint_count 1` — limit to one path per endpoint (de-duplicate shared endpoints).

You'll run one of these yourself in the action below.

## The comparison

Pull up your numbers from lesson 3 (post-synth WNS/TNS) and compare against this lesson's post-route WNS/TNS. Questions to answer:

1. Did WNS get worse? By how much?
2. Did TNS grow? If yes, by 2x or by 20x? (2x is normal. 20x means something is wrong — maybe the clock tree inflated insertion delay.)
3. Are the WNS paths the same startpoint/endpoint as they were post-synth? If yes, the bottleneck is a logic issue. If the new WNS path is different, routing wire delay dominated.

## Hold violations

After route, you'll often see hold violations for the first time. Hold means data arrived **too fast** — the next flop captured it before it was supposed to. Fix: insert hold buffers, or rely on slower-than-expected routing delay. OpenROAD's finish stage typically runs a hold-fix pass automatically.

## The "is this chip shippable" mental checklist

Before closing timing on a block, confirm all of:
- [ ] WNS ≥ 0 at all analysis corners.
- [ ] TNS ≥ 0 at all analysis corners.
- [ ] DRC count = 0.
- [ ] Hold violations = 0.
- [ ] Clock skew within spec (usually < 100 ps).
- [ ] Utilization < 85% (room for ECO).

If any one is red, you're not done.

## Try it

Click **Run finish** first. When it's done, click the second button to run `report_checks` manually. Read both sets of numbers.

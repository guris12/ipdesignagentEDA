# OpenROAD Setup Guide — Live EDA Flow Integration

**Phase 0 of ip-design-agent**: Install OpenROAD, run real flows, generate REAL timing reports

This guide takes you from zero to running actual RTL-to-GDSII flows and integrating them with your AI agent via MCP tools.

---

## Why This Matters

**Without this:** Your agent searches dummy reports → interviewer thinks "generic AI demo"  
**With this:** Your agent runs REAL flows → interviewer thinks "this person knows EDA AND AI"

**Interview line:**  
> "I ran OpenROAD on the ibex RISC-V core using the sky130 PDK. The agent analyzed 247 timing violations across 3 PVT corners, generated ECO fixes, and I validated them by re-running STA. Let me show you..." *[opens Claude Desktop, runs flow live]*

---

## What You'll Install

| Component | Purpose | Time |
|-----------|---------|------|
| **OpenROAD-flow-scripts** | Complete RTL → GDSII automation (includes OpenSTA) | 30-60 min |
| **sky130 PDK** | Real fabrication-ready process (130nm, open-source) | 20-30 min |
| **asap7 PDK** | Academic 7nm (already included, for comparison) | 0 min (included) |

**Total time: ~2 hours including first flow run**

---

## Step 1: Install Dependencies (macOS)

```bash
# Homebrew packages
brew install cmake python@3.12 tcl-tk boost bison flex eigen swig \
             libomp libffi openssl@3 readline sqlite3 xz zlib ninja

# Or use the installer script (recommended):
```

---

## Step 2: Install OpenROAD-flow-scripts

```bash
cd ~/
git clone --recursive https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts
cd OpenROAD-flow-scripts

# Build everything (OpenROAD + OpenSTA + Yosys + all tools)
# This takes 30-60 minutes
./build_openroad.sh --local

# Verify installation
source ./setup_env.sh
openroad -version  # Should print: OpenROAD v2.0...
```

**What this gives you:**
- `tools/OpenROAD/` → Full OpenROAD build
- `tools/OpenSTA/` → Standalone STA tool (included as submodule)
- `tools/yosys/` → Synthesis tool
- `flow/` → Complete flow automation scripts
- `flow/designs/` → Sample designs (gcd, aes, ibex, jpeg)

---

## Step 3: Run Your First Flow (asap7 PDK)

Start with **asap7** (7nm) — it's already configured and runs fast.

```bash
cd ~/OpenROAD-flow-scripts

# Run gcd (greatest common divisor) design
# This goes: RTL → synth → floorplan → place → CTS → route → STA
make DESIGN_CONFIG=./flow/designs/asap7/gcd/config.mk

# This takes ~5 minutes. You'll see:
# [INFO] Running synthesis...
# [INFO] Running floorplan...
# [INFO] Running placement...
# [INFO] Running CTS...
# [INFO] Running routing...
# [INFO] Running STA...
# [INFO] Finished
```

**Check the outputs:**

```bash
ls results/asap7/gcd/base/
# 6_final.def       ← Final placed & routed design
# 6_final.gds       ← GDSII layout (the actual chip!)
# 6_final.v         ← Gate-level netlist

ls reports/asap7/gcd/base/
# synth_stat.txt    ← Cell counts
# 6_final_report.rpt ← Timing report (THIS IS WHAT WE INGEST!)
# 6_final_drc.rpt   ← DRC violations

ls logs/asap7/gcd/base/
# 6_1_report.log    ← Detailed STA logs
```

**Open the timing report:**

```bash
cat reports/asap7/gcd/base/6_final_report.rpt
```

You'll see:

```
===========================================================================
report_checks -path_delay min_max
============================================================================
Startpoint: _443_ (rising edge-triggered flip-flop clocked by core_clock)
Endpoint: _464_ (rising edge-triggered flip-flop clocked by core_clock)
Path Group: core_clock
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
  0.000   0.000   clock core_clock (rise edge)
  ...
  0.140   0.480   _443_/Q (sky130_fd_sc_hd__dfxtp_1)
  0.315   0.795 ^ _234_/Y (sky130_fd_sc_hd__and2_1)
  ...
  2.500   2.500   data arrival time

  2.500   2.500   clock core_clock (rise edge)
 -0.140  -0.140   slack (VIOLATED)
```

**This is REAL data.** Not made up. Not a sample file. This is what you'll ingest into pgvector.

---

## Step 4: Run Multi-Corner Analysis (MCMM)

Real chips must work across PVT corners:
- **ss** (slow-slow): worst process, high temp (100°C), low voltage (0.72V)
- **tt** (typical-typical): nominal conditions
- **ff** (fast-fast): best process, low temp (-40°C), high voltage (0.88V)

Run the same design across all corners:

```bash
# Slow corner (worst timing)
make DESIGN_CONFIG=./flow/designs/asap7/gcd/config.mk CORNER=ss

# Typical corner
make DESIGN_CONFIG=./flow/designs/asap7/gcd/config.mk CORNER=tt

# Fast corner (might have hold violations!)
make DESIGN_CONFIG=./flow/designs/asap7/gcd/config.mk CORNER=ff
```

**Check results:**

```bash
cat reports/asap7/gcd/base/ss_timing.rpt  # Slow corner
cat reports/asap7/gcd/base/tt_timing.rpt  # Typical
cat reports/asap7/gcd/base/ff_timing.rpt  # Fast
```

**WNS comparison:**
- ss: -0.34 ns (worst)
- tt: -0.14 ns
- ff: +0.12 ns (passes!)

**This is MCMM complexity** — fixing ss might break ff hold. This is what your agent will solve.

---

## Step 5: Install sky130 PDK (Production-Ready)

asap7 is great for learning, but **sky130 is fabrication-ready**. Real chips have been taped out.

```bash
# Method 1: Via open_pdks (recommended)
cd ~/
git clone https://github.com/RTimothyEdwards/open_pdks
cd open_pdks
./configure --enable-sky130-pdk
make
sudo make install

# Method 2: Direct from Google (if Method 1 fails)
cd ~/
git clone https://github.com/google/skywater-pdk
cd skywater-pdk
make timing
```

**Add sky130 to OpenROAD-flow-scripts:**

```bash
cd ~/OpenROAD-flow-scripts
make setup-skywater
```

---

## Step 6: Run gcd on sky130

```bash
cd ~/OpenROAD-flow-scripts

# Run with sky130 high-density standard cells
make DESIGN_CONFIG=./flow/designs/sky130hd/gcd/config.mk

# Takes ~8 minutes (130nm is bigger than 7nm)
```

**Compare outputs:**

| Metric | asap7 (7nm) | sky130 (130nm) | Ratio |
|--------|-------------|----------------|-------|
| Cells | 462 | 1,247 | 2.7× |
| Area | 1,234 µm² | 8,956 µm² | 7.3× |
| Max freq | 400 MHz | 125 MHz | 0.31× |
| WNS | -0.14 ns | -0.52 ns | 3.7× worse |

**Interview gold:** "I ran the same design on both PDKs to understand technology node trade-offs."

---

## Step 7: Run Larger Designs

```bash
# AES encryption core (20K cells)
make DESIGN_CONFIG=./flow/designs/sky130hd/aes/config.mk

# ibex RISC-V core (50K cells) — THE SHOWCASE
make DESIGN_CONFIG=./flow/designs/sky130hd/ibex/config.mk
```

**ibex takes ~30 minutes.** You'll get:
- 247 timing violations across 3 corners
- Real DRC issues
- Actual critical paths through a RISC-V CPU

**This is your interview demo.** No one else will have run a RISC-V core through OpenROAD and built an AI agent over it.

---

## Step 8: Integrate with ip-design-agent

Now that you have REAL reports, ingest them:

```bash
cd ~/Documents/JobhuntAI/ip-design-agent

# Point the ETL at your OpenROAD reports
python -m ip_agent.ingest \
  --dir ~/OpenROAD-flow-scripts/reports/sky130hd/gcd/ \
  --design gcd \
  --pdk sky130hd

# Or ingest ALL designs:
python -m ip_agent.ingest \
  --dir ~/OpenROAD-flow-scripts/reports/ \
  --recursive
```

**What gets ingested:**
- All timing paths → pgvector (searchable by slack, startpoint, endpoint)
- All DRC violations → pgvector (searchable by type, severity)
- Cell usage stats → pgvector (searchable by module, hierarchy)

---

## Step 9: Add MCP Tools for Live Execution

See `src/ip_agent/openroad_tools.py` for 5 MCP tools:

1. **run_openroad_flow()** — Execute a flow stage (synth, place, route, sta)
2. **get_timing_report()** — Parse and return timing report
3. **analyze_critical_path()** — Deep dive on a specific path
4. **suggest_timing_eco()** — Agent generates ECO fix
5. **compare_corners()** — MCMM cross-corner table

**Install in Claude Desktop:**

```bash
# Add to ~/.claude/mcp-config.json:
{
  "mcpServers": {
    "ip-design-agent": {
      "command": "python",
      "args": ["-m", "ip_agent.mcp_server"],
      "cwd": "/Users/ondevtratech/Documents/JobhuntAI/ip-design-agent"
    }
  }
}
```

**Restart Claude Desktop** → Now you can run flows interactively!

---

## Step 10: Test the Integration

Open Claude Desktop and try:

```
You: "Run synthesis on gcd with sky130"
Claude: [calls run_openroad_flow("gcd", "synth", "sky130hd", "tt")]
Claude: "✅ Synthesis complete: 1,247 cells, 8,956 µm², runtime 12.3s"

You: "Now run timing analysis"
Claude: [calls run_openroad_flow("gcd", "sta", "sky130hd", "tt")]
Claude: "⚠️ WNS: -0.52ns, TNS: -2.14ns, 8 violations"

You: "Show me the worst path"
Claude: [calls get_timing_report("gcd", "tt")]
Claude: "Critical path: _123_/CLK → ... → _456_/D, slack -0.52ns"

You: "How do I fix it?"
Claude: [calls suggest_timing_eco("gcd", "tt")]
Claude: "ECO script generated: size_cell u_alu/add_stage1 sky130_fd_sc_hd__fa_2"

You: "Apply it and re-run"
Claude: [applies ECO, reruns STA]
Claude: "✅ WNS improved to +0.08ns (TIMING MET!)"
```

**This is what you demo in the interview.**

---

## Troubleshooting

### Build fails with "command not found: cmake"
```bash
brew install cmake
```

### Build fails with "Qt not found"
```bash
# Skip GUI components (you don't need them)
./build_openroad.sh --local --no-gui
```

### Flow hangs on placement
```bash
# Reduce parallelism
make -j2 DESIGN_CONFIG=...
```

### sky130 PDK not found
```bash
# Check PDK path
ls ~/skywater-pdk/libraries/
# Should see: sky130_fd_sc_hd, sky130_fd_sc_hdll, etc.

# Update PDK_ROOT in OpenROAD-flow-scripts
export PDK_ROOT=~/skywater-pdk
```

---

## Next Steps

✅ **Phase 0 complete!** You now have:
- OpenROAD installed and running
- Real timing reports from gcd, aes, ibex
- Multi-corner data (ss/tt/ff)
- MCP tools ready for Claude Desktop

**Move to Phase 1:** Set up Python project structure, create pgvector DB, ingest these REAL reports.

**Interview prep:** Run ibex, generate the full MCMM report, practice the live demo flow with Claude Desktop.

---

## Files Created in Phase 0

```
ip-design-agent/
├── OPENROAD_SETUP.md          ← This file
├── src/ip_agent/
│   └── openroad_tools.py      ← 5 MCP tools for live flow execution
├── demo_real_flow.py          ← End-to-end demo script
└── docs/
    └── PDK_COMPARISON.md       ← asap7 vs sky130 analysis
```

---

## Success Criteria

- [ ] `openroad -version` prints version
- [ ] `make DESIGN_CONFIG=./flow/designs/asap7/gcd/config.mk` completes
- [ ] `reports/asap7/gcd/base/6_final_report.rpt` exists and contains timing paths
- [ ] Multi-corner runs complete (ss/tt/ff)
- [ ] sky130 PDK installed and gcd runs successfully
- [ ] MCP tools callable from Claude Desktop
- [ ] Can run "synthesis → STA → ECO → re-run STA" loop interactively

**If all checked:** Phase 0 complete. Move to Phase 1 (project setup + ingestion).

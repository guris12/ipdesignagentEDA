"""
Run Tracker — Store and manage OpenROAD flow run metrics.

This module tracks timing/DRC metrics across multiple runs to enable
trend analysis and ECO validation. Think of it as version control for
your timing closure iterations.

Swift analogy: Like Core Data or SQLite for persisting app state.
Each "run" is a record with metrics + metadata.

Usage:
    tracker = RunTracker("gcd", "sky130hd")

    # After baseline run
    tracker.save_run(
        run_id="baseline",
        corner="tt",
        wns=-0.52,
        tns=-2.14,
        violations=8,
        drc=5,
        cells=1247,
        area=8956.0,
    )

    # After ECO #1
    tracker.save_run(
        run_id="eco1",
        corner="tt",
        wns=-0.14,
        tns=-0.87,
        violations=3,
        drc=5,
        cells=1289,
        area=9123.0,
        eco={
            "type": "cell_sizing",
            "description": "Upsized 4 critical cells",
            "commands": ["size_cell u_alu/add_stage1 ..."],
        }
    )

    # Get all runs
    runs = tracker.get_all_runs()

    # Compare runs
    comparison = tracker.compare_runs("baseline", "eco1")
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, asdict


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class ECOInfo:
    """ECO fix information"""
    type: str  # "cell_sizing", "buffer_insertion", "vt_swap", etc.
    description: str
    commands: list[str]  # Tcl commands applied

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ECOInfo:
        return cls(**data)


@dataclass
class RunMetrics:
    """Metrics from a single OpenROAD run"""
    run_id: str
    timestamp: str  # ISO format
    corner: str  # ss, tt, ff

    # Timing metrics
    wns: float  # Worst Negative Slack (ns)
    tns: float  # Total Negative Slack (ns)
    violations: int  # Number of violated paths

    # Physical metrics
    drc: int  # DRC violation count
    cells: int  # Total cell count
    area: float  # Die area (µm²)

    # Optional metrics
    power: Optional[float] = None  # Total power (mW)
    runtime: Optional[float] = None  # Flow runtime (seconds)

    # ECO information
    eco: Optional[ECOInfo] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.eco:
            data['eco'] = self.eco.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> RunMetrics:
        if data.get('eco'):
            data['eco'] = ECOInfo.from_dict(data['eco'])
        return cls(**data)

    @property
    def passing_timing(self) -> bool:
        """Check if timing is met"""
        return self.wns >= 0.0


# ---------------------------------------------------------------------------
# Run Tracker
# ---------------------------------------------------------------------------

class RunTracker:
    """
    Track OpenROAD flow runs for a design.

    Stores metrics in JSON files: data/runs/{design}_{pdk}_runs.json
    """

    def __init__(self, design: str, pdk: str, data_dir: Optional[Path] = None):
        self.design = design
        self.pdk = pdk

        # Default data directory
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent / "data" / "runs"

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # JSON file for this design
        self.run_file = self.data_dir / f"{design}_{pdk}_runs.json"

        # Load existing runs
        self._load_runs()

    def _load_runs(self):
        """Load runs from JSON file"""
        if self.run_file.exists():
            with open(self.run_file) as f:
                data = json.load(f)
                self.runs = [RunMetrics.from_dict(r) for r in data.get("runs", [])]
        else:
            self.runs = []

    def _save_runs(self):
        """Save runs to JSON file"""
        data = {
            "design": self.design,
            "pdk": self.pdk,
            "updated": datetime.now().isoformat(),
            "runs": [r.to_dict() for r in self.runs],
        }

        with open(self.run_file, "w") as f:
            json.dump(data, f, indent=2)

    def save_run(
        self,
        run_id: str,
        corner: str,
        wns: float,
        tns: float,
        violations: int,
        drc: int,
        cells: int,
        area: float,
        power: Optional[float] = None,
        runtime: Optional[float] = None,
        eco: Optional[dict[str, Any]] = None,
    ) -> RunMetrics:
        """
        Save metrics from a run.

        Args:
            run_id: Unique identifier (e.g., "baseline", "eco1", "eco2")
            corner: PVT corner (ss, tt, ff)
            wns: Worst Negative Slack (ns)
            tns: Total Negative Slack (ns)
            violations: Number of violated paths
            drc: DRC violation count
            cells: Total cell count
            area: Die area (µm²)
            power: Optional power (mW)
            runtime: Optional runtime (seconds)
            eco: Optional ECO info dict

        Returns:
            RunMetrics object
        """
        # Convert ECO dict to ECOInfo if provided
        eco_info = ECOInfo(**eco) if eco else None

        # Create metrics object
        metrics = RunMetrics(
            run_id=run_id,
            timestamp=datetime.now().isoformat(),
            corner=corner,
            wns=wns,
            tns=tns,
            violations=violations,
            drc=drc,
            cells=cells,
            area=area,
            power=power,
            runtime=runtime,
            eco=eco_info,
        )

        # Remove existing run with same ID (replace)
        self.runs = [r for r in self.runs if r.run_id != run_id]

        # Add new run
        self.runs.append(metrics)

        # Save to disk
        self._save_runs()

        return metrics

    def get_run(self, run_id: str) -> Optional[RunMetrics]:
        """Get a specific run by ID"""
        for run in self.runs:
            if run.run_id == run_id:
                return run
        return None

    def get_all_runs(self) -> list[RunMetrics]:
        """Get all runs sorted by timestamp"""
        return sorted(self.runs, key=lambda r: r.timestamp)

    def compare_runs(self, run1_id: str, run2_id: str) -> dict[str, Any]:
        """
        Compare two runs and return deltas.

        Returns:
            Dict with deltas for each metric
        """
        run1 = self.get_run(run1_id)
        run2 = self.get_run(run2_id)

        if not run1 or not run2:
            raise ValueError(f"Run not found: {run1_id if not run1 else run2_id}")

        return {
            "wns_delta": run2.wns - run1.wns,
            "tns_delta": run2.tns - run1.tns,
            "violations_delta": run2.violations - run1.violations,
            "drc_delta": run2.drc - run1.drc,
            "cells_delta": run2.cells - run1.cells,
            "area_delta": run2.area - run1.area,
            "area_pct": ((run2.area - run1.area) / run1.area) * 100,
            "improved_timing": run2.wns > run1.wns,
            "improved_violations": run2.violations < run1.violations,
            "now_passing": run2.passing_timing and not run1.passing_timing,
        }

    def get_trend(self, metric: str) -> list[tuple[str, float]]:
        """
        Get trend data for a specific metric across all runs.

        Args:
            metric: "wns", "tns", "violations", "drc", "cells", "area"

        Returns:
            List of (run_id, value) tuples
        """
        trend = []
        for run in self.get_all_runs():
            value = getattr(run, metric)
            trend.append((run.run_id, value))
        return trend

    def get_summary(self) -> dict[str, Any]:
        """
        Get summary statistics across all runs.

        Returns:
            Dict with baseline, latest, best, worst metrics
        """
        if not self.runs:
            return {"error": "No runs found"}

        sorted_runs = self.get_all_runs()
        baseline = sorted_runs[0]
        latest = sorted_runs[-1]

        # Find best WNS
        best_wns_run = max(sorted_runs, key=lambda r: r.wns)

        # Count passing runs
        passing_runs = sum(1 for r in sorted_runs if r.passing_timing)

        return {
            "total_runs": len(sorted_runs),
            "baseline": {
                "run_id": baseline.run_id,
                "wns": baseline.wns,
                "violations": baseline.violations,
            },
            "latest": {
                "run_id": latest.run_id,
                "wns": latest.wns,
                "violations": latest.violations,
                "passing": latest.passing_timing,
            },
            "best_wns": {
                "run_id": best_wns_run.run_id,
                "wns": best_wns_run.wns,
            },
            "improvement": {
                "wns_delta": latest.wns - baseline.wns,
                "violations_delta": latest.violations - baseline.violations,
            },
            "passing_runs": passing_runs,
            "convergence": self._check_convergence(),
        }

    def _check_convergence(self) -> str:
        """
        Check if timing is converging (improving) or diverging.

        Returns:
            "converging", "diverging", "stable", or "insufficient_data"
        """
        if len(self.runs) < 3:
            return "insufficient_data"

        sorted_runs = self.get_all_runs()
        wns_values = [r.wns for r in sorted_runs]

        # Check last 3 runs
        recent = wns_values[-3:]

        # Converging: each run better than previous
        if recent[0] < recent[1] < recent[2]:
            return "converging"

        # Diverging: each run worse than previous
        if recent[0] > recent[1] > recent[2]:
            return "diverging"

        # Check if oscillating
        deltas = [recent[i+1] - recent[i] for i in range(len(recent)-1)]
        if all(abs(d) < 0.05 for d in deltas):  # Within 50ps
            return "stable"

        return "oscillating"

    def export_csv(self, output_path: Optional[Path] = None) -> Path:
        """
        Export run data to CSV for analysis in spreadsheets.

        Returns:
            Path to CSV file
        """
        import csv

        if output_path is None:
            output_path = self.data_dir / f"{self.design}_{self.pdk}_runs.csv"

        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                "run_id", "timestamp", "corner",
                "wns", "tns", "violations",
                "drc", "cells", "area",
                "power", "runtime",
                "eco_type", "eco_description"
            ])

            # Data rows
            for run in self.get_all_runs():
                writer.writerow([
                    run.run_id, run.timestamp, run.corner,
                    run.wns, run.tns, run.violations,
                    run.drc, run.cells, run.area,
                    run.power or "", run.runtime or "",
                    run.eco.type if run.eco else "",
                    run.eco.description if run.eco else "",
                ])

        return output_path


# ---------------------------------------------------------------------------
# CLI for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Create sample data
    tracker = RunTracker("gcd", "sky130hd")

    # Baseline
    tracker.save_run(
        run_id="baseline",
        corner="tt",
        wns=-0.52,
        tns=-2.14,
        violations=8,
        drc=5,
        cells=1247,
        area=8956.0,
    )

    # ECO #1: Cell sizing
    tracker.save_run(
        run_id="eco1",
        corner="tt",
        wns=-0.14,
        tns=-0.87,
        violations=3,
        drc=5,
        cells=1289,
        area=9123.0,
        eco={
            "type": "cell_sizing",
            "description": "Upsized 4 critical cells in ALU",
            "commands": [
                "size_cell u_alu/add_stage1 sky130_fd_sc_hd__fa_2",
                "size_cell u_alu/add_stage2 sky130_fd_sc_hd__fa_2",
            ]
        }
    )

    # ECO #2: Buffer insertion
    tracker.save_run(
        run_id="eco2",
        corner="tt",
        wns=0.08,
        tns=0.00,
        violations=0,
        drc=5,
        cells=1305,
        area=9456.0,
        eco={
            "type": "buffer_insertion",
            "description": "Buffered 2 long nets",
            "commands": [
                "insert_buffer -net net_234 -buffer sky130_fd_sc_hd__buf_4",
            ]
        }
    )

    print("✅ Saved 3 runs")
    print(f"📁 Data file: {tracker.run_file}")

    # Get summary
    summary = tracker.get_summary()
    print("\n📊 Summary:")
    print(f"  Total runs: {summary['total_runs']}")
    print(f"  Baseline WNS: {summary['baseline']['wns']:.3f} ns")
    print(f"  Latest WNS: {summary['latest']['wns']:+.3f} ns")
    print(f"  Improvement: {summary['improvement']['wns_delta']:+.3f} ns")
    print(f"  Status: {summary['latest']['passing']}")
    print(f"  Convergence: {summary['convergence']}")

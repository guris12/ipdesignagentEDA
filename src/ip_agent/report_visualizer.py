"""
Report Visualizer — Generate HTML dashboards from run history.

Creates beautiful, interactive timing closure reports with:
- Summary cards (current status, improvement)
- Trend charts (WNS over runs, violations by corner)
- Detailed comparison table
- ECO history

Swift analogy: Like generating a SwiftUI view from data models.
Input: RunTracker data → Output: HTML with Plotly charts

Usage:
    visualizer = ReportVisualizer("gcd", "sky130hd")
    html_path = visualizer.generate_dashboard()
    # Opens: reports/gcd_sky130hd_dashboard.html
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from ip_agent.run_tracker import RunTracker, RunMetrics


# ---------------------------------------------------------------------------
# Report Visualizer
# ---------------------------------------------------------------------------

class ReportVisualizer:
    """Generate HTML dashboards from run tracking data"""

    def __init__(self, design: str, pdk: str, output_dir: Optional[Path] = None):
        self.design = design
        self.pdk = pdk

        # Load run tracker
        self.tracker = RunTracker(design, pdk)

        # Output directory
        if output_dir is None:
            output_dir = Path(__file__).parent.parent.parent / "reports"

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_dashboard(
        self,
        run_ids: Optional[list[str]] = None,
        title: Optional[str] = None,
    ) -> Path:
        """
        Generate HTML dashboard.

        Args:
            run_ids: Optional list of run IDs to include (default: all)
            title: Optional custom title

        Returns:
            Path to generated HTML file
        """
        # Get runs
        if run_ids:
            runs = [self.tracker.get_run(rid) for rid in run_ids]
            runs = [r for r in runs if r is not None]  # Filter None
        else:
            runs = self.tracker.get_all_runs()

        if not runs:
            raise ValueError(f"No runs found for {self.design}/{self.pdk}")

        # Generate HTML
        html = self._generate_html(runs, title)

        # Write to file
        output_file = self.output_dir / f"{self.design}_{self.pdk}_dashboard.html"
        output_file.write_text(html)

        return output_file

    def _generate_html(self, runs: list[RunMetrics], title: Optional[str]) -> str:
        """Generate complete HTML document"""

        if title is None:
            title = f"Timing Closure Dashboard: {self.design} ({self.pdk})"

        baseline = runs[0]
        latest = runs[-1]

        # Calculate deltas
        wns_delta = latest.wns - baseline.wns
        tns_delta = latest.tns - baseline.tns
        viol_delta = latest.violations - baseline.violations
        drc_delta = latest.drc - baseline.drc
        area_pct = ((latest.area - baseline.area) / baseline.area) * 100

        # Prepare chart data
        chart_data = self._prepare_chart_data(runs)

        # Generate HTML
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 20px;
    color: #333;
}}

.container {{
    max-width: 1400px;
    margin: 0 auto;
}}

.header {{
    background: white;
    padding: 24px;
    border-radius: 12px;
    margin-bottom: 20px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}}

.header h1 {{
    font-size: 28px;
    color: #2d3748;
    margin-bottom: 8px;
}}

.header .meta {{
    color: #718096;
    font-size: 14px;
}}

.cards {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 16px;
    margin-bottom: 20px;
}}

.card {{
    background: white;
    padding: 20px;
    border-radius: 12px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}}

.card-title {{
    font-size: 14px;
    color: #718096;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}}

.card-value {{
    font-size: 32px;
    font-weight: 700;
    color: #2d3748;
    margin-bottom: 4px;
}}

.card-value.pass {{
    color: #38a169;
}}

.card-value.fail {{
    color: #e53e3e;
}}

.card-delta {{
    font-size: 14px;
    font-weight: 600;
}}

.delta-positive {{
    color: #38a169;
}}

.delta-negative {{
    color: #e53e3e;
}}

.delta-neutral {{
    color: #718096;
}}

.chart-container {{
    background: white;
    padding: 24px;
    border-radius: 12px;
    margin-bottom: 20px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}}

.chart-title {{
    font-size: 18px;
    font-weight: 600;
    color: #2d3748;
    margin-bottom: 16px;
}}

table {{
    width: 100%;
    background: white;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    border-collapse: collapse;
}}

th {{
    background: #4a5568;
    color: white;
    padding: 12px;
    text-align: left;
    font-weight: 600;
    font-size: 14px;
}}

td {{
    padding: 12px;
    border-bottom: 1px solid #e2e8f0;
    font-size: 14px;
}}

tr:last-child td {{
    border-bottom: none;
}}

tr:hover {{
    background: #f7fafc;
}}

.status-badge {{
    display: inline-block;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
}}

.badge-pass {{
    background: #c6f6d5;
    color: #22543d;
}}

.badge-fail {{
    background: #fed7d7;
    color: #742a2a;
}}

.eco-description {{
    font-size: 12px;
    color: #718096;
    font-style: italic;
}}

.convergence {{
    display: inline-block;
    margin-left: 12px;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    background: #bee3f8;
    color: #2c5282;
}}
</style>
</head>
<body>
<div class="container">

<!-- Header -->
<div class="header">
    <h1>{title}</h1>
    <div class="meta">
        Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} |
        Runs: {len(runs)} |
        Baseline: {baseline.run_id} |
        Latest: {latest.run_id}
        <span class="convergence">{self.tracker._check_convergence().upper()}</span>
    </div>
</div>

<!-- Summary Cards -->
<div class="cards">
    <div class="card">
        <div class="card-title">Current WNS</div>
        <div class="card-value {'pass' if latest.passing_timing else 'fail'}">
            {latest.wns:+.3f} ns
        </div>
        <div class="card-delta {'delta-positive' if wns_delta > 0 else 'delta-negative'}">
            {wns_delta:+.3f} ns from baseline
        </div>
    </div>

    <div class="card">
        <div class="card-title">Violations</div>
        <div class="card-value {'pass' if latest.violations == 0 else 'fail'}">
            {latest.violations}
        </div>
        <div class="card-delta {'delta-positive' if viol_delta < 0 else 'delta-negative' if viol_delta > 0 else 'delta-neutral'}">
            {viol_delta:+d} from baseline
        </div>
    </div>

    <div class="card">
        <div class="card-title">DRC Issues</div>
        <div class="card-value {'pass' if latest.drc == 0 else 'fail'}">
            {latest.drc}
        </div>
        <div class="card-delta {'delta-positive' if drc_delta < 0 else 'delta-negative' if drc_delta > 0 else 'delta-neutral'}">
            {drc_delta:+d} from baseline
        </div>
    </div>

    <div class="card">
        <div class="card-title">Area</div>
        <div class="card-value">
            {latest.area:.0f} µm²
        </div>
        <div class="card-delta {'delta-negative' if area_pct > 10 else 'delta-neutral'}">
            {area_pct:+.1f}% from baseline
        </div>
    </div>

    <div class="card">
        <div class="card-title">TNS</div>
        <div class="card-value {'pass' if latest.tns >= 0 else 'fail'}">
            {latest.tns:+.3f} ns
        </div>
        <div class="card-delta {'delta-positive' if tns_delta > 0 else 'delta-negative'}">
            {tns_delta:+.3f} ns from baseline
        </div>
    </div>
</div>

<!-- Charts -->
<div class="chart-container">
    <div class="chart-title">WNS Trend Over Runs</div>
    <div id="wns-chart"></div>
</div>

<div class="chart-container">
    <div class="chart-title">Violations by Run</div>
    <div id="violations-chart"></div>
</div>

<!-- Detailed Table -->
<div class="chart-container">
    <div class="chart-title">Detailed Run Comparison</div>
    <table>
        <thead>
            <tr>
                <th>Run ID</th>
                <th>WNS (ns)</th>
                <th>TNS (ns)</th>
                <th>Violations</th>
                <th>DRC</th>
                <th>Cells</th>
                <th>Area (µm²)</th>
                <th>Status</th>
                <th>ECO Applied</th>
            </tr>
        </thead>
        <tbody>
"""

        # Table rows
        for run in runs:
            status_class = "badge-pass" if run.passing_timing else "badge-fail"
            status_text = "✅ PASS" if run.passing_timing else "⚠️ FAIL"

            eco_text = "—"
            if run.eco:
                eco_text = f"{run.eco.type}<br><span class='eco-description'>{run.eco.description}</span>"

            html += f"""
            <tr>
                <td><strong>{run.run_id}</strong></td>
                <td>{run.wns:+.3f}</td>
                <td>{run.tns:+.3f}</td>
                <td>{run.violations}</td>
                <td>{run.drc}</td>
                <td>{run.cells}</td>
                <td>{run.area:.0f}</td>
                <td><span class="status-badge {status_class}">{status_text}</span></td>
                <td>{eco_text}</td>
            </tr>
"""

        html += f"""
        </tbody>
    </table>
</div>

</div>

<!-- Chart Scripts -->
<script>
// WNS Trend Chart
var wnsTrace = {{
    x: {chart_data['run_ids']},
    y: {chart_data['wns_values']},
    type: 'scatter',
    mode: 'lines+markers',
    name: 'WNS',
    line: {{
        color: '#667eea',
        width: 3
    }},
    marker: {{
        size: 10,
        color: {chart_data['wns_colors']}
    }}
}};

var zeroLine = {{
    x: {chart_data['run_ids']},
    y: {[0] * len(runs)},
    type: 'scatter',
    mode: 'lines',
    name: 'Target (0 ns)',
    line: {{
        color: '#38a169',
        width: 2,
        dash: 'dash'
    }},
    showlegend: true
}};

var wnsLayout = {{
    xaxis: {{
        title: 'Run',
        showgrid: true
    }},
    yaxis: {{
        title: 'WNS (ns)',
        showgrid: true,
        zeroline: true
    }},
    hovermode: 'closest',
    plot_bgcolor: '#f7fafc',
    paper_bgcolor: '#ffffff',
    margin: {{t: 20, r: 20, b: 60, l: 60}}
}};

Plotly.newPlot('wns-chart', [wnsTrace, zeroLine], wnsLayout, {{responsive: true}});

// Violations Chart
var violTrace = {{
    x: {chart_data['run_ids']},
    y: {chart_data['violations']},
    type: 'bar',
    marker: {{
        color: {chart_data['viol_colors']}
    }}
}};

var violLayout = {{
    xaxis: {{
        title: 'Run'
    }},
    yaxis: {{
        title: 'Violation Count',
        showgrid: true
    }},
    plot_bgcolor: '#f7fafc',
    paper_bgcolor: '#ffffff',
    margin: {{t: 20, r: 20, b: 60, l: 60}}
}};

Plotly.newPlot('violations-chart', [violTrace], violLayout, {{responsive: true}});
</script>

</body>
</html>
"""

        return html

    def _prepare_chart_data(self, runs: list[RunMetrics]) -> dict:
        """Prepare data for Plotly charts"""

        run_ids = [r.run_id for r in runs]
        wns_values = [r.wns for r in runs]
        violations = [r.violations for r in runs]

        # Color points based on pass/fail
        wns_colors = ['#38a169' if v >= 0 else '#e53e3e' for v in wns_values]
        viol_colors = ['#38a169' if v == 0 else '#e53e3e' for v in violations]

        return {
            'run_ids': json.dumps(run_ids),
            'wns_values': json.dumps(wns_values),
            'violations': json.dumps(violations),
            'wns_colors': json.dumps(wns_colors),
            'viol_colors': json.dumps(viol_colors),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import webbrowser

    parser = argparse.ArgumentParser(description="Generate timing closure dashboard")
    parser.add_argument("--design", default="gcd", help="Design name")
    parser.add_argument("--pdk", default="sky130hd", help="PDK name")
    parser.add_argument("--runs", help="Comma-separated run IDs (default: all)")
    parser.add_argument("--open", action="store_true", help="Open in browser")

    args = parser.parse_args()

    # Parse run IDs
    run_ids = args.runs.split(",") if args.runs else None

    # Generate dashboard
    visualizer = ReportVisualizer(args.design, args.pdk)
    html_path = visualizer.generate_dashboard(run_ids=run_ids)

    print(f"✅ Dashboard generated: {html_path}")

    # Open in browser
    if args.open:
        webbrowser.open(html_path.as_uri())
        print(f"🌐 Opened in browser")

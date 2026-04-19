#!/usr/bin/env python3
"""
Standalone dashboard generator — No dependencies needed!

This creates a sample timing closure dashboard using only Python stdlib.
Perfect for testing without installing dependencies.

Usage:
    python3 test_dashboard_standalone.py
"""

import json
from pathlib import Path
from datetime import datetime


def generate_sample_dashboard():
    """Generate sample dashboard HTML"""

    # Sample data
    runs = [
        {
            "run_id": "baseline",
            "wns": -0.52,
            "tns": -2.14,
            "violations": 8,
            "drc": 5,
            "cells": 1247,
            "area": 8956,
            "eco": None
        },
        {
            "run_id": "eco1",
            "wns": -0.14,
            "tns": -0.87,
            "violations": 3,
            "drc": 5,
            "cells": 1289,
            "area": 9123,
            "eco": {
                "type": "cell_sizing",
                "description": "Upsized 4 critical cells in ALU datapath"
            }
        },
        {
            "run_id": "eco2",
            "wns": 0.08,
            "tns": 0.00,
            "violations": 0,
            "drc": 5,
            "cells": 1305,
            "area": 9456,
            "eco": {
                "type": "buffer_insertion",
                "description": "Buffered 2 long nets with high RC delay"
            }
        }
    ]

    # Calculate deltas
    baseline = runs[0]
    latest = runs[-1]
    wns_delta = latest["wns"] - baseline["wns"]
    viol_delta = latest["violations"] - baseline["violations"]
    area_pct = ((latest["area"] - baseline["area"]) / baseline["area"]) * 100

    # Chart data
    run_ids = [r["run_id"] for r in runs]
    wns_values = [r["wns"] for r in runs]
    violations = [r["violations"] for r in runs]
    wns_colors = ['#38a169' if v >= 0 else '#e53e3e' for v in wns_values]
    viol_colors = ['#38a169' if v == 0 else '#e53e3e' for v in violations]

    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Timing Closure Dashboard: gcd (sky130hd)</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 20px;
    color: #333;
}}
.container {{ max-width: 1400px; margin: 0 auto; }}
.header {{
    background: white;
    padding: 24px;
    border-radius: 12px;
    margin-bottom: 20px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
}}
.header h1 {{ font-size: 28px; color: #2d3748; margin-bottom: 8px; }}
.header .meta {{ color: #718096; font-size: 14px; }}
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
.card-value.pass {{ color: #38a169; }}
.card-value.fail {{ color: #e53e3e; }}
.card-delta {{ font-size: 14px; font-weight: 600; }}
.delta-positive {{ color: #38a169; }}
.delta-negative {{ color: #e53e3e; }}
.delta-neutral {{ color: #718096; }}
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
tr:last-child td {{ border-bottom: none; }}
tr:hover {{ background: #f7fafc; }}
.status-badge {{
    display: inline-block;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
}}
.badge-pass {{ background: #c6f6d5; color: #22543d; }}
.badge-fail {{ background: #fed7d7; color: #742a2a; }}
.eco-description {{ font-size: 12px; color: #718096; font-style: italic; }}
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

<div class="header">
    <h1>Timing Closure Dashboard: gcd (sky130hd)</h1>
    <div class="meta">
        Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} |
        Runs: {len(runs)} |
        Baseline: {baseline["run_id"]} |
        Latest: {latest["run_id"]}
        <span class="convergence">CONVERGING</span>
    </div>
</div>

<div class="cards">
    <div class="card">
        <div class="card-title">Current WNS</div>
        <div class="card-value {'pass' if latest['wns'] >= 0 else 'fail'}">
            {latest['wns']:+.3f} ns
        </div>
        <div class="card-delta {'delta-positive' if wns_delta > 0 else 'delta-negative'}">
            {wns_delta:+.3f} ns from baseline
        </div>
    </div>
    <div class="card">
        <div class="card-title">Violations</div>
        <div class="card-value {'pass' if latest['violations'] == 0 else 'fail'}">
            {latest['violations']}
        </div>
        <div class="card-delta {'delta-positive' if viol_delta < 0 else 'delta-negative'}">
            {viol_delta:+d} from baseline
        </div>
    </div>
    <div class="card">
        <div class="card-title">DRC Issues</div>
        <div class="card-value">
            {latest['drc']}
        </div>
        <div class="card-delta delta-neutral">
            ±0 from baseline
        </div>
    </div>
    <div class="card">
        <div class="card-title">Area</div>
        <div class="card-value">
            {latest['area']:.0f} µm²
        </div>
        <div class="card-delta delta-neutral">
            {area_pct:+.1f}% from baseline
        </div>
    </div>
</div>

<div class="chart-container">
    <div class="chart-title">WNS Trend Over Runs</div>
    <div id="wns-chart"></div>
</div>

<div class="chart-container">
    <div class="chart-title">Violations by Run</div>
    <div id="violations-chart"></div>
</div>

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
        status_class = "badge-pass" if run["wns"] >= 0 else "badge-fail"
        status_text = "✅ PASS" if run["wns"] >= 0 else "⚠️ FAIL"
        eco_text = "—"
        if run["eco"]:
            eco_text = f"{run['eco']['type']}<br><span class='eco-description'>{run['eco']['description']}</span>"

        html += f"""
            <tr>
                <td><strong>{run['run_id']}</strong></td>
                <td>{run['wns']:+.3f}</td>
                <td>{run['tns']:+.3f}</td>
                <td>{run['violations']}</td>
                <td>{run['drc']}</td>
                <td>{run['cells']}</td>
                <td>{run['area']:.0f}</td>
                <td><span class="status-badge {status_class}">{status_text}</span></td>
                <td>{eco_text}</td>
            </tr>
"""

    html += f"""
        </tbody>
    </table>
</div>

</div>

<script>
// WNS Trend Chart
var wnsTrace = {{
    x: {json.dumps(run_ids)},
    y: {json.dumps(wns_values)},
    type: 'scatter',
    mode: 'lines+markers',
    name: 'WNS',
    line: {{ color: '#667eea', width: 3 }},
    marker: {{ size: 10, color: {json.dumps(wns_colors)} }}
}};

var zeroLine = {{
    x: {json.dumps(run_ids)},
    y: {json.dumps([0] * len(runs))},
    type: 'scatter',
    mode: 'lines',
    name: 'Target (0 ns)',
    line: {{ color: '#38a169', width: 2, dash: 'dash' }},
    showlegend: true
}};

var wnsLayout = {{
    xaxis: {{ title: 'Run', showgrid: true }},
    yaxis: {{ title: 'WNS (ns)', showgrid: true, zeroline: true }},
    hovermode: 'closest',
    plot_bgcolor: '#f7fafc',
    paper_bgcolor: '#ffffff',
    margin: {{t: 20, r: 20, b: 60, l: 60}}
}};

Plotly.newPlot('wns-chart', [wnsTrace, zeroLine], wnsLayout, {{responsive: true}});

// Violations Chart
var violTrace = {{
    x: {json.dumps(run_ids)},
    y: {json.dumps(violations)},
    type: 'bar',
    marker: {{ color: {json.dumps(viol_colors)} }}
}};

var violLayout = {{
    xaxis: {{ title: 'Run' }},
    yaxis: {{ title: 'Violation Count', showgrid: true }},
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


if __name__ == "__main__":
    print("=" * 70)
    print("  🎨 Generating Sample Timing Closure Dashboard")
    print("=" * 70)
    print()

    # Generate dashboard
    html = generate_sample_dashboard()

    # Save to reports folder
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)

    output_file = reports_dir / "sample_timing_dashboard.html"
    output_file.write_text(html)

    print(f"✅ Dashboard generated: {output_file}")
    print()
    print("📊 Dashboard contains:")
    print("  • 4 summary cards (WNS, Violations, DRC, Area)")
    print("  • WNS trend chart (shows improvement from -0.52ns → +0.08ns)")
    print("  • Violations bar chart (8 → 3 → 0)")
    print("  • Detailed comparison table with ECO descriptions")
    print()
    print(f"🌐 Open in browser:")
    print(f"   open {output_file}")
    print()
    print("=" * 70)

    # Try to open in browser
    import webbrowser
    import time

    print("Opening in browser in 2 seconds...")
    time.sleep(2)
    webbrowser.open(output_file.as_uri())

    print("✅ Done!")

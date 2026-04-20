#!/bin/bash
# job_server.sh — OpenROAD container job watcher.
# Watches /shared/jobs/ for JSON job files, executes them,
# writes results to /shared/results/{job_id}/.
set -uo pipefail

# Source ORFS environment so openroad, yosys etc. are on PATH
if [ -f /OpenROAD-flow-scripts/setup_env.sh ]; then
    source /OpenROAD-flow-scripts/setup_env.sh
elif [ -d /OpenROAD-flow-scripts/tools/install/OpenROAD/bin ]; then
    export PATH="/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:$PATH"
fi

JOBS_DIR="/shared/jobs"
RESULTS_DIR="/shared/results"
FLOW_HOME="/OpenROAD-flow-scripts/flow"

mkdir -p "$JOBS_DIR" "$RESULTS_DIR"

echo "=== OpenROAD Job Server started $(date -u) ==="
echo "=== Watching $JOBS_DIR for new jobs ==="

# If positional args provided (not --watch-only), run initial flow first
if [[ "${1:-}" != "" && "${1:-}" != "--watch-only" ]]; then
    echo "=== Running initial flow: $@ ==="
    /run_flow.sh "$@" &
    INITIAL_PID=$!
fi

process_job() {
    local job_file="$1"
    local job_id
    local job_type
    job_id=$(python3 -c "import json,sys; print(json.load(open('$job_file'))['job_id'])")
    job_type=$(python3 -c "import json,sys; print(json.load(open('$job_file'))['type'])")

    local result_dir="$RESULTS_DIR/$job_id"
    mkdir -p "$result_dir/reports"

    echo "$(date -u) RUNNING" > "$result_dir/.running"
    echo "=== Job $job_id ($job_type) started ==="

    local start_time
    start_time=$(date +%s)
    local exit_code=0

    cd "$FLOW_HOME"

    case "$job_type" in
        "stage")
            local design pdk stage config target
            design=$(python3 -c "import json; print(json.load(open('$job_file'))['design'])")
            pdk=$(python3 -c "import json; print(json.load(open('$job_file'))['pdk'])")
            stage=$(python3 -c "import json; print(json.load(open('$job_file'))['stage'])")
            config="designs/${pdk}/${design}/config.mk"

            # Map stage names to OpenROAD-flow-scripts make targets
            case "$stage" in
                synth)     target="synth" ;;
                floorplan) target="floorplan" ;;
                place)     target="place" ;;
                cts)       target="cts" ;;
                route)     target="route" ;;
                finish)    target="finish" ;;
                *)         target="$stage" ;;
            esac

            echo "=== Running: make DESIGN_CONFIG=$config $target ===" | tee "$result_dir/output.log"
            make "DESIGN_CONFIG=$config" "$target" 2>&1 | tee -a "$result_dir/output.log" || exit_code=$?

            # Copy all reports and logs to results
            cp -r "results/${pdk}/${design}/base/"*.rpt "$result_dir/reports/" 2>/dev/null || true
            cp -r "logs/${pdk}/${design}/base/"*.log "$result_dir/reports/" 2>/dev/null || true
            cp -r "reports/${pdk}/${design}/base/"*.rpt "$result_dir/reports/" 2>/dev/null || true
            ;;

        "tcl_command")
            local command
            command=$(python3 -c "import json; print(json.load(open('$job_file'))['command'])")
            local design pdk
            design=$(python3 -c "import json; print(json.load(open('$job_file')).get('design','gcd'))")
            pdk=$(python3 -c "import json; print(json.load(open('$job_file')).get('pdk','sky130hd'))")

            # Load the latest database if it exists, then run command
            local latest_odb
            latest_odb=$(ls -t "results/${pdk}/${design}/base/"*.odb 2>/dev/null | head -1)

            # Find liberty file for the PDK
            local liberty_file
            liberty_file=$(find "platforms/${pdk}/lib" -name "*.lib" -type f 2>/dev/null | head -1)
            local sdc_file
            sdc_file=$(ls -t "results/${pdk}/${design}/base/"*.sdc 2>/dev/null | head -1)

            if [[ -n "$latest_odb" ]]; then
                echo "=== Loading DB: $latest_odb ===" | tee "$result_dir/output.log"
                {
                    [[ -n "$liberty_file" ]] && echo "read_liberty $liberty_file"
                    echo "read_db $latest_odb"
                    [[ -n "$sdc_file" ]] && echo "read_sdc $sdc_file"
                    echo "$command"
                    echo "exit"
                } | openroad -no_init 2>&1 | tee -a "$result_dir/output.log" || exit_code=$?
            else
                echo "=== No existing DB found, running command directly ===" | tee "$result_dir/output.log"
                {
                    [[ -n "$liberty_file" ]] && echo "read_liberty $liberty_file"
                    echo "$command"
                    echo "exit"
                } | openroad -no_init 2>&1 | tee -a "$result_dir/output.log" || exit_code=$?
            fi
            ;;

        "full_flow")
            local design pdk
            design=$(python3 -c "import json; print(json.load(open('$job_file'))['design'])")
            pdk=$(python3 -c "import json; print(json.load(open('$job_file'))['pdk'])")

            /run_flow.sh "$design" "$pdk" 2>&1 | tee "$result_dir/output.log" || exit_code=$?

            # Copy from run_flow.sh output dir to job results
            local latest_run
            latest_run=$(ls -td /shared/reports/${design}_${pdk}_* 2>/dev/null | head -1)
            if [[ -n "$latest_run" ]]; then
                cp -r "$latest_run/"* "$result_dir/reports/" 2>/dev/null || true
            fi
            ;;

        *)
            echo "Unknown job type: $job_type" | tee "$result_dir/output.log"
            exit_code=1
            ;;
    esac

    local end_time elapsed
    end_time=$(date +%s)
    elapsed=$((end_time - start_time))

    # Extract metrics
    python3 -c "
import json, glob, os, re
metrics = {'job_id': '$job_id', 'type': '$job_type', 'exit_code': $exit_code, 'elapsed_seconds': $elapsed}
rpt_dir = '$result_dir/reports'
for f in sorted(glob.glob(os.path.join(rpt_dir, '*.rpt'))):
    with open(f) as fh:
        content = fh.read()
    if 'slack' in content.lower():
        slacks = re.findall(r'(-?\d+\.\d+)\s+slack', content)
        if slacks:
            metrics['wns'] = float(slacks[0])
            metrics['tns'] = sum(float(s) for s in slacks if float(s) < 0)
            metrics['violations'] = sum(1 for s in slacks if float(s) < 0)
            break
for f in sorted(glob.glob(os.path.join(rpt_dir, '*drc*'))):
    with open(f) as fh:
        lines = fh.readlines()
    metrics['drc_violations'] = len([l for l in lines if 'violation' in l.lower()])
    break
# Design area from logs
for f in sorted(glob.glob(os.path.join(rpt_dir, '*.log')), reverse=True):
    with open(f) as fh:
        content = fh.read()
    m = re.findall(r'Design area (\d+) um\^2 (\d+)% utilization', content)
    if m:
        metrics['area_um2'] = int(m[-1][0])
        metrics['utilization_pct'] = int(m[-1][1])
        break
with open(os.path.join('$result_dir', 'metrics.json'), 'w') as fh:
    json.dump(metrics, fh, indent=2)
print(json.dumps(metrics, indent=2))
" 2>/dev/null || echo '{"status": "metrics extraction skipped"}'

    rm -f "$result_dir/.running"

    if [ $exit_code -eq 0 ]; then
        echo "DONE" > "$result_dir/.complete"
    else
        echo "FAILED exit_code=$exit_code" > "$result_dir/.failed"
    fi

    mv "$job_file" "$job_file.done"
    echo "=== Job $job_id finished (exit=$exit_code, ${elapsed}s) ==="
}

# Wait for initial flow if running
if [[ -n "${INITIAL_PID:-}" ]]; then
    wait "$INITIAL_PID" 2>/dev/null || true
fi

# Main watch loop
while true; do
    for job_file in "$JOBS_DIR"/*.json; do
        [ -f "$job_file" ] || continue
        process_job "$job_file"
    done
    sleep 2
done

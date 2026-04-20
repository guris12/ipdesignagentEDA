#!/bin/bash
set -euo pipefail

DESIGN=${1:-gcd}
PDK=${2:-sky130hd}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR="/shared/reports/${DESIGN}_${PDK}_${TIMESTAMP}"

echo "=== OpenROAD Flow: ${DESIGN} / ${PDK} ==="
echo "=== Output: ${OUTPUT_DIR} ==="

cd /OpenROAD-flow-scripts/flow

# Run full flow: synth → floorplan → place → CTS → route → finish (STA)
make DESIGN_CONFIG="designs/${PDK}/${DESIGN}/config.mk" 2>&1 | tee "/tmp/flow_${DESIGN}.log"

# Copy results to shared volume
mkdir -p "${OUTPUT_DIR}"
cp -r "results/${PDK}/${DESIGN}/base/"*.rpt "${OUTPUT_DIR}/" 2>/dev/null || true
cp -r "logs/${PDK}/${DESIGN}/base/"*.log "${OUTPUT_DIR}/" 2>/dev/null || true
cp "/tmp/flow_${DESIGN}.log" "${OUTPUT_DIR}/full_flow.log"

# Extract key metrics for the agent
python3 -c "
import re, json, glob, os

metrics = {'design': '${DESIGN}', 'pdk': '${PDK}', 'timestamp': '${TIMESTAMP}'}
rpt_dir = '${OUTPUT_DIR}'

# Parse setup slack from final timing report
for f in sorted(glob.glob(os.path.join(rpt_dir, '*.rpt'))):
    with open(f) as fh:
        content = fh.read()
    if 'slack' in content.lower():
        slacks = re.findall(r'(-?\d+\.\d+)\s+slack', content)
        if slacks:
            metrics['wns'] = float(slacks[0])
            metrics['tns'] = sum(float(s) for s in slacks if float(s) < 0)
            metrics['paths'] = len(slacks)
            metrics['violations'] = sum(1 for s in slacks if float(s) < 0)
            break

# Parse DRC count
for f in sorted(glob.glob(os.path.join(rpt_dir, '*drc*'))):
    with open(f) as fh:
        lines = fh.readlines()
    metrics['drc_violations'] = len([l for l in lines if 'violation' in l.lower()])
    break

with open(os.path.join(rpt_dir, 'metrics.json'), 'w') as fh:
    json.dump(metrics, fh, indent=2)
print(json.dumps(metrics, indent=2))
" 2>/dev/null || echo '{"status": "metrics extraction skipped"}'

# Signal completion
echo "DONE" > "${OUTPUT_DIR}/.complete"
echo "=== Flow complete. Reports in ${OUTPUT_DIR} ==="
ls -la "${OUTPUT_DIR}/"

# Done — job_server.sh handles container lifecycle

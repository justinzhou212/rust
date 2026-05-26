#!/usr/bin/env bash
# Reproducible Docker Image Benchmark - Test Runner
#
# Generates fixtures from seed, runs the submitted tool through A/B/C builds
# in isolated environments, and validates OCI output, digest equality,
# rootfs equality, runtime behavior, and diagnosis correctness.
#
# Usage:
#   ./test.sh                           # Run with default seed
#   ./test.sh --seed 20260526           # Run with specific seed
#   ./test.sh --submission ./path       # Specify submission directory
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEED="${REPRO_BENCH_SEED:-20260526}"
SUBMISSION="${1:-$SCRIPT_DIR/submissions/repro-docker}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --seed) SEED="$2"; shift 2 ;;
        --submission) SUBMISSION="$2"; shift 2 ;;
        *) shift ;;
    esac
done

export REPRO_BENCH_SEED="$SEED"

echo "=== Reproducible Docker Benchmark ==="
echo "Seed: $SEED"
echo "Submission: $SUBMISSION"
echo ""

# Install Python dependencies for the harness
pip install --quiet --no-cache-dir \
    jsonschema==4.23.0 \
    pyyaml==6.0.2 2>/dev/null || true

# Generate fixtures
echo "--- Generating fixtures ---"
python3 "$SCRIPT_DIR/fixturegen/generate_all.py" \
    --seed "$SEED" \
    --out "$SCRIPT_DIR/fixtures"

# Run all fixtures
echo ""
echo "--- Running benchmark ---"
python3 "$SCRIPT_DIR/runner/run_all.py" \
    --submission "$SUBMISSION" \
    --fixtures "$SCRIPT_DIR/fixtures" \
    --seed "$SEED"

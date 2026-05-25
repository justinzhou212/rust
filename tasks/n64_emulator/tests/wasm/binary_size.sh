#!/usr/bin/env bash
# =============================================================================
# Gate: WASM binary size
#
# Ensures the WASM binary stays under 15 MB after wasm-opt. Large binaries
# cause slow page loads and poor UX. This gate prevents size regressions.
#
# Thresholds:
#   - Hard fail:  > 15 MB (unacceptable for browser delivery)
#   - Warning:    > 10 MB (should investigate)
#   - Ideal:      < 8 MB
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/../../../app"
MAX_SIZE_BYTES=$((15 * 1024 * 1024))   # 15 MB
WARN_SIZE_BYTES=$((10 * 1024 * 1024))  # 10 MB

cd "$APP_DIR"

WASM_FILE=$(find target/wasm32-unknown-unknown/release -name "*.wasm" -not -name "*.d" 2>/dev/null | head -1)

if [ -z "$WASM_FILE" ]; then
    echo "ERROR: No .wasm file found. Run the WASM build gate first."
    exit 1
fi

RAW_SIZE=$(stat -c%s "$WASM_FILE" 2>/dev/null || stat -f%z "$WASM_FILE")
echo "Raw WASM size: $RAW_SIZE bytes ($(echo "scale=2; $RAW_SIZE / 1048576" | bc) MB)"

# Run wasm-opt if available for optimized size measurement
OPT_SIZE=$RAW_SIZE
if command -v wasm-opt &>/dev/null; then
    OPT_FILE="/tmp/n64_optimized.wasm"
    echo "Running wasm-opt -Oz..."
    wasm-opt -Oz "$WASM_FILE" -o "$OPT_FILE" 2>&1 || true
    if [ -f "$OPT_FILE" ]; then
        OPT_SIZE=$(stat -c%s "$OPT_FILE" 2>/dev/null || stat -f%z "$OPT_FILE")
        echo "Optimized WASM size: $OPT_SIZE bytes ($(echo "scale=2; $OPT_SIZE / 1048576" | bc) MB)"
        rm -f "$OPT_FILE"
    fi
else
    echo "WARN: wasm-opt not found, checking raw size"
fi

# Use the smaller of raw/optimized for gating
CHECK_SIZE=$OPT_SIZE
if [ "$RAW_SIZE" -lt "$OPT_SIZE" ]; then
    CHECK_SIZE=$RAW_SIZE
fi

if [ "$CHECK_SIZE" -gt "$MAX_SIZE_BYTES" ]; then
    echo "FAIL: WASM binary ($CHECK_SIZE bytes) exceeds maximum ($MAX_SIZE_BYTES bytes / 15 MB)"
    echo "Consider: tree-shaking unused code, splitting crates, using wasm-opt -Oz"
    exit 1
fi

if [ "$CHECK_SIZE" -gt "$WARN_SIZE_BYTES" ]; then
    echo "WARN: WASM binary ($CHECK_SIZE bytes) exceeds warning threshold ($WARN_SIZE_BYTES bytes / 10 MB)"
    echo "Not a failure, but investigate size reduction opportunities."
fi

echo "Binary size gate passed: $(echo "scale=2; $CHECK_SIZE / 1048576" | bc) MB < 15 MB"

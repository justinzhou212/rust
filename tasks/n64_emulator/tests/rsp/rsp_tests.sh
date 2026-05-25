#!/usr/bin/env bash
# =============================================================================
# Gate: RSP Correctness
#
# Verifies the Reality Signal Processor (RSP) implementation against multiple
# test suites:
#
# 1. n64-systemtest RSP section — vector/scalar/DMA tests (subset of the
#    full n64-systemtest ROM, but we parse RSP-specific results)
# 2. Peter Lemon's RSP test ROMs — bare-metal assembly tests for individual
#    RSP operations (XBUS, vector ops, etc.)
#
# RSP correctness is critical because:
#   - Audio processing runs as RSP microcode
#   - Many games use custom RSP microcode for geometry/lighting
#   - The vector unit has unusual 48-bit accumulator semantics that are
#     easy to get wrong
#
# All tests are deterministic and non-visual. Each test loads specific inputs
# into DMEM, runs RSP code, and checks DMEM output against expected values.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$SCRIPT_DIR/../.."
APP_DIR="$TASK_DIR/../../app"
ROM_DIR="$TASK_DIR/reference/test_roms"
CLI="$APP_DIR/target/release/n64-cli"

if [ ! -f "$CLI" ]; then
    echo "ERROR: n64-cli not found at $CLI"
    exit 1
fi

PASS_COUNT=0
FAIL_COUNT=0
FAILED_TESTS=()

run_rsp_test() {
    local name="$1"
    local rom="$2"
    local timeout="${3:-60}"

    if [ ! -f "$rom" ]; then
        echo "SKIP: $name — ROM not found at $rom"
        return
    fi

    echo "  Running: $name"
    OUTPUT=$("$CLI" test "$rom" --timeout "$timeout" 2>&1) || true

    # Check for pass in the output — test ROMs print PASS/FAIL
    if echo "$OUTPUT" | grep -qi "failed\|error\|fail"; then
        # Check if it's "Failed 0" (which is a pass)
        if echo "$OUTPUT" | grep -qP 'Failed 0'; then
            PASS_COUNT=$((PASS_COUNT + 1))
            echo "    PASS"
        else
            FAIL_COUNT=$((FAIL_COUNT + 1))
            FAILED_TESTS+=("$name")
            echo "    FAIL"
            echo "$OUTPUT" | tail -5
        fi
    elif echo "$OUTPUT" | grep -qi "pass\|success\|done"; then
        PASS_COUNT=$((PASS_COUNT + 1))
        echo "    PASS"
    else
        # No recognizable output — possible crash or timeout
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_TESTS+=("$name")
        echo "    FAIL (no recognizable output — possible crash/timeout)"
        echo "$OUTPUT" | tail -5
    fi
}

echo "========================================="
echo "RSP Test Suite"
echo "========================================="

# --- n64-systemtest RSP tests ---
echo ""
echo "--- n64-systemtest RSP section ---"
N64_SYSTEMTEST="$ROM_DIR/n64-systemtest.z64"
if [ -f "$N64_SYSTEMTEST" ]; then
    echo "  Running n64-systemtest (RSP tests are embedded)..."
    OUTPUT=$("$CLI" test "$N64_SYSTEMTEST" --timeout 120 2>&1) || true

    # Extract RSP-specific results if available
    RSP_LINES=$(echo "$OUTPUT" | grep -i "rsp\|vector\|vmu\|vadd\|vsub\|vmulf" || true)
    if [ -n "$RSP_LINES" ]; then
        echo "$RSP_LINES"
    fi

    # Check overall pass/fail
    if echo "$OUTPUT" | grep -qP 'Failed 0 of'; then
        PASS_COUNT=$((PASS_COUNT + 1))
        echo "    PASS (RSP tests within n64-systemtest)"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_TESTS+=("n64-systemtest-rsp")
        echo "    FAIL (some tests failed in n64-systemtest)"
    fi
else
    echo "  SKIP: n64-systemtest ROM not found"
fi

# --- Peter Lemon RSP test ROMs ---
echo ""
echo "--- Peter Lemon RSP tests ---"
PL_RSP_DIR="$ROM_DIR/peterlemon/RSPTest"
if [ -d "$PL_RSP_DIR" ]; then
    for rom_file in $(find "$PL_RSP_DIR" -name "*.N64" -o -name "*.z64" -o -name "*.n64" 2>/dev/null | sort); do
        test_name="PL/$(basename "$(dirname "$rom_file")")/$(basename "$rom_file" | sed 's/\.[^.]*$//')"
        run_rsp_test "$test_name" "$rom_file" 30
    done
else
    echo "  SKIP: Peter Lemon RSP test ROMs not found at $PL_RSP_DIR"
fi

# --- Summary ---
echo ""
echo "========================================="
echo "RSP Test Summary"
echo "========================================="
echo "  Passed: $PASS_COUNT"
echo "  Failed: $FAIL_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo ""
    echo "  Failed tests:"
    for t in "${FAILED_TESTS[@]}"; do
        echo "    - $t"
    done
    exit 1
fi

if [ "$PASS_COUNT" -eq 0 ]; then
    echo "ERROR: No RSP tests ran. Ensure test ROMs are fetched."
    exit 1
fi

echo "All RSP tests passed."

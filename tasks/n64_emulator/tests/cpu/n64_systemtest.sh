#!/usr/bin/env bash
# =============================================================================
# Gate: CPU Correctness — n64-systemtest
#
# Runs the n64-systemtest ROM (3,650+ hardware tests) in headless mode and
# verifies zero test failures. This is the primary CPU/FPU/TLB/exception
# correctness gate.
#
# n64-systemtest is a self-reporting test ROM: it prints a summary line like:
#   "Finished in 3.96s. Base: Failed 0 of 3650 tests (100% success rate)"
#
# We parse this line and fail if failures > 0.
#
# Test coverage includes:
#   - All integer arithmetic ops (ADD, SUB, MULT, DIV, DADD, etc.)
#   - All FPU ops (CVT, ROUND, TRUNC with all rounding modes)
#   - COP0 register behavior (MFC0, MTC0, DMFC0, DMTC0)
#   - TLB operations (TLBWI, TLBWR, TLBR, TLBP, miss/invalid exceptions)
#   - Exception handling (overflow, unaligned, trap, break, syscall)
#   - Memory access (8/16/32/64-bit to RAM, ROM, SPMEM, PIF)
#   - RSP scalar/vector/DMA operations
#   - Atomic operations (LL/SC, LLD/SCD)
#   - Cache operations
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$SCRIPT_DIR/../.."
APP_DIR="$TASK_DIR/../../app"
ROM_DIR="$TASK_DIR/reference/test_roms"
CLI="$APP_DIR/target/release/n64-cli"

N64_SYSTEMTEST_ROM="$ROM_DIR/n64-systemtest.z64"

if [ ! -f "$N64_SYSTEMTEST_ROM" ]; then
    echo "ERROR: n64-systemtest ROM not found at $N64_SYSTEMTEST_ROM"
    echo "Run scripts/fetch_test_roms.sh first."
    exit 1
fi

if [ ! -f "$CLI" ]; then
    echo "ERROR: n64-cli not found at $CLI"
    echo "Run 'cargo build --release' in $APP_DIR first."
    exit 1
fi

echo "Running n64-systemtest (3,650+ tests)..."
echo "ROM: $N64_SYSTEMTEST_ROM"

# Run with a generous timeout — n64-systemtest takes ~4 seconds on hardware,
# emulated it may take longer. 120 seconds should be safe.
TIMEOUT=120
OUTPUT=$("$CLI" test "$N64_SYSTEMTEST_ROM" --timeout "$TIMEOUT" 2>&1) || true

echo "$OUTPUT"

# Parse the summary line
# Expected format: "Finished in X.XXs. Base: Failed N of M tests (XX% success rate)"
SUMMARY=$(echo "$OUTPUT" | grep -oP 'Failed \d+ of \d+ tests' | tail -1)

if [ -z "$SUMMARY" ]; then
    echo "ERROR: Could not find test summary in output."
    echo "Expected a line like: 'Failed 0 of 3650 tests'"
    echo "The emulator may have crashed or timed out."
    exit 1
fi

FAILED=$(echo "$SUMMARY" | grep -oP 'Failed \K\d+')
TOTAL=$(echo "$SUMMARY" | grep -oP 'of \K\d+')

echo ""
echo "Results: $SUMMARY"

if [ "$FAILED" -ne 0 ]; then
    echo "FAIL: $FAILED of $TOTAL tests failed."
    echo ""
    echo "Common failure categories and what they indicate:"
    echo "  - COP1 (FPU) failures → floating point rounding/conversion bugs"
    echo "  - TLB failures → virtual memory translation issues"
    echo "  - Exception failures → incorrect EPC/Cause/Status register updates"
    echo "  - RSP failures → RSP scalar/vector opcode bugs"
    echo "  - Memory access failures → bus/MMIO implementation issues"
    exit 1
fi

if [ "$TOTAL" -lt 3600 ]; then
    echo "WARN: Only $TOTAL tests ran (expected 3,650+). Some tests may have been skipped."
    echo "This could indicate the emulator crashed mid-run."
    exit 1
fi

echo "PASS: All $TOTAL tests passed."

#!/usr/bin/env bash
# =============================================================================
# N64 Emulator — Master Test Runner
#
# Runs all verification layers in order of increasing cost. Fails fast on
# any gate failure. Exit 0 only if every gate passes.
#
# Usage:
#   ./test.sh              # Run all gates
#   ./test.sh <suite>      # Run a single suite (cpu|rsp|rdp|integration|
#                          #   performance|wasm|demo)
#   ./test.sh --list       # List available suites
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/../../app"
TESTS_DIR="$SCRIPT_DIR/tests"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"
RESULTS_DIR="$SCRIPT_DIR/test-results"

mkdir -p "$RESULTS_DIR"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

pass()  { echo -e "${GREEN}[PASS]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; }
info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }

TOTAL=0
PASSED=0
FAILED=0
FAILED_NAMES=()

run_gate() {
    local name="$1"
    local script="$2"
    TOTAL=$((TOTAL + 1))
    info "Running gate: $name"
    if bash "$script" > "$RESULTS_DIR/${name}.log" 2>&1; then
        pass "$name"
        PASSED=$((PASSED + 1))
    else
        fail "$name (see $RESULTS_DIR/${name}.log)"
        FAILED=$((FAILED + 1))
        FAILED_NAMES+=("$name")
        # Print last 20 lines of log for diagnosis
        echo "--- Last 20 lines of ${name}.log ---"
        tail -20 "$RESULTS_DIR/${name}.log" || true
        echo "--- End ---"
    fi
}

# ---------------------------------------------------------------------------
# Ensure test ROMs are available
# ---------------------------------------------------------------------------
ensure_test_roms() {
    if [ ! -d "$SCRIPT_DIR/reference/test_roms" ]; then
        info "Fetching test ROMs..."
        bash "$SCRIPTS_DIR/fetch_test_roms.sh"
    fi
}

# ---------------------------------------------------------------------------
# Suite definitions
# ---------------------------------------------------------------------------
run_wasm_suite() {
    info "========== WASM BUILD GATES =========="
    run_gate "build_native"       "$TESTS_DIR/wasm/build_native.sh"
    run_gate "build_wasm"         "$TESTS_DIR/wasm/build_wasm.sh"
    run_gate "binary_size"        "$TESTS_DIR/wasm/binary_size.sh"
    run_gate "clippy"             "$TESTS_DIR/wasm/clippy.sh"
}

run_cpu_suite() {
    info "========== CPU CORRECTNESS =========="
    ensure_test_roms
    run_gate "n64_systemtest"     "$TESTS_DIR/cpu/n64_systemtest.sh"
}

run_rsp_suite() {
    info "========== RSP CORRECTNESS =========="
    ensure_test_roms
    run_gate "rsp_tests"          "$TESTS_DIR/rsp/rsp_tests.sh"
}

run_rdp_suite() {
    info "========== RDP BIT-EXACT =========="
    ensure_test_roms
    run_gate "rdp_bitexact"       "$TESTS_DIR/rdp/bitexact.sh"
}

run_integration_suite() {
    info "========== INTEGRATION =========="
    ensure_test_roms
    run_gate "homebrew_boot"      "$TESTS_DIR/integration/homebrew_boot.sh"
    run_gate "demo_site"          "$TESTS_DIR/integration/demo_site.sh"
}

run_performance_suite() {
    info "========== PERFORMANCE =========="
    ensure_test_roms
    run_gate "native_benchmark"   "$TESTS_DIR/performance/native_benchmark.sh"
    run_gate "wasm_benchmark"     "$TESTS_DIR/performance/wasm_benchmark.sh"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
case "${1:-all}" in
    --list)
        echo "Available suites:"
        echo "  wasm          Build gates (native, WASM, binary size, clippy)"
        echo "  cpu           CPU correctness (n64-systemtest, 3650+ tests)"
        echo "  rsp           RSP correctness (vector/scalar/DMA)"
        echo "  rdp           RDP bit-exact verification vs Angrylion"
        echo "  integration   Homebrew ROM boot + demo site"
        echo "  performance   Native and WASM performance benchmarks"
        echo "  all           Run all suites (default)"
        exit 0
        ;;
    wasm)         run_wasm_suite ;;
    cpu)          run_cpu_suite ;;
    rsp)          run_rsp_suite ;;
    rdp)          run_rdp_suite ;;
    integration)  run_integration_suite ;;
    performance)  run_performance_suite ;;
    all)
        run_wasm_suite
        run_cpu_suite
        run_rsp_suite
        run_rdp_suite
        run_integration_suite
        run_performance_suite
        ;;
    *)
        echo "Unknown suite: $1" >&2
        echo "Run '$0 --list' for available suites." >&2
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "  TEST SUMMARY"
echo "============================================"
echo -e "  Total:  $TOTAL"
echo -e "  ${GREEN}Passed: $PASSED${NC}"
if [ "$FAILED" -gt 0 ]; then
    echo -e "  ${RED}Failed: $FAILED${NC}"
    for name in "${FAILED_NAMES[@]}"; do
        echo -e "    ${RED}- $name${NC}"
    done
    echo "============================================"
    exit 1
else
    echo "============================================"
    echo -e "${GREEN}All gates passed.${NC}"
    exit 0
fi

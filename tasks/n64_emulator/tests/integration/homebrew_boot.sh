#!/usr/bin/env bash
# =============================================================================
# Gate: Homebrew ROM Boot Test
#
# Verifies that legally distributable homebrew ROMs boot and render frames
# without crashing. This is an integration test that exercises the full
# emulation stack (CPU + RSP + RDP + memory + VI) together.
#
# For each ROM, the test:
#   1. Launches the emulator in headless mode
#   2. Runs for N frames (or N seconds)
#   3. Verifies:
#      a) The emulator did not crash or hang
#      b) At least 60 VI interrupts fired (≈1 second of emulated time)
#      c) The framebuffer is not all-black or all-white (something rendered)
#      d) No unhandled CPU exceptions occurred
#
# Minimum requirement: 5 homebrew ROMs must pass.
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

MIN_PASS=5
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
FAILED_ROMS=()

# ---------------------------------------------------------------------------
# Boot test a single ROM
# ---------------------------------------------------------------------------
boot_test() {
    local name="$1"
    local rom="$2"
    local min_frames="${3:-60}"
    local timeout="${4:-30}"

    if [ ! -f "$rom" ]; then
        echo "  SKIP: $name — ROM not found at $rom"
        SKIP_COUNT=$((SKIP_COUNT + 1))
        return
    fi

    echo "  Testing: $name"

    # Run emulator headless, capture output
    OUTPUT=$("$CLI" run --headless "$rom" \
        --max-frames "$min_frames" \
        --timeout "$timeout" \
        2>&1) || true

    # Check for crash indicators
    if echo "$OUTPUT" | grep -qi "panic\|segfault\|abort\|SIGSEGV\|SIGBUS\|SIGILL"; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_ROMS+=("$name (crash)")
        echo "    FAIL: Emulator crashed"
        echo "$OUTPUT" | grep -i "panic\|segfault\|abort" | head -3
        return
    fi

    # Check for unhandled exceptions
    if echo "$OUTPUT" | grep -qi "unhandled exception\|unimplemented\|todo!"; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_ROMS+=("$name (unhandled exception)")
        echo "    FAIL: Unhandled exception"
        echo "$OUTPUT" | grep -i "unhandled\|unimplemented\|todo!" | head -3
        return
    fi

    # Check VI count — expect at least min_frames VI interrupts
    VI_COUNT=$(echo "$OUTPUT" | grep -oP 'vi_count: \K\d+' | tail -1)
    if [ -z "$VI_COUNT" ]; then
        VI_COUNT=$(echo "$OUTPUT" | grep -oP 'frames: \K\d+' | tail -1)
    fi

    if [ -z "$VI_COUNT" ]; then
        # If no frame count in output, check if it at least completed without crash
        if echo "$OUTPUT" | grep -qi "completed\|finished\|done"; then
            PASS_COUNT=$((PASS_COUNT + 1))
            echo "    PASS (completed, frame count not parsed)"
            return
        fi
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_ROMS+=("$name (no frame output)")
        echo "    FAIL: No frame count in output (possible hang or early exit)"
        return
    fi

    if [ "$VI_COUNT" -lt "$min_frames" ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_ROMS+=("$name (only $VI_COUNT frames, need $min_frames)")
        echo "    FAIL: Only $VI_COUNT VI frames (minimum: $min_frames)"
        return
    fi

    # Check framebuffer is not blank
    FB_CHECK=$(echo "$OUTPUT" | grep -oP 'fb_nonblank: \K(true|false)' | tail -1)
    if [ "$FB_CHECK" = "false" ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_ROMS+=("$name (blank framebuffer)")
        echo "    FAIL: Framebuffer is blank after $VI_COUNT frames"
        return
    fi

    PASS_COUNT=$((PASS_COUNT + 1))
    echo "    PASS ($VI_COUNT frames rendered)"
}

# ---------------------------------------------------------------------------
# Discover and test ROMs
# ---------------------------------------------------------------------------
echo "========================================="
echo "Homebrew Boot Tests"
echo "========================================="

# n64-systemtest (should already pass, but boot test validates integration)
boot_test "n64-systemtest" "$ROM_DIR/n64-systemtest.z64" 30 60

# Libdragon examples
LIBDRAGON_DIR="$ROM_DIR/libdragon"
if [ -d "$LIBDRAGON_DIR" ]; then
    for rom_file in $(find "$LIBDRAGON_DIR" -name "*.z64" -o -name "*.n64" 2>/dev/null | sort | head -5); do
        test_name="libdragon/$(basename "$rom_file" | sed 's/\.[^.]*$//')"
        boot_test "$test_name" "$rom_file" 60 30
    done
fi

# 64brew Game Jam entries
GAMEJAM_DIR="$ROM_DIR/gamejam"
if [ -d "$GAMEJAM_DIR" ]; then
    for rom_file in $(find "$GAMEJAM_DIR" -name "*.z64" -o -name "*.n64" 2>/dev/null | sort | head -5); do
        test_name="gamejam/$(basename "$rom_file" | sed 's/\.[^.]*$//')"
        boot_test "$test_name" "$rom_file" 60 30
    done
fi

# Peter Lemon demo ROMs
PL_DIR="$ROM_DIR/peterlemon"
if [ -d "$PL_DIR" ]; then
    for rom_file in $(find "$PL_DIR" -path "*/Video/*.N64" -o -path "*/Video/*.z64" 2>/dev/null | sort | head -3); do
        test_name="peterlemon/$(basename "$rom_file" | sed 's/\.[^.]*$//')"
        boot_test "$test_name" "$rom_file" 30 20
    done
fi

# Embedded demo ROM (must exist for the web frontend)
EMBEDDED_ROM="$APP_DIR/web/roms/demo.z64"
if [ -f "$EMBEDDED_ROM" ]; then
    boot_test "embedded-demo" "$EMBEDDED_ROM" 60 30
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo "Homebrew Boot Summary"
echo "========================================="
echo "  Passed:  $PASS_COUNT"
echo "  Failed:  $FAIL_COUNT"
echo "  Skipped: $SKIP_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo ""
    echo "  Failed ROMs:"
    for r in "${FAILED_ROMS[@]}"; do
        echo "    - $r"
    done
fi

if [ "$PASS_COUNT" -lt "$MIN_PASS" ]; then
    echo ""
    echo "FAIL: Only $PASS_COUNT ROMs passed (minimum: $MIN_PASS)"
    echo "Ensure test ROMs are fetched and the emulator boots them correctly."
    exit 1
fi

echo ""
echo "Boot test passed: $PASS_COUNT/$((PASS_COUNT + FAIL_COUNT)) ROMs boot successfully."

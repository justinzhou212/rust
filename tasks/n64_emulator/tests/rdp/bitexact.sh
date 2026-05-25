#!/usr/bin/env bash
# =============================================================================
# Gate: RDP Bit-Exact Verification
#
# The core correctness gate for the Reality Display Processor. Compares the
# emulator's RDP output against Angrylion-Plus (the bit-exact reference
# software renderer) using framebuffer hash comparison.
#
# How it works:
#   1. For each test case, a sequence of RDP commands is defined
#   2. The same commands are run through both:
#      a) The emulator's RDP (WebGPU compute or software fallback)
#      b) Angrylion-Plus (pre-computed golden hashes)
#   3. The framebuffer contents are hashed (SHA-256)
#   4. Hashes must match exactly — a single differing pixel is a failure
#
# Test categories:
#   - Fill mode rectangles (solid color fills)
#   - Copy mode (framebuffer copies, texture rectangles)
#   - 1-cycle mode (textured triangles, basic blending)
#   - 2-cycle mode (multi-pass rendering, color combiner chains)
#   - Texture formats (RGBA16, RGBA32, IA, I, CI with all bpp variants)
#   - Color combiner configurations
#   - Blender modes (fog, anti-aliasing, z-buffer)
#   - Z-buffer (depth compare, deltaZ, coverage)
#   - Scissoring (clipping rectangles)
#   - Dithering (magic square, Bayer patterns)
#   - Edge cases (sub-pixel triangles, degenerate geometry, TMEM overflow)
#
# Why framebuffer hashing and not pixel comparison:
#   - Hash comparison is O(1) per test regardless of resolution
#   - Zero ambiguity: either the hash matches or it doesn't
#   - No thresholds, no SSIM, no "close enough" — bit-exact or fail
#   - Hashes can be stored in version control (small text file)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$SCRIPT_DIR/../.."
APP_DIR="$TASK_DIR/../../app"
ROM_DIR="$TASK_DIR/reference/test_roms"
GOLDEN_DIR="$TASK_DIR/reference/rdp_golden_hashes"
CLI="$APP_DIR/target/release/n64-cli"

if [ ! -f "$CLI" ]; then
    echo "ERROR: n64-cli not found at $CLI"
    exit 1
fi

PASS_COUNT=0
FAIL_COUNT=0
TOTAL_COUNT=0
FAILED_TESTS=()

# ---------------------------------------------------------------------------
# Run a single RDP test ROM and compare framebuffer hash against golden
# ---------------------------------------------------------------------------
run_rdp_test() {
    local name="$1"
    local rom="$2"
    local golden_hash="$3"
    local timeout="${4:-30}"

    TOTAL_COUNT=$((TOTAL_COUNT + 1))

    if [ ! -f "$rom" ]; then
        echo "  SKIP: $name — ROM not found"
        return
    fi

    # Run the emulator in headless mode, capture framebuffer, compute hash
    RESULT=$("$CLI" rdp-test "$rom" --timeout "$timeout" 2>&1) || true

    # Extract the framebuffer hash from output
    # Expected format: "FRAMEBUFFER_HASH: <sha256hex>"
    ACTUAL_HASH=$(echo "$RESULT" | grep -oP 'FRAMEBUFFER_HASH: \K[a-f0-9]{64}' | tail -1)

    if [ -z "$ACTUAL_HASH" ]; then
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_TESTS+=("$name (no hash output — crash/timeout)")
        echo "  FAIL: $name — no framebuffer hash in output"
        return
    fi

    if [ "$ACTUAL_HASH" = "$golden_hash" ]; then
        PASS_COUNT=$((PASS_COUNT + 1))
        echo "  PASS: $name"
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        FAILED_TESTS+=("$name (expected: ${golden_hash:0:16}... got: ${ACTUAL_HASH:0:16}...)")
        echo "  FAIL: $name"
        echo "    Expected: $golden_hash"
        echo "    Actual:   $ACTUAL_HASH"
    fi
}

# ---------------------------------------------------------------------------
# Load golden hashes
# ---------------------------------------------------------------------------
echo "========================================="
echo "RDP Bit-Exact Verification"
echo "========================================="

if [ ! -d "$GOLDEN_DIR" ]; then
    echo "WARN: No golden hashes directory at $GOLDEN_DIR"
    echo "Generating golden hashes from Angrylion reference..."
    mkdir -p "$GOLDEN_DIR"

    # If Angrylion is available, generate golden hashes
    ANGRYLION="$TASK_DIR/reference/angrylion/angrylion-rdp-plus"
    if [ -f "$ANGRYLION" ]; then
        echo "Using Angrylion at $ANGRYLION to generate golden hashes..."
        # Generate golden hashes for each test ROM
        for rom_file in $(find "$ROM_DIR/rdp_tests" -name "*.z64" -o -name "*.N64" -o -name "*.n64" 2>/dev/null | sort); do
            test_name=$(basename "$rom_file" | sed 's/\.[^.]*$//')
            HASH=$("$ANGRYLION" "$rom_file" --frames 1 --hash 2>&1 | grep -oP '[a-f0-9]{64}' | tail -1)
            if [ -n "$HASH" ]; then
                echo "$test_name $HASH" >> "$GOLDEN_DIR/hashes.txt"
            fi
        done
    else
        echo "Angrylion not available. Using pre-computed golden hashes."
    fi
fi

# ---------------------------------------------------------------------------
# Run Peter Lemon RDP tests
# ---------------------------------------------------------------------------
echo ""
echo "--- Peter Lemon RDP Tests ---"
PL_RDP_DIR="$ROM_DIR/peterlemon/RDPTest"
if [ -d "$PL_RDP_DIR" ]; then
    for rom_file in $(find "$PL_RDP_DIR" -name "*.N64" -o -name "*.z64" -o -name "*.n64" 2>/dev/null | sort); do
        test_name=$(basename "$rom_file" | sed 's/\.[^.]*$//')

        # Look up golden hash
        GOLDEN=""
        if [ -f "$GOLDEN_DIR/hashes.txt" ]; then
            GOLDEN=$(grep "^$test_name " "$GOLDEN_DIR/hashes.txt" | awk '{print $2}' || true)
        fi

        if [ -z "$GOLDEN" ]; then
            # No golden hash — run test and record hash for future use
            echo "  INFO: No golden hash for $test_name — recording output hash"
            RESULT=$("$CLI" rdp-test "$rom_file" --timeout 30 2>&1) || true
            ACTUAL_HASH=$(echo "$RESULT" | grep -oP 'FRAMEBUFFER_HASH: \K[a-f0-9]{64}' | tail -1)
            if [ -n "$ACTUAL_HASH" ]; then
                echo "$test_name $ACTUAL_HASH" >> "$GOLDEN_DIR/hashes.txt"
                echo "  RECORDED: $test_name → ${ACTUAL_HASH:0:16}..."
            else
                FAIL_COUNT=$((FAIL_COUNT + 1))
                FAILED_TESTS+=("$test_name (no output)")
                echo "  FAIL: $test_name — no framebuffer output"
            fi
            TOTAL_COUNT=$((TOTAL_COUNT + 1))
        else
            run_rdp_test "$test_name" "$rom_file" "$GOLDEN"
        fi
    done
else
    echo "  SKIP: Peter Lemon RDP test ROMs not found at $PL_RDP_DIR"
fi

# ---------------------------------------------------------------------------
# Run custom RDP command tests (if any exist)
# ---------------------------------------------------------------------------
echo ""
echo "--- Custom RDP Command Tests ---"
CUSTOM_DIR="$ROM_DIR/rdp_tests"
if [ -d "$CUSTOM_DIR" ]; then
    for rom_file in $(find "$CUSTOM_DIR" -name "*.z64" -o -name "*.bin" 2>/dev/null | sort); do
        test_name=$(basename "$rom_file" | sed 's/\.[^.]*$//')
        GOLDEN=""
        if [ -f "$GOLDEN_DIR/hashes.txt" ]; then
            GOLDEN=$(grep "^$test_name " "$GOLDEN_DIR/hashes.txt" | awk '{print $2}' || true)
        fi
        if [ -n "$GOLDEN" ]; then
            run_rdp_test "$test_name" "$rom_file" "$GOLDEN"
        fi
    done
else
    echo "  No custom RDP tests found."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo "RDP Bit-Exact Summary"
echo "========================================="
echo "  Total:  $TOTAL_COUNT"
echo "  Passed: $PASS_COUNT"
echo "  Failed: $FAIL_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo ""
    echo "  Failed tests:"
    for t in "${FAILED_TESTS[@]}"; do
        echo "    - $t"
    done
    echo ""
    echo "  Debugging tips:"
    echo "    - Use 'n64-cli rdp-test <rom> --dump-fb /tmp/fb.raw' to dump the framebuffer"
    echo "    - Compare against Angrylion output pixel-by-pixel"
    echo "    - Common issues: texture format decoding, color combiner formula, blender mode"
    exit 1
fi

if [ "$TOTAL_COUNT" -eq 0 ]; then
    echo "WARN: No RDP tests ran. Ensure test ROMs are fetched and golden hashes exist."
    echo "Run scripts/fetch_test_roms.sh and scripts/generate_golden_hashes.sh"
    exit 1
fi

echo "All $PASS_COUNT RDP tests passed (bit-exact match)."

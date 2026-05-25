#!/usr/bin/env bash
# =============================================================================
# Generate RDP Golden Hashes
#
# Builds Angrylion-Plus (the reference N64 RDP software renderer) and runs
# each RDP test ROM through it, capturing the framebuffer hash for each.
#
# These golden hashes are the ground truth for the bit-exact RDP verification
# gate. The emulator's RDP output must produce identical hashes.
#
# Output: reference/rdp_golden_hashes/hashes.txt
#   Format: <test_name> <sha256_hex>
#
# Prerequisites:
#   - cmake, make, gcc/clang
#   - Test ROMs fetched (run fetch_test_roms.sh first)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$SCRIPT_DIR/.."
ROM_DIR="$TASK_DIR/reference/test_roms"
GOLDEN_DIR="$TASK_DIR/reference/rdp_golden_hashes"
BUILD_DIR="/tmp/angrylion-build"

mkdir -p "$GOLDEN_DIR"
mkdir -p "$BUILD_DIR"

echo "========================================="
echo "Generating RDP Golden Hashes"
echo "========================================="

# ---------------------------------------------------------------------------
# Build Angrylion-Plus
# ---------------------------------------------------------------------------
ANGRYLION_DIR="$BUILD_DIR/angrylion-rdp-plus"
ANGRYLION_BIN=""

if [ ! -d "$ANGRYLION_DIR" ]; then
    echo "Cloning Angrylion-Plus..."
    git clone --depth 1 https://github.com/ata4/angrylion-rdp-plus.git "$ANGRYLION_DIR" 2>&1
fi

echo "Building Angrylion-Plus..."
cd "$ANGRYLION_DIR"
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 || true
make -j"$(nproc)" 2>&1 || true

# Find the built binary
ANGRYLION_BIN=$(find . -name "angrylion-rdp-plus" -executable 2>/dev/null | head -1)
if [ -z "$ANGRYLION_BIN" ]; then
    ANGRYLION_BIN=$(find . -name "*.so" -o -name "*.dll" 2>/dev/null | head -1)
fi

if [ -z "$ANGRYLION_BIN" ]; then
    echo "WARN: Could not build Angrylion-Plus standalone."
    echo "Angrylion is typically a plugin for mupen64plus or RetroArch."
    echo ""
    echo "Alternative: Use the n64-cli software renderer as the reference."
    echo "Build n64-cli with 'cargo build --release' and use:"
    echo "  n64-cli rdp-test <rom> --renderer software"
    echo ""
    echo "For initial development, you can generate golden hashes from your own"
    echo "software renderer once it matches known-good outputs for simple test cases."
    exit 0
fi

# ---------------------------------------------------------------------------
# Generate hashes for each RDP test ROM
# ---------------------------------------------------------------------------
echo ""
echo "Generating golden hashes..."

> "$GOLDEN_DIR/hashes.txt"  # Clear/create

for rom_dir in "$ROM_DIR/peterlemon/RDPTest" "$ROM_DIR/rdp_tests"; do
    if [ ! -d "$rom_dir" ]; then
        continue
    fi

    for rom_file in $(find "$rom_dir" -name "*.N64" -o -name "*.z64" -o -name "*.n64" 2>/dev/null | sort); do
        test_name=$(basename "$rom_file" | sed 's/\.[^.]*$//')

        echo "  Processing: $test_name"

        # Run through Angrylion, capture framebuffer hash
        HASH=$("$ANGRYLION_BIN" "$rom_file" --frames 1 --hash 2>&1 | \
            grep -oP '[a-f0-9]{64}' | tail -1) || true

        if [ -n "$HASH" ]; then
            echo "$test_name $HASH" >> "$GOLDEN_DIR/hashes.txt"
            echo "    Hash: ${HASH:0:16}..."
        else
            echo "    WARN: No hash output"
        fi
    done
done

TOTAL=$(wc -l < "$GOLDEN_DIR/hashes.txt" 2>/dev/null || echo 0)
echo ""
echo "Generated $TOTAL golden hashes."
echo "Output: $GOLDEN_DIR/hashes.txt"

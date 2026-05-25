#!/usr/bin/env bash
# =============================================================================
# Fetch Test ROMs
#
# Downloads all legally distributable test ROMs and homebrew needed for the
# test suite. Everything fetched here is open-source or freely distributable.
#
# NO copyrighted commercial ROMs are downloaded.
#
# Directory structure after running:
#   reference/test_roms/
#   ├── n64-systemtest.z64          # Hardware test suite (3,650+ tests)
#   ├── peterlemon/                 # Peter Lemon's bare-metal test ROMs
#   │   ├── CPUTest/
#   │   ├── RSPTest/
#   │   ├── RDPTest/
#   │   └── Video/
#   ├── libdragon/                  # libdragon SDK example ROMs
#   └── gamejam/                    # 64brew Game Jam homebrew entries
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$SCRIPT_DIR/.."
ROM_DIR="$TASK_DIR/reference/test_roms"
BUILD_DIR="/tmp/n64-test-rom-build"

mkdir -p "$ROM_DIR"
mkdir -p "$BUILD_DIR"

echo "========================================="
echo "Fetching N64 Test ROMs"
echo "========================================="

# ---------------------------------------------------------------------------
# 1. n64-systemtest
# ---------------------------------------------------------------------------
echo ""
echo "--- n64-systemtest ---"
N64_ST_DIR="$BUILD_DIR/n64-systemtest"

if [ -f "$ROM_DIR/n64-systemtest.z64" ]; then
    echo "  Already exists, skipping."
else
    echo "  Cloning n64-systemtest..."
    git clone --depth 1 https://github.com/lemmy-64/n64-systemtest.git "$N64_ST_DIR" 2>&1 || true

    if [ -d "$N64_ST_DIR" ]; then
        echo "  Building n64-systemtest ROM..."
        cd "$N64_ST_DIR"

        # Install nust64 (N64 ROM builder)
        cargo install nust64 2>&1 || true

        # Build the test ROM
        cargo run --release 2>&1 || true

        # Find the built ROM
        ROM_FILE=$(find . -name "*.z64" -o -name "*.n64" 2>/dev/null | head -1)
        if [ -n "$ROM_FILE" ]; then
            cp "$ROM_FILE" "$ROM_DIR/n64-systemtest.z64"
            echo "  Built: n64-systemtest.z64"
        else
            echo "  WARN: Could not build n64-systemtest ROM"
            echo "  Checking for pre-built release..."
            # Try downloading a pre-built ROM from releases
            RELEASE_URL=$(curl -s https://api.github.com/repos/lemmy-64/n64-systemtest/releases/latest | \
                grep -oP '"browser_download_url":\s*"\K[^"]+\.z64' | head -1)
            if [ -n "$RELEASE_URL" ]; then
                curl -L -o "$ROM_DIR/n64-systemtest.z64" "$RELEASE_URL" 2>&1
                echo "  Downloaded pre-built ROM"
            fi
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 2. Peter Lemon's N64 test ROMs
# ---------------------------------------------------------------------------
echo ""
echo "--- Peter Lemon N64 tests ---"
PL_DIR="$BUILD_DIR/peterlemon-n64"

if [ -d "$ROM_DIR/peterlemon" ]; then
    echo "  Already exists, skipping."
else
    echo "  Cloning PeterLemon/N64..."
    git clone --depth 1 https://github.com/PeterLemon/N64.git "$PL_DIR" 2>&1 || true

    if [ -d "$PL_DIR" ]; then
        mkdir -p "$ROM_DIR/peterlemon"

        # Copy pre-built ROMs (Peter Lemon includes .N64 binaries in the repo)
        for dir in CPUTest RSPTest RDPTest Video; do
            if [ -d "$PL_DIR/$dir" ]; then
                echo "  Copying $dir..."
                mkdir -p "$ROM_DIR/peterlemon/$dir"
                find "$PL_DIR/$dir" -name "*.N64" -exec cp {} "$ROM_DIR/peterlemon/$dir/" \; 2>/dev/null || true
                COUNT=$(find "$ROM_DIR/peterlemon/$dir" -name "*.N64" 2>/dev/null | wc -l)
                echo "    $COUNT ROMs copied"
            fi
        done
    fi
fi

# ---------------------------------------------------------------------------
# 3. libdragon example ROMs
# ---------------------------------------------------------------------------
echo ""
echo "--- libdragon examples ---"
if [ -d "$ROM_DIR/libdragon" ]; then
    echo "  Already exists, skipping."
else
    echo "  NOTE: libdragon examples require the libdragon toolchain to build."
    echo "  Checking for pre-built example ROMs..."

    mkdir -p "$ROM_DIR/libdragon"

    # libdragon examples need the full toolchain — try Docker build
    if command -v docker &>/dev/null; then
        echo "  Building libdragon examples via Docker..."
        LIBDRAGON_DIR="$BUILD_DIR/libdragon"
        git clone --depth 1 https://github.com/DragonMinded/libdragon.git "$LIBDRAGON_DIR" 2>&1 || true

        if [ -d "$LIBDRAGON_DIR" ]; then
            cd "$LIBDRAGON_DIR"
            # Use the libdragon Docker container to build examples
            docker run --rm -v "$(pwd):/libdragon" ghcr.io/dragonminded/libdragon:latest \
                bash -c "cd /libdragon && make examples" 2>&1 || true

            # Copy built ROMs
            find examples -name "*.z64" -exec cp {} "$ROM_DIR/libdragon/" \; 2>/dev/null || true
            COUNT=$(find "$ROM_DIR/libdragon" -name "*.z64" 2>/dev/null | wc -l)
            echo "  $COUNT libdragon example ROMs built"
        fi
    else
        echo "  Docker not available. Skipping libdragon examples."
        echo "  To build manually: install libdragon toolchain and run 'make examples'"
    fi
fi

# ---------------------------------------------------------------------------
# 4. 64brew Game Jam entries (homebrew games)
# ---------------------------------------------------------------------------
echo ""
echo "--- 64brew Game Jam homebrew ---"
if [ -d "$ROM_DIR/gamejam" ]; then
    echo "  Already exists, skipping."
else
    mkdir -p "$ROM_DIR/gamejam"

    echo "  Checking for Game Jam 2024 release ROM..."
    # The N64brew Game Jam 2024 has a combined ROM release
    GJ_RELEASE=$(curl -s https://api.github.com/repos/n64brew/N64brew-GameJam2024/releases/latest 2>/dev/null | \
        grep -oP '"browser_download_url":\s*"\K[^"]+\.(z64|n64)' | head -1)

    if [ -n "$GJ_RELEASE" ]; then
        echo "  Downloading Game Jam 2024 ROM..."
        curl -L -o "$ROM_DIR/gamejam/gamejam2024.z64" "$GJ_RELEASE" 2>&1 || true
        echo "  Downloaded"
    else
        echo "  No pre-built release found. Individual entries may need manual building."
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "========================================="
echo "Test ROM Summary"
echo "========================================="
echo "Directory: $ROM_DIR"

for sub in "" "peterlemon/CPUTest" "peterlemon/RSPTest" "peterlemon/RDPTest" "peterlemon/Video" "libdragon" "gamejam"; do
    dir="$ROM_DIR/$sub"
    if [ -d "$dir" ]; then
        count=$(find "$dir" -maxdepth 1 \( -name "*.z64" -o -name "*.N64" -o -name "*.n64" \) 2>/dev/null | wc -l)
        echo "  $dir: $count ROMs"
    fi
done

TOTAL=$(find "$ROM_DIR" \( -name "*.z64" -o -name "*.N64" -o -name "*.n64" \) 2>/dev/null | wc -l)
echo ""
echo "Total: $TOTAL test ROMs"

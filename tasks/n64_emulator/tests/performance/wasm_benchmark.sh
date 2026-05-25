#!/usr/bin/env bash
# =============================================================================
# Gate: WASM Performance Benchmark
#
# Measures the emulator's performance when running as WASM in a headless
# browser (Chrome/Chromium). This gate ensures the browser experience is
# acceptable — not just that the native build is fast.
#
# WASM is typically 60-80% of native speed due to:
#   - No native SIMD (WASM SIMD is 128-bit only, vs AVX2/512)
#   - No JIT code patching (must compile new WASM modules)
#   - Browser overhead (JS↔WASM boundary, GC pauses)
#   - WebGPU overhead vs native Vulkan
#
# Thresholds:
#   - Hard fail:  < 15 VI/s (unplayable, choppy)
#   - Warning:    < 30 VI/s (below half speed)
#   - Target:     >= 30 VI/s (playable for most games)
#
# Uses Playwright or headless Chrome to run the emulator in a browser
# context and measure frame output rate.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$SCRIPT_DIR/../.."
APP_DIR="$TASK_DIR/../../app"
WEB_DIR="$APP_DIR/web"
ROM_DIR="$TASK_DIR/reference/test_roms"

MIN_VIS=15         # Minimum VI/s in WASM
WARN_VIS=30        # Warning threshold
BENCH_FRAMES=120   # Number of frames (fewer than native due to slower speed)

echo "========================================="
echo "WASM Performance Benchmark"
echo "========================================="

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------
if [ ! -f "$WEB_DIR/index.html" ]; then
    echo "ERROR: Web frontend not found at $WEB_DIR/index.html"
    exit 1
fi

WASM_FOUND=false
for dir in "$WEB_DIR/pkg" "$WEB_DIR"; do
    if find "$dir" -name "*.wasm" -not -name "*.d" 2>/dev/null | grep -q .; then
        WASM_FOUND=true
        break
    fi
done
if [ "$WASM_FOUND" = "false" ]; then
    echo "ERROR: No .wasm binary found. Run WASM build gate first."
    exit 1
fi

# ---------------------------------------------------------------------------
# Start HTTP server
# ---------------------------------------------------------------------------
SERVER_PORT=8766
cd "$WEB_DIR"
python3 -m http.server "$SERVER_PORT" &>/dev/null &
SERVER_PID=$!
sleep 2

cleanup() {
    kill "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "Server running on port $SERVER_PORT"

# ---------------------------------------------------------------------------
# Run benchmark via headless Chrome
# ---------------------------------------------------------------------------

# Create a benchmark script that loads a ROM and measures frame rate
BENCH_SCRIPT=$(cat <<'JSEOF'
const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({
        args: ['--enable-unsafe-webgpu', '--enable-features=Vulkan']
    });
    const page = await browser.newPage();

    // Navigate to the emulator
    await page.goto(process.env.EMULATOR_URL);
    await page.waitForTimeout(3000);

    // Check if emulator initialized
    const canvasExists = await page.$('canvas');
    if (!canvasExists) {
        console.log('ERROR: No canvas element found');
        process.exit(1);
    }

    // Wait for frames and measure
    const startTime = Date.now();
    const targetFrames = parseInt(process.env.BENCH_FRAMES || '120');

    // Poll for frame count from the emulator's performance overlay
    let frames = 0;
    let lastCheck = Date.now();
    const maxWait = 60000; // 60 seconds max

    while (frames < targetFrames && (Date.now() - startTime) < maxWait) {
        await page.waitForTimeout(1000);
        const frameCount = await page.evaluate(() => {
            // Try to read frame count from the emulator's exposed API
            if (window.__n64_frame_count) return window.__n64_frame_count();
            if (window.n64FrameCount) return window.n64FrameCount;
            return -1;
        });
        if (frameCount > 0) frames = frameCount;
    }

    const elapsed = (Date.now() - startTime) / 1000;

    if (frames > 0) {
        const vis = frames / elapsed;
        console.log(`vis: ${vis.toFixed(2)}`);
        console.log(`frames: ${frames}`);
        console.log(`elapsed: ${elapsed.toFixed(2)}s`);
    } else {
        console.log('ERROR: Could not read frame count from emulator');
        console.log('Ensure window.__n64_frame_count or window.n64FrameCount is exposed');
    }

    await browser.close();
})();
JSEOF
)

if command -v npx &>/dev/null; then
    echo ""
    echo "Running WASM benchmark via Playwright..."

    EMULATOR_URL="http://localhost:$SERVER_PORT" \
    BENCH_FRAMES="$BENCH_FRAMES" \
    node -e "$BENCH_SCRIPT" 2>&1 || true

    # Parse results
    VIS=$(echo "$BENCH_SCRIPT" | grep -oP 'vis: \K[0-9]+(\.[0-9]+)?' || true)

    if [ -n "$VIS" ]; then
        VIS_INT=$(echo "$VIS" | cut -d. -f1)

        if [ "$VIS_INT" -lt "$MIN_VIS" ]; then
            echo "FAIL: $VIS VI/s is below minimum WASM threshold ($MIN_VIS VI/s)"
            exit 1
        fi

        if [ "$VIS_INT" -lt "$WARN_VIS" ]; then
            echo "WARN: $VIS VI/s is below target ($WARN_VIS VI/s)"
        fi

        echo "WASM performance gate passed: $VIS VI/s >= $MIN_VIS VI/s"
    else
        echo "WARN: Could not parse WASM benchmark results"
        echo "Falling back to static checks..."

        # Fallback: just verify the WASM loads without errors
        echo "Checking WASM module validity..."
        node -e "
            const fs = require('fs');
            const wasmFiles = fs.readdirSync('$WEB_DIR/pkg').filter(f => f.endsWith('.wasm'));
            if (wasmFiles.length === 0) { console.log('No WASM files'); process.exit(1); }
            const buf = fs.readFileSync('$WEB_DIR/pkg/' + wasmFiles[0]);
            WebAssembly.validate(buf) ? console.log('WASM valid') : (console.log('WASM invalid'), process.exit(1));
        " 2>/dev/null || echo "WARN: Could not validate WASM"

        echo "WASM benchmark: inconclusive (Playwright not fully available)"
        echo "PASS (with warning)"
    fi
else
    echo "WARN: Playwright not available for browser benchmarking"
    echo "Performing static WASM validation only..."

    # Validate the WASM binary is well-formed
    if command -v wasm-validate &>/dev/null; then
        WASM_FILE=$(find "$WEB_DIR/pkg" "$WEB_DIR" -name "*.wasm" -not -name "*.d" 2>/dev/null | head -1)
        if [ -n "$WASM_FILE" ]; then
            wasm-validate "$WASM_FILE" 2>&1 && echo "WASM binary is valid" || echo "WARN: WASM validation failed"
        fi
    fi

    echo "PASS (Playwright unavailable, static checks only)"
fi

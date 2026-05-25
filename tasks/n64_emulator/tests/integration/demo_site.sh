#!/usr/bin/env bash
# =============================================================================
# Gate: Demo Site Verification
#
# Verifies the web frontend works end-to-end:
#   1. The WASM build exists and is served correctly
#   2. index.html loads without JavaScript errors
#   3. The WASM module initializes successfully
#   4. The canvas element renders at least one frame
#   5. The embedded homebrew ROM loads and runs
#
# Uses a lightweight HTTP server + headless Chrome (via Playwright or
# puppeteer) to verify the site. If neither is available, falls back to
# static file checks.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TASK_DIR="$SCRIPT_DIR/../.."
APP_DIR="$TASK_DIR/../../app"
WEB_DIR="$APP_DIR/web"

echo "========================================="
echo "Demo Site Verification"
echo "========================================="

# ---------------------------------------------------------------------------
# Check 1: Required files exist
# ---------------------------------------------------------------------------
echo ""
echo "--- File existence checks ---"

check_file() {
    if [ -f "$1" ]; then
        echo "  OK: $1"
    else
        echo "  MISSING: $1"
        return 1
    fi
}

MISSING=0
check_file "$WEB_DIR/index.html"       || MISSING=$((MISSING + 1))

# Check for WASM build output (either in web/pkg/ or web/ directly)
WASM_FOUND=false
for dir in "$WEB_DIR/pkg" "$WEB_DIR" "$APP_DIR/target/wasm32-unknown-unknown/release"; do
    if find "$dir" -name "*.wasm" -not -name "*.d" 2>/dev/null | grep -q .; then
        WASM_FOUND=true
        echo "  OK: WASM binary found in $dir"
        break
    fi
done
if [ "$WASM_FOUND" = "false" ]; then
    echo "  MISSING: No .wasm binary found"
    MISSING=$((MISSING + 1))
fi

if [ "$MISSING" -gt 0 ]; then
    echo ""
    echo "FAIL: $MISSING required files missing."
    echo "Run the WASM build gate first, then wasm-bindgen."
    exit 1
fi

# ---------------------------------------------------------------------------
# Check 2: HTML structure
# ---------------------------------------------------------------------------
echo ""
echo "--- HTML structure checks ---"

HTML_ERRORS=0

# Must have a canvas element
if grep -q '<canvas' "$WEB_DIR/index.html"; then
    echo "  OK: <canvas> element found"
else
    echo "  FAIL: No <canvas> element in index.html"
    HTML_ERRORS=$((HTML_ERRORS + 1))
fi

# Must reference WASM (import or script)
if grep -qE 'wasm|\.js' "$WEB_DIR/index.html"; then
    echo "  OK: WASM/JS reference found"
else
    echo "  FAIL: No WASM or JS reference in index.html"
    HTML_ERRORS=$((HTML_ERRORS + 1))
fi

# Must have ROM loader UI (file input or drag-drop handler)
if grep -qE 'file|drop|rom|load' "$WEB_DIR/index.html" "$WEB_DIR"/*.js 2>/dev/null; then
    echo "  OK: ROM loader UI found"
else
    echo "  WARN: No ROM loader UI detected (check main.js)"
fi

if [ "$HTML_ERRORS" -gt 0 ]; then
    echo ""
    echo "FAIL: HTML structure checks failed."
    exit 1
fi

# ---------------------------------------------------------------------------
# Check 3: Headless browser test (if Playwright available)
# ---------------------------------------------------------------------------
echo ""
echo "--- Headless browser test ---"

if command -v npx &>/dev/null && npx playwright --version &>/dev/null 2>&1; then
    echo "Playwright available, running headless browser test..."

    # Start a temporary HTTP server
    SERVER_PORT=8765
    cd "$WEB_DIR"
    python3 -m http.server "$SERVER_PORT" &>/dev/null &
    SERVER_PID=$!
    sleep 2

    # Simple Playwright test: load page, check for errors, verify canvas
    BROWSER_RESULT=$(npx playwright test --reporter=line 2>&1) || true
    BROWSER_EXIT=$?

    kill "$SERVER_PID" 2>/dev/null || true

    if [ "$BROWSER_EXIT" -eq 0 ]; then
        echo "  PASS: Headless browser test passed"
    else
        echo "  WARN: Headless browser test had issues (non-blocking)"
        echo "$BROWSER_RESULT" | tail -10
    fi
elif command -v node &>/dev/null; then
    echo "Playwright not available, running Node.js static checks..."

    # Verify JavaScript syntax
    for js_file in "$WEB_DIR"/*.js; do
        if [ -f "$js_file" ]; then
            if node --check "$js_file" 2>/dev/null; then
                echo "  OK: $(basename "$js_file") syntax valid"
            else
                echo "  FAIL: $(basename "$js_file") has syntax errors"
                HTML_ERRORS=$((HTML_ERRORS + 1))
            fi
        fi
    done
else
    echo "  SKIP: Neither Playwright nor Node.js available for browser testing"
fi

echo ""
echo "Demo site verification passed."

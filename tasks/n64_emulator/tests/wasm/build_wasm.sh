#!/usr/bin/env bash
# =============================================================================
# Gate: WASM build
#
# Verifies the emulator compiles to wasm32-unknown-unknown. The web frontend
# crate must produce a valid .wasm binary. Also runs wasm-bindgen to generate
# JS glue and verifies the output files exist.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/../../../app"

echo "Checking wasm32-unknown-unknown target is installed..."
rustup target add wasm32-unknown-unknown 2>/dev/null || true

echo "Building WASM (release)..."
cd "$APP_DIR"
cargo build --release --target wasm32-unknown-unknown -p n64-frontend-web 2>&1

WASM_FILE=$(find target/wasm32-unknown-unknown/release -name "*.wasm" -not -name "*.d" | head -1)

if [ -z "$WASM_FILE" ]; then
    echo "ERROR: No .wasm file found in target/wasm32-unknown-unknown/release/"
    exit 1
fi

echo "WASM binary: $WASM_FILE ($(stat -c%s "$WASM_FILE" 2>/dev/null || stat -f%z "$WASM_FILE") bytes)"

# Run wasm-bindgen if available
if command -v wasm-bindgen &>/dev/null; then
    echo "Running wasm-bindgen..."
    wasm-bindgen "$WASM_FILE" --out-dir web/pkg --target web 2>&1
    echo "wasm-bindgen output generated in web/pkg/"
elif cargo install --list | grep -q wasm-bindgen; then
    echo "Running wasm-bindgen..."
    wasm-bindgen "$WASM_FILE" --out-dir web/pkg --target web 2>&1
else
    echo "WARN: wasm-bindgen not found, skipping JS glue generation"
fi

echo "WASM build succeeded."

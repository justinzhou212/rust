#!/usr/bin/env bash
# =============================================================================
# Gate: Native Rust build
#
# Verifies the emulator compiles on the host with zero warnings.
# Treats warnings as errors to enforce code quality.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/../../../app"

echo "Building native (release)..."
cd "$APP_DIR"

# Build all crates in the workspace
RUSTFLAGS="-D warnings" cargo build --release 2>&1

echo "Native build succeeded with zero warnings."

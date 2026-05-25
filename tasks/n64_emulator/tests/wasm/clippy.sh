#!/usr/bin/env bash
# =============================================================================
# Gate: Clippy lint
#
# Runs clippy with deny-warnings on all crates. Ensures idiomatic Rust and
# catches common mistakes.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$SCRIPT_DIR/../../../app"

cd "$APP_DIR"
echo "Running clippy..."
cargo clippy --all-targets --all-features -- -D warnings 2>&1

echo "Clippy passed with zero warnings."

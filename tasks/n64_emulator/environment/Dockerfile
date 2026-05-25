# =============================================================================
# N64 Emulator Challenge — Build & Test Environment
#
# This Dockerfile creates a reproducible environment with all tools needed
# to build and test the N64 emulator.
#
# Usage:
#   docker build -t n64-emulator-test -f environment/Dockerfile .
#   docker run --rm -v $(pwd)/../../app:/app n64-emulator-test ./test.sh
# =============================================================================
FROM rust:1.82-bookworm

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    pkg-config \
    python3 \
    python3-pip \
    bc \
    curl \
    git \
    # For wasm-opt
    binaryen \
    # For headless browser testing
    chromium \
    # Node.js for Playwright
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Rust targets and tools
RUN rustup target add wasm32-unknown-unknown && \
    cargo install wasm-bindgen-cli wasm-pack

# Playwright for browser testing
RUN npm install -g playwright && \
    npx playwright install --with-deps chromium || true

# nust64 for building n64-systemtest
RUN cargo install nust64 || true

WORKDIR /workspace

# Copy task files (tests, scripts, etc.)
COPY . /workspace/tasks/n64_emulator/

# The /app directory is expected to be mounted as a volume
# containing the agent's Rust workspace

ENTRYPOINT ["bash"]

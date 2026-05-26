# repro-docker-bench

A Terminal-Bench Challenge for building bit-for-bit reproducible Docker/OCI images.

## Quick Start

```bash
# Generate fixtures and run benchmark
./test.sh

# With custom seed
REPRO_BENCH_SEED=20260526 ./test.sh

# Specify submission
./test.sh --submission ./submissions/repro-docker
```

## The Challenge

Build a tool (`repro-docker`) that:

1. Takes a Docker build context + Dockerfile
2. Produces a bit-for-bit reproducible OCI image layout
3. Works across different build environments (paths, hostnames, timezones, etc.)
4. Diagnoses unreproducible inputs with machine-readable JSON

See [instruction.md](./instruction.md) for the full specification.

## Fixture Families

| # | Family | What It Tests |
|---|--------|---------------|
| 1 | Complex file tree | Layer ordering, mtimes, symlinks, .dockerignore |
| 2 | Go multi-stage | Compiler build paths, build IDs |
| 3 | Python pip/pyc | Wheel metadata, .pyc timestamps, generated assets |
| 4 | Node npm | Lockfile fidelity, node_modules layout |
| 5 | Debian apt | Package manager caches, dpkg state |
| 6 | Internal archive | Application-generated tar.gz determinism |
| 7 | Mixed multi-stage | Node + Rust + Debian integrated app |
| 8 | Pinned network | Content-addressed downloads |
| 9 | Diagnosis | Detecting unreproducible inputs |

## Scoring

**All-or-nothing.** All 9 fixture families must pass. No partial credit.

## Submission

Place your solution at `submissions/repro-docker/repro-docker` (executable).

Interface:
```bash
repro-docker build \
  --context <context-dir> \
  --dockerfile <dockerfile-path> \
  --output <oci-layout-dir> \
  --source-date-epoch <unix-seconds>
```

For unreproducible inputs, exit with code `78` and write diagnosis JSON to stdout.

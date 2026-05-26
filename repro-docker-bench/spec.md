# Reproducible Docker Benchmark — Technical Specification

## Overview

This benchmark evaluates a tool's ability to produce **bit-for-bit reproducible OCI images** from Docker build contexts across different build environments. The core invariant:

```
Same logical source + different build environment → identical image digest
Changed logical source → different image digest + changed runtime behavior
Unsafe unreproducible input → explicit machine-readable diagnosis
```

## Architecture

```
repro-docker-bench/
├── runner/           # Benchmark harness
├── fixturegen/       # Fixture generators (9 families)
├── local-services/   # Deterministic package mirrors
├── base-images/      # Pinned image digests
├── schemas/          # JSON schemas for validation
├── submissions/      # Solution goes here
├── instruction.md    # Task specification
├── spec.md           # This file
├── test.sh           # Entry point
└── task.toml         # Benchmark metadata
```

## Execution Flow

1. **Generate fixtures** from a seed (deterministic but varied per run)
2. **For each fixture**, run the submission tool in 3 isolated environments (A, B, C)
3. **Validate** OCI output, digest equality (A==B), mutation detection (C≠A), runtime behavior
4. **For diagnosis fixtures**, validate JSON output against expected causes

## Build Environment Isolation

Each build gets a unique combination of:
- Source path (different absolute paths)
- Hostname
- Timezone
- Locale
- Umask
- HOME directory
- TMPDIR
- File modification times (randomized per environment)
- File creation order (shuffled per environment)

## Network Isolation

Builds have no external network access. Only local deterministic services are available:
- `apt.local` — Debian package mirror
- `pypi.local` — Python package mirror
- `npm.local` — npm package registry
- `payload.local` — HTTP payload server

## Fixture Families

| # | Family | Tests |
|---|--------|-------|
| 1 | file_tree | OCI layer determinism, COPY, .dockerignore, symlinks |
| 2 | go_multistage | Compiler path embedding, build IDs |
| 3 | python_pip_pyc | pip installs, .pyc files, generated assets |
| 4 | node_npm | npm lockfile, node_modules, build output |
| 5 | debian_apt | OS package manager caches, dpkg state |
| 6 | internal_archive | Application-generated tar/gzip files |
| 7 | mixed_multistage | Multi-language multi-stage real app |
| 8 | pinned_network | Content-addressed network downloads |
| 9 | diagnosis | Unreproducible input detection + safe cousin |

## Validation Steps

For reproducible fixtures (1-8):
1. OCI layout validity
2. Digest equality (A vs B)
3. Unpacked rootfs equality
4. Runtime smoke tests (A, B, C all pass)
5. Mutation check (C ≠ A, C runtime correct)

For diagnosis fixture (9):
1. Unsafe variant: exit code 78, valid JSON diagnosis, correct cause set
2. Safe cousin: reproducible A/B/C build passes

## Pass Condition

**All-or-nothing.** Every fixture must pass. No partial credit.

## Anti-Gaming Properties

- **Fixed-output cheating**: Caught by mutation C (different source → different image)
- **Cache reuse**: Isolated builds with no shared state
- **File deletion**: Runtime smoke tests require specific artifacts
- **Ignore Dockerfile**: Generated behavior depends on source + Dockerfile
- **Hardcoded names**: Fixture instances generated fresh per seed
- **Always-fail diagnosis**: Safe cousin must build reproducibly
- **Metadata-only normalization**: Internal archives, compiled binaries, pyc files
- **External network oracle**: Network guard blocks all external requests
- **Reading expected answers**: Sandbox prevents access to harness data

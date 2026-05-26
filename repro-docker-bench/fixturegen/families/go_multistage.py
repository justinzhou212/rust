"""
Fixture family 2: Go multi-stage build with path/build-ID traps.
Tests compiler/toolchain nondeterminism. Intentionally omits -trimpath
and -ldflags="-buildid=" to test the tool's ability to normalize Go binaries.
"""

import os
import shutil

from common import FixtureContext, write_file


# Pinned Go image digest
GOLANG_DIGEST = (
    "sha256:4746d26432a9117a5f58e95cb9f954ddf0de128e9d5816886514199316e4a2fb"
)


def generate(ctx: FixtureContext):
    """Generate a Go multi-stage build fixture."""
    context_dir = ctx.make_context_dir()

    # Generate unique constants for this fixture
    app_name = f"app-{ctx.random_string(6)}"
    magic_constant = ctx.random_hex(32)
    hash_salt = ctx.random_string(16)
    version_string = f"v1.{ctx.random_int(0, 99)}.{ctx.random_int(0, 99)}"

    # Create Go module
    module_name = f"example.com/{app_name}"

    write_file(
        os.path.join(context_dir, "go.mod"),
        f"""module {module_name}

go 1.21
""",
    )

    write_file(os.path.join(context_dir, "go.sum"), "")

    # Main application
    os.makedirs(os.path.join(context_dir, "cmd", "app"), exist_ok=True)
    os.makedirs(os.path.join(context_dir, "internal", "compute"), exist_ok=True)

    write_file(
        os.path.join(context_dir, "cmd", "app", "main.go"),
        f"""package main

import (
\t"crypto/sha256"
\t"encoding/hex"
\t"fmt"
\t"os"

\t"{module_name}/internal/compute"
)

const Version = "{version_string}"
const MagicConstant = "{magic_constant}"

func main() {{
\tif len(os.Args) > 1 && os.Args[1] == "--check" {{
\t\tif len(os.Args) < 3 {{
\t\t\tfmt.Fprintf(os.Stderr, "Usage: %s --check <input>\\n", os.Args[0])
\t\t\tos.Exit(1)
\t\t}}
\t\tinput := os.Args[2]
\t\tresult := compute.Hash(input, MagicConstant)
\t\tfmt.Println(result)
\t\tos.Exit(0)
\t}}

\tif len(os.Args) > 1 && os.Args[1] == "--version" {{
\t\tfmt.Println(Version)
\t\tos.Exit(0)
\t}}

\t// Default: self-test
\texpected := compute.Hash("self-test", MagicConstant)
\th := sha256.New()
\th.Write([]byte("self-test"))
\th.Write([]byte(MagicConstant))
\tgot := hex.EncodeToString(h.Sum(nil))
\tif got != expected {{
\t\tfmt.Fprintf(os.Stderr, "self-test failed: got %s, expected %s\\n", got, expected)
\t\tos.Exit(1)
\t}}
\tfmt.Println("PASS: go app self-test")
}}
""",
    )

    write_file(
        os.path.join(context_dir, "internal", "compute", "hash.go"),
        f"""package compute

import (
\t"crypto/sha256"
\t"encoding/hex"
)

const Salt = "{hash_salt}"

// Hash computes a deterministic hash of input combined with a secret and salt.
func Hash(input, secret string) string {{
\th := sha256.New()
\th.Write([]byte(input))
\th.Write([]byte(secret))
\treturn hex.EncodeToString(h.Sum(nil))
}}

// HashWithSalt includes the package-level salt.
func HashWithSalt(input, secret string) string {{
\th := sha256.New()
\th.Write([]byte(input))
\th.Write([]byte(secret))
\th.Write([]byte(Salt))
\treturn hex.EncodeToString(h.Sum(nil))
}}
""",
    )

    # Dockerfile - intentionally omits -trimpath and -buildid flags
    write_file(
        os.path.join(context_dir, "Dockerfile"),
        f"""FROM golang@{GOLANG_DIGEST} AS build
WORKDIR /src
COPY go.mod go.sum ./
COPY cmd cmd
COPY internal internal
RUN go build -o /out/app ./cmd/app

FROM scratch
COPY --from=build /out/app /app
ENTRYPOINT ["/app"]
""",
    )

    # Generate test input and expected output
    test_input = ctx.random_string(20)
    import hashlib

    h = hashlib.sha256()
    h.update(test_input.encode())
    h.update(magic_constant.encode())
    expected_hash = h.hexdigest()

    # Create mutated context
    mutated_dir = ctx.make_mutated_context_dir()
    shutil.copytree(context_dir, mutated_dir, dirs_exist_ok=True)

    # Mutate: change the magic constant
    mutated_constant = ctx.random_hex(32)
    mutated_main = os.path.join(mutated_dir, "cmd", "app", "main.go")
    with open(mutated_main) as f:
        content = f.read()
    content = content.replace(magic_constant, mutated_constant)
    with open(mutated_main, "w") as f:
        f.write(content)

    # Compute mutated expected output
    h2 = hashlib.sha256()
    h2.update(test_input.encode())
    h2.update(mutated_constant.encode())
    mutated_expected_hash = h2.hexdigest()

    # Write metadata
    ctx.write_metadata(
        {
            "type": "reproducible",
            "family": "go_multistage",
            "test_input": test_input,
            "expected_output": expected_hash,
            "expected_output_mutated": mutated_expected_hash,
            "app_name": app_name,
            "required_rootfs_paths": ["/app"],
        }
    )

    # Write smoke test
    ctx.write_smoke_test(f"""#!/bin/bash
set -e
IMAGE="$1"
TEST_INPUT="{test_input}"

if [ -n "$ROOTFS_DIR" ]; then
    test -f "$ROOTFS_DIR/app" || {{ echo "FAIL: /app binary missing from rootfs"; exit 1; }}
    test -x "$ROOTFS_DIR/app" || {{ echo "FAIL: /app not executable"; exit 1; }}
    OUTPUT=$("$ROOTFS_DIR/app" --check "$TEST_INPUT")
    echo "$OUTPUT"
    exit 0
fi

if [ -n "$IMAGE" ] && command -v docker >/dev/null 2>&1; then
    OUTPUT=$(docker run --rm "$IMAGE" --check "$TEST_INPUT")
    echo "$OUTPUT"
    exit 0
fi

echo "FAIL: no container runtime or rootfs available"
exit 1
""")

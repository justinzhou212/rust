"""
Fixture family 5: Debian apt install from local snapshot mirror.
Tests OS package manager determinism.
"""

import os
import shutil

from common import FixtureContext, write_file


# Pinned Debian image digest
DEBIAN_DIGEST = (
    "sha256:0104b334637a5f19aa9c983a91b54c89887c0984081f2068983107a6f6c21eeb"
)


def generate(ctx: FixtureContext):
    """Generate a Debian apt fixture."""
    context_dir = ctx.make_context_dir()

    # Generate check script content
    check_token = ctx.random_hex(16)
    packages = ["ca-certificates", "curl", "file"]

    # Create check.sh
    check_script = f"""#!/bin/bash
set -e

echo "Checking installed packages..."

# Verify packages are installed
for pkg in {" ".join(packages)}; do
    if ! dpkg -l "$pkg" >/dev/null 2>&1; then
        echo "FAIL: package $pkg not installed"
        exit 1
    fi
done

# Verify binaries work
curl --version >/dev/null 2>&1 || {{ echo "FAIL: curl not working"; exit 1; }}
file --version >/dev/null 2>&1 || {{ echo "FAIL: file not working"; exit 1; }}

# Deterministic output check
TOKEN="{check_token}"
HASH=$(echo -n "$TOKEN" | sha256sum | cut -d' ' -f1)
echo "token_hash=$HASH"

# Check dpkg database consistency
dpkg --audit 2>/dev/null || true

echo "PASS: debian apt verified"
"""
    write_file(os.path.join(context_dir, "check.sh"), check_script, executable=True)

    # Dockerfile
    write_file(
        os.path.join(context_dir, "Dockerfile"),
        f"""FROM debian@{DEBIAN_DIGEST}
RUN apt-get update && apt-get install -y --no-install-recommends \\
    {" ".join(packages)} \\
    && rm -rf /var/lib/apt/lists/*
COPY check.sh /check.sh
CMD ["bash", "/check.sh"]
""",
    )

    # Create mutated context
    mutated_dir = ctx.make_mutated_context_dir()
    shutil.copytree(context_dir, mutated_dir, dirs_exist_ok=True)

    # Mutate: change check token and add an additional package
    mutated_token = ctx.random_hex(16)
    mutated_check = f"""#!/bin/bash
set -e

echo "Checking installed packages..."

# Verify packages are installed
for pkg in {" ".join(packages)} jq; do
    if ! dpkg -l "$pkg" >/dev/null 2>&1; then
        echo "FAIL: package $pkg not installed"
        exit 1
    fi
done

# Verify binaries work
curl --version >/dev/null 2>&1 || {{ echo "FAIL: curl not working"; exit 1; }}
file --version >/dev/null 2>&1 || {{ echo "FAIL: file not working"; exit 1; }}
jq --version >/dev/null 2>&1 || {{ echo "FAIL: jq not working"; exit 1; }}

# Deterministic output check
TOKEN="{mutated_token}"
HASH=$(echo -n "$TOKEN" | sha256sum | cut -d' ' -f1)
echo "token_hash=$HASH"

echo "PASS: debian apt verified"
"""
    write_file(os.path.join(mutated_dir, "check.sh"), mutated_check, executable=True)

    # Mutated Dockerfile adds jq
    write_file(
        os.path.join(mutated_dir, "Dockerfile"),
        f"""FROM debian@{DEBIAN_DIGEST}
RUN apt-get update && apt-get install -y --no-install-recommends \\
    {" ".join(packages)} jq \\
    && rm -rf /var/lib/apt/lists/*
COPY check.sh /check.sh
CMD ["bash", "/check.sh"]
""",
    )

    ctx.write_metadata(
        {
            "type": "reproducible",
            "family": "debian_apt",
            "expected_output": "PASS: debian apt verified",
            "expected_output_mutated": "PASS: debian apt verified",
            "packages": packages,
            "required_rootfs_paths": [
                "/check.sh",
                "/usr/bin/curl",
                "/usr/bin/file",
            ],
        }
    )

    ctx.write_smoke_test("""#!/bin/bash
set -e
IMAGE="$1"

if [ -n "$ROOTFS_DIR" ]; then
    test -f "$ROOTFS_DIR/check.sh" || { echo "FAIL: /check.sh missing"; exit 1; }
    test -f "$ROOTFS_DIR/usr/bin/curl" || { echo "FAIL: curl not installed"; exit 1; }
    test -f "$ROOTFS_DIR/usr/bin/file" || { echo "FAIL: file not installed"; exit 1; }
    echo "PASS: debian apt verified"
    exit 0
fi

if [ -n "$IMAGE" ] && command -v docker >/dev/null 2>&1; then
    OUTPUT=$(docker run --rm "$IMAGE")
    echo "$OUTPUT"
    echo "$OUTPUT" | grep -q "PASS" || { echo "FAIL: container output missing PASS"; exit 1; }
    exit 0
fi

echo "FAIL: no container runtime or rootfs available"
exit 1
""")

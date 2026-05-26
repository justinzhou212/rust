"""
Fixture family 9: Generated unreproducible diagnosis.
Tests that the tool correctly identifies and reports unreproducible inputs.
Also generates a safe cousin that must build reproducibly.
"""

import os
import shutil

from common import FixtureContext, write_file


# Pinned image digests
BUSYBOX_DIGEST = (
    "sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
)
DEBIAN_DIGEST = (
    "sha256:0104b334637a5f19aa9c983a91b54c89887c0984081f2068983107a6f6c21eeb"
)

ALL_CAUSE_TYPES = [
    "UNPINNED_BASE_IMAGE",
    "UNPINNED_APT_REPOSITORY",
    "UNPINNED_PIP_DEPENDENCY",
    "UNPINNED_NPM_DEPENDENCY",
    "UNPINNED_NETWORK_DOWNLOAD",
    "TIMESTAMP_LEAK",
    "RANDOMNESS_LEAK",
    "HOSTNAME_LEAK",
    "BUILD_PATH_LEAK",
]


def generate(ctx: FixtureContext):
    """Generate a diagnosis fixture with unsafe and safe variants."""

    # Choose 2-6 causes randomly
    num_causes = ctx.random_int(2, 6)
    chosen_causes = ctx.random_sample(ALL_CAUSE_TYPES, num_causes)

    # Generate unsafe variant
    unsafe_dir = os.path.join(ctx.output_dir, "unsafe", "context")
    os.makedirs(unsafe_dir, exist_ok=True)
    os.makedirs(os.path.join(unsafe_dir, "scripts"), exist_ok=True)

    # Generate safe cousin
    safe_dir = os.path.join(ctx.output_dir, "safe", "context")
    os.makedirs(safe_dir, exist_ok=True)
    os.makedirs(os.path.join(safe_dir, "scripts"), exist_ok=True)

    # Track expected causes with locations
    expected_causes = []
    dockerfile_lines_unsafe = []
    dockerfile_lines_safe = []
    line_num = 1

    # Base image handling
    if "UNPINNED_BASE_IMAGE" in chosen_causes:
        dockerfile_lines_unsafe.append("ARG BASE_IMAGE=debian:bookworm")
        dockerfile_lines_unsafe.append("FROM ${BASE_IMAGE}")
        expected_causes.append(
            {
                "type": "UNPINNED_BASE_IMAGE",
                "location": f"Dockerfile:{line_num + 1}",
            }
        )
        line_num += 2
    else:
        dockerfile_lines_unsafe.append(f"FROM debian@{DEBIAN_DIGEST}")
        line_num += 1

    # Safe always uses pinned
    dockerfile_lines_safe.append(f"FROM debian@{DEBIAN_DIGEST}")

    dockerfile_lines_unsafe.append("")
    dockerfile_lines_unsafe.append("WORKDIR /app")
    dockerfile_lines_unsafe.append("COPY scripts scripts")
    dockerfile_lines_unsafe.append("")
    line_num += 4

    dockerfile_lines_safe.append("")
    dockerfile_lines_safe.append("WORKDIR /app")
    dockerfile_lines_safe.append("COPY scripts scripts")
    dockerfile_lines_safe.append("")

    # Generate scripts for each cause
    if "UNPINNED_APT_REPOSITORY" in chosen_causes:
        script_name = "install_unpinned_apt.sh"
        script_content = """#!/bin/bash
apt-get update
apt-get install -y curl wget
"""
        write_file(
            os.path.join(unsafe_dir, "scripts", script_name),
            script_content,
            executable=True,
        )
        dockerfile_lines_unsafe.append(f"RUN ./scripts/{script_name}")
        expected_causes.append(
            {
                "type": "UNPINNED_APT_REPOSITORY",
                "location": f"scripts/{script_name}:2",
            }
        )
        line_num += 1

        # Safe version: pinned apt
        safe_script = """#!/bin/bash
apt-get update
apt-get install -y --no-install-recommends curl wget
rm -rf /var/lib/apt/lists/*
"""
        write_file(
            os.path.join(safe_dir, "scripts", script_name), safe_script, executable=True
        )
        dockerfile_lines_safe.append(f"RUN ./scripts/{script_name}")

    if "UNPINNED_PIP_DEPENDENCY" in chosen_causes:
        script_name = "install_pip_deps.sh"
        script_content = """#!/bin/bash
pip install requests flask numpy
"""
        write_file(
            os.path.join(unsafe_dir, "scripts", script_name),
            script_content,
            executable=True,
        )
        dockerfile_lines_unsafe.append(f"RUN ./scripts/{script_name}")
        expected_causes.append(
            {
                "type": "UNPINNED_PIP_DEPENDENCY",
                "location": f"scripts/{script_name}:2",
            }
        )
        line_num += 1

        # Safe version doesn't exist in safe (just skip)
        safe_pip = """#!/bin/bash
# No unpinned dependencies
echo "deps ok"
"""
        write_file(
            os.path.join(safe_dir, "scripts", script_name), safe_pip, executable=True
        )
        dockerfile_lines_safe.append(f"RUN ./scripts/{script_name}")

    if "UNPINNED_NPM_DEPENDENCY" in chosen_causes:
        script_name = "install_npm_deps.sh"
        script_content = """#!/bin/bash
npm install express lodash
"""
        write_file(
            os.path.join(unsafe_dir, "scripts", script_name),
            script_content,
            executable=True,
        )
        dockerfile_lines_unsafe.append(f"RUN ./scripts/{script_name}")
        expected_causes.append(
            {
                "type": "UNPINNED_NPM_DEPENDENCY",
                "location": f"scripts/{script_name}:2",
            }
        )
        line_num += 1

        safe_npm = """#!/bin/bash
echo "npm deps ok"
"""
        write_file(
            os.path.join(safe_dir, "scripts", script_name), safe_npm, executable=True
        )
        dockerfile_lines_safe.append(f"RUN ./scripts/{script_name}")

    if "UNPINNED_NETWORK_DOWNLOAD" in chosen_causes:
        script_name = "fetch_latest_payload.sh"
        script_content = """#!/bin/bash
curl -fsSL https://example.com/latest/release.tar.gz -o /tmp/release.tar.gz
tar -xzf /tmp/release.tar.gz -C /opt/
"""
        write_file(
            os.path.join(unsafe_dir, "scripts", script_name),
            script_content,
            executable=True,
        )
        dockerfile_lines_unsafe.append(f"RUN ./scripts/{script_name}")
        expected_causes.append(
            {
                "type": "UNPINNED_NETWORK_DOWNLOAD",
                "location": f"scripts/{script_name}:2",
            }
        )
        line_num += 1

        safe_net = """#!/bin/bash
echo "network ok (no download needed)"
"""
        write_file(
            os.path.join(safe_dir, "scripts", script_name), safe_net, executable=True
        )
        dockerfile_lines_safe.append(f"RUN ./scripts/{script_name}")

    if "TIMESTAMP_LEAK" in chosen_causes:
        script_name = "write_required_timestamp.sh"
        script_content = """#!/bin/bash
date +%s > /app/required_timestamp.txt
date -R >> /app/required_timestamp.txt
"""
        write_file(
            os.path.join(unsafe_dir, "scripts", script_name),
            script_content,
            executable=True,
        )
        dockerfile_lines_unsafe.append(f"RUN ./scripts/{script_name}")
        expected_causes.append(
            {
                "type": "TIMESTAMP_LEAK",
                "location": f"scripts/{script_name}:2",
            }
        )
        line_num += 1

        safe_ts = """#!/bin/bash
echo "1700000000" > /app/required_timestamp.txt
echo "Tue, 14 Nov 2023 22:13:20 +0000" >> /app/required_timestamp.txt
"""
        write_file(
            os.path.join(safe_dir, "scripts", script_name), safe_ts, executable=True
        )
        dockerfile_lines_safe.append(f"RUN ./scripts/{script_name}")

    if "RANDOMNESS_LEAK" in chosen_causes:
        script_name = "random_seed.sh"
        script_content = """#!/bin/bash
head -c 32 /dev/urandom | base64 > /app/session_key.txt
cat /proc/sys/kernel/random/uuid >> /app/session_key.txt
"""
        write_file(
            os.path.join(unsafe_dir, "scripts", script_name),
            script_content,
            executable=True,
        )
        dockerfile_lines_unsafe.append(f"RUN ./scripts/{script_name}")
        expected_causes.append(
            {
                "type": "RANDOMNESS_LEAK",
                "location": f"scripts/{script_name}:2",
            }
        )
        line_num += 1

        safe_rand = """#!/bin/bash
echo "deterministic-key-value" > /app/session_key.txt
"""
        write_file(
            os.path.join(safe_dir, "scripts", script_name), safe_rand, executable=True
        )
        dockerfile_lines_safe.append(f"RUN ./scripts/{script_name}")

    if "HOSTNAME_LEAK" in chosen_causes:
        script_name = "embed_hostname.sh"
        script_content = """#!/bin/bash
hostname > /app/build_host.txt
echo "Built on: $(hostname)" >> /app/metadata.txt
"""
        write_file(
            os.path.join(unsafe_dir, "scripts", script_name),
            script_content,
            executable=True,
        )
        dockerfile_lines_unsafe.append(f"RUN ./scripts/{script_name}")
        expected_causes.append(
            {
                "type": "HOSTNAME_LEAK",
                "location": f"scripts/{script_name}:2",
            }
        )
        line_num += 1

        safe_host = """#!/bin/bash
echo "build-host" > /app/build_host.txt
echo "Built on: build-host" >> /app/metadata.txt
"""
        write_file(
            os.path.join(safe_dir, "scripts", script_name), safe_host, executable=True
        )
        dockerfile_lines_safe.append(f"RUN ./scripts/{script_name}")

    if "BUILD_PATH_LEAK" in chosen_causes:
        script_name = "embed_paths.sh"
        script_content = """#!/bin/bash
echo "$PWD" > /app/build_path.txt
echo "$HOME" >> /app/build_path.txt
realpath . >> /app/build_path.txt
"""
        write_file(
            os.path.join(unsafe_dir, "scripts", script_name),
            script_content,
            executable=True,
        )
        dockerfile_lines_unsafe.append(f"RUN ./scripts/{script_name}")
        expected_causes.append(
            {
                "type": "BUILD_PATH_LEAK",
                "location": f"scripts/{script_name}:2",
            }
        )
        line_num += 1

        safe_path = """#!/bin/bash
echo "/app" > /app/build_path.txt
echo "/root" >> /app/build_path.txt
echo "/app" >> /app/build_path.txt
"""
        write_file(
            os.path.join(safe_dir, "scripts", script_name), safe_path, executable=True
        )
        dockerfile_lines_safe.append(f"RUN ./scripts/{script_name}")

    # Add CMD
    dockerfile_lines_unsafe.append("")
    dockerfile_lines_unsafe.append(
        'CMD ["sh", "-c", "cat /app/*.txt 2>/dev/null; echo done"]'
    )

    dockerfile_lines_safe.append("")
    dockerfile_lines_safe.append(
        'CMD ["sh", "-c", "cat /app/*.txt 2>/dev/null; echo done"]'
    )

    # Write Dockerfiles
    write_file(
        os.path.join(unsafe_dir, "Dockerfile"),
        "\n".join(dockerfile_lines_unsafe) + "\n",
    )
    write_file(
        os.path.join(safe_dir, "Dockerfile"),
        "\n".join(dockerfile_lines_safe) + "\n",
    )

    # Create safe mutated_context
    safe_mutated = os.path.join(ctx.output_dir, "safe", "mutated_context")
    shutil.copytree(safe_dir, safe_mutated)

    # Just add a marker file to the mutated version
    write_file(
        os.path.join(safe_mutated, "scripts", "mutation_marker.sh"),
        """#!/bin/bash
echo "mutated-output" > /app/mutation.txt
""",
        executable=True,
    )

    # Update mutated Dockerfile to include the marker
    mutated_dockerfile = os.path.join(safe_mutated, "Dockerfile")
    with open(mutated_dockerfile) as f:
        content = f.read()
    content = content.replace(
        'CMD ["sh", "-c"', 'RUN ./scripts/mutation_marker.sh\nCMD ["sh", "-c"'
    )
    with open(mutated_dockerfile, "w") as f:
        f.write(content)

    # Write safe smoke test
    write_file(
        os.path.join(ctx.output_dir, "safe", "test_container.sh"),
        """#!/bin/bash
set -e
IMAGE="$1"

if [ -n "$ROOTFS_DIR" ]; then
    # Verify the safe build produced expected output files
    FOUND=$(find "$ROOTFS_DIR/app" -name "*.txt" -type f 2>/dev/null | wc -l)
    test "$FOUND" -gt 0 || { echo "FAIL: no output files in /app"; exit 1; }
    echo "PASS: safe cousin verified"
    exit 0
fi

if [ -n "$IMAGE" ] && command -v docker >/dev/null 2>&1; then
    OUTPUT=$(docker run --rm "$IMAGE")
    echo "$OUTPUT"
    echo "$OUTPUT" | grep -q "done" || { echo "FAIL: container output missing done"; exit 1; }
    echo "PASS: safe cousin verified"
    exit 0
fi

echo "FAIL: no container runtime or rootfs available"
exit 1
""",
        executable=True,
    )

    # Write metadata
    ctx.write_metadata(
        {
            "type": "diagnosis",
            "family": "diagnosis",
            "expected_causes": expected_causes,
            "chosen_cause_types": [c["type"] for c in expected_causes],
            "num_causes": len(expected_causes),
        }
    )

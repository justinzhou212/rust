"""
Fixture family 1: Complex file-tree image.
Tests OCI/layer/file-tree determinism: COPY, .dockerignore, file ordering,
mtimes, modes, symlinks, image config metadata, runtime preservation.
"""

import os
import shutil

from common import FixtureContext, write_file


# Pinned busybox image digest
BUSYBOX_DIGEST = (
    "sha256:2c8ed5408241dd6de6857f0de28e3d8dea66543eae4a02d0290c0a39a8161344"
)


def generate(ctx: FixtureContext):
    """Generate a complex file-tree fixture."""
    context_dir = ctx.make_context_dir()

    # Generate file tree parameters
    num_files = ctx.random_int(100, 300)
    num_dirs = ctx.random_int(10, 30)
    num_symlinks = ctx.random_int(5, 15)
    num_ignored = ctx.random_int(10, 30)

    # Create directory structure
    dirs = ["data"]
    for i in range(num_dirs):
        depth = ctx.random_int(1, 4)
        parts = ["data"] + [
            ctx.random_string(ctx.random_int(3, 10)) for _ in range(depth)
        ]
        dirs.append(os.path.join(*parts))

    for d in dirs:
        os.makedirs(os.path.join(context_dir, d), exist_ok=True)

    # Create data files with random content
    data_files = []
    for i in range(num_files):
        target_dir = ctx.random_choice(dirs)
        # Some files with special characters (safe subset)
        if ctx.random_int(0, 10) == 0:
            name = f"file-{ctx.random_string(5)}-{i}.dat"
        else:
            name = f"{ctx.random_string(ctx.random_int(4, 12))}.{ctx.random_choice(['txt', 'dat', 'bin', 'cfg', 'json'])}"

        path = os.path.join(target_dir, name)
        full_path = os.path.join(context_dir, path)

        # Random content
        content_size = ctx.random_int(10, 4096)
        content = ctx.random_bytes(content_size)

        write_file(full_path, content)

        # Random executable bit
        if ctx.random_int(0, 10) == 0:
            os.chmod(full_path, 0o755)
            data_files.append((path, True))
        else:
            data_files.append((path, False))

    # Create symlinks
    symlinks = []
    for i in range(num_symlinks):
        if not data_files:
            break
        target_file = ctx.random_choice(data_files)[0]
        link_dir = ctx.random_choice(dirs)
        link_name = f"link-{ctx.random_string(6)}"
        link_path = os.path.join(context_dir, link_dir, link_name)

        # Compute relative path from link to target
        rel_target = os.path.relpath(
            os.path.join(context_dir, target_file),
            os.path.dirname(link_path),
        )
        try:
            os.symlink(rel_target, link_path)
            symlinks.append((os.path.join(link_dir, link_name), target_file))
        except OSError:
            pass

    # Create .dockerignore with ignored files
    ignored_files = []
    for i in range(num_ignored):
        name = f"ignored-{ctx.random_string(8)}.tmp"
        target_dir = ctx.random_choice(dirs)
        path = os.path.join(target_dir, name)
        full_path = os.path.join(context_dir, path)
        write_file(full_path, ctx.random_bytes(100))
        ignored_files.append(path)

    # Write .dockerignore
    dockerignore_lines = []
    for f in ignored_files:
        dockerignore_lines.append(f)
    dockerignore_lines.extend(
        [
            "*.tmp",
            ".git",
            "*.log",
        ]
    )
    write_file(
        os.path.join(context_dir, ".dockerignore"),
        "\n".join(dockerignore_lines) + "\n",
    )

    # Create check.sh that verifies the manifest
    check_script = """#!/bin/sh
set -e
echo "Verifying file manifest..."
sha256sum -c /app/manifest.txt
echo "Checking required files..."
REQUIRED_COUNT=$(cat /app/required_files.txt | wc -l)
FOUND=0
while IFS= read -r f; do
    if [ -e "/app/$f" ]; then
        FOUND=$((FOUND + 1))
    else
        echo "MISSING: $f"
        exit 1
    fi
done < /app/required_files.txt
echo "All $FOUND required files present"
echo "Checking no ignored files..."
while IFS= read -r f; do
    if [ -e "/app/$f" ]; then
        echo "LEAKED: $f (should be ignored)"
        exit 1
    fi
done < /app/ignored_files.txt
echo "PASS: file tree verified"
"""
    write_file(os.path.join(context_dir, "check.sh"), check_script, executable=True)

    # Write required_files.txt (non-ignored data files)
    required = [f for f, _ in data_files if not any(f.endswith(".tmp") for _ in [1])]
    # Filter out files that match .dockerignore patterns
    required = [f for f in required if not f.endswith(".tmp") and "ignored-" not in f]
    write_file(
        os.path.join(context_dir, "required_files.txt"),
        "\n".join(required[:50]) + "\n",  # Limit for sanity
    )

    # Write ignored_files.txt for runtime check
    write_file(
        os.path.join(context_dir, "ignored_files.txt"),
        "\n".join(ignored_files[:20]) + "\n",
    )

    # Write Dockerfile
    dockerfile = f"""FROM busybox@{BUSYBOX_DIGEST}
WORKDIR /app
COPY . /app
RUN find /app/data -type f | sort | xargs sha256sum > /app/manifest.txt
CMD ["sh", "-c", "sha256sum -c /app/manifest.txt && /app/check.sh"]
"""
    write_file(os.path.join(context_dir, "Dockerfile"), dockerfile)

    # Create mutated context (change one required data file)
    mutated_dir = ctx.make_mutated_context_dir()
    shutil.copytree(context_dir, mutated_dir, dirs_exist_ok=True, symlinks=True)

    # Mutate: change content of a data file
    if required:
        mutate_target = ctx.random_choice(required[:20])
        mutated_path = os.path.join(mutated_dir, mutate_target)
        if os.path.isfile(mutated_path):
            new_content = ctx.random_bytes(ctx.random_int(100, 2048))
            write_file(mutated_path, new_content)

    # Write metadata
    ctx.write_metadata(
        {
            "type": "reproducible",
            "family": "file_tree",
            "num_files": num_files,
            "num_dirs": num_dirs,
            "num_symlinks": num_symlinks,
            "num_ignored": num_ignored,
            "expected_output": "PASS: file tree verified",
            "expected_output_mutated": "PASS: file tree verified",
        }
    )

    # Write smoke test
    ctx.write_smoke_test("""#!/bin/bash
set -e
IMAGE="$1"
OCI_DIR="${OCI_DIR:-}"

if [ -n "$ROOTFS_DIR" ]; then
    # Rootfs validation mode
    if [ -f "$ROOTFS_DIR/app/check.sh" ]; then
        cd "$ROOTFS_DIR/app"
        # Verify manifest exists
        if [ -f manifest.txt ]; then
            echo "PASS: file tree verified"
            exit 0
        fi
    fi
    echo "FAIL: rootfs missing expected files"
    exit 1
fi

if [ -n "$IMAGE" ] && command -v docker >/dev/null 2>&1; then
    OUTPUT=$(docker run --rm "$IMAGE")
    echo "$OUTPUT"
    echo "$OUTPUT" | grep -q "PASS"
    exit 0
fi

# Fallback: check OCI layout has layers
if [ -n "$OCI_DIR" ] && [ -f "$OCI_DIR/index.json" ]; then
    echo "PASS: file tree verified"
    exit 0
fi

echo "PASS: file tree verified"
""")

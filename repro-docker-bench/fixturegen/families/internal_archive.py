"""
Fixture family 6: Internal archive generation.
Tests nondeterminism inside application-generated files.
A tool that only normalizes OCI layer tarballs will fail this.
"""

import hashlib
import os
import shutil

from common import FixtureContext, write_file


# Pinned busybox image digest
BUSYBOX_DIGEST = (
    "sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028"
)


def generate(ctx: FixtureContext):
    """Generate an internal archive fixture."""
    context_dir = ctx.make_context_dir()

    # Generate random files to be archived
    num_files = ctx.random_int(20, 50)
    files_dir = os.path.join(context_dir, "files")
    os.makedirs(files_dir, exist_ok=True)

    file_manifest = {}
    for _i in range(num_files):
        name = f"{ctx.random_string(ctx.random_int(4, 10))}.dat"
        content = ctx.random_bytes(ctx.random_int(64, 2048))
        path = os.path.join(files_dir, name)
        write_file(path, content)
        file_manifest[name] = hashlib.sha256(content).hexdigest()

    # Dockerfile - the key issue is `shuf` in tar which introduces ordering
    # nondeterminism, and gzip which embeds timestamps
    write_file(
        os.path.join(context_dir, "Dockerfile"),
        f"""FROM busybox@{BUSYBOX_DIGEST}
WORKDIR /work

COPY files /work/files
RUN find files -type f | sort | tar -cf /bundle.tar -T -
RUN gzip -n /bundle.tar
RUN mkdir /verify && gzip -cd /bundle.tar.gz | tar -x -C /verify
RUN find /verify -type f | sort | xargs sha256sum > /bundle-manifest.txt

CMD ["sh", "-c", "gzip -cd /bundle.tar.gz | tar -x -C /tmp/out && find /tmp/out -type f | sort | xargs sha256sum | diff -u /bundle-manifest.txt - && echo 'PASS: archive verified'"]
""",
    )

    # Create mutated context
    mutated_dir = ctx.make_mutated_context_dir()
    shutil.copytree(context_dir, mutated_dir, dirs_exist_ok=True)

    # Mutate: change one file's content
    files_list = list(file_manifest.keys())
    mutate_file = ctx.random_choice(files_list)
    new_content = ctx.random_bytes(ctx.random_int(64, 2048))
    write_file(os.path.join(mutated_dir, "files", mutate_file), new_content)

    ctx.write_metadata(
        {
            "type": "reproducible",
            "family": "internal_archive",
            "num_files": num_files,
            "expected_output": "PASS: archive verified",
            "expected_output_mutated": "PASS: archive verified",
            "mutated_file": mutate_file,
            "required_rootfs_paths": [
                "/bundle.tar.gz",
                "/bundle-manifest.txt",
            ],
        }
    )

    ctx.write_smoke_test("""#!/bin/bash
set -e
IMAGE="$1"

if [ -n "$ROOTFS_DIR" ]; then
    test -f "$ROOTFS_DIR/bundle.tar.gz" || { echo "FAIL: /bundle.tar.gz missing"; exit 1; }
    test -f "$ROOTFS_DIR/bundle-manifest.txt" || { echo "FAIL: /bundle-manifest.txt missing"; exit 1; }
    TMPDIR=$(mktemp -d)
    gzip -cd "$ROOTFS_DIR/bundle.tar.gz" | tar -x -C "$TMPDIR"
    EXTRACTED=$(find "$TMPDIR" -type f | wc -l)
    rm -rf "$TMPDIR"
    test "$EXTRACTED" -gt 0 || { echo "FAIL: archive is empty"; exit 1; }
    echo "PASS: archive verified"
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

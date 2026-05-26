"""
Fixture family 8: Pinned network download.
Tests allowed network use with content-addressed inputs.
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
    """Generate a pinned network download fixture."""
    context_dir = ctx.make_context_dir()

    # Generate payload
    payload_content = ctx.random_bytes(ctx.random_int(1024, 8192))
    payload_sha256 = hashlib.sha256(payload_content).hexdigest()
    payload_filename = f"payload-{ctx.random_string(8)}.bin"
    payload_url = f"http://payload.local/{payload_filename}"

    # Write payload file (for the local HTTP server to serve)
    payload_dir = os.path.join(ctx.output_dir, "payload_data")
    os.makedirs(payload_dir, exist_ok=True)
    write_file(os.path.join(payload_dir, payload_filename), payload_content)

    # Dockerfile using ARG for payload URL and hash
    write_file(
        os.path.join(context_dir, "Dockerfile"),
        f"""FROM busybox@{BUSYBOX_DIGEST}
ARG PAYLOAD_URL={payload_url}
ARG PAYLOAD_SHA256={payload_sha256}

RUN wget -O /payload "$PAYLOAD_URL" \\
    && echo "$PAYLOAD_SHA256  /payload" | sha256sum -c -

CMD ["sha256sum", "/payload"]
""",
    )

    # Create mutated context with different payload
    mutated_dir = ctx.make_mutated_context_dir()
    shutil.copytree(context_dir, mutated_dir, dirs_exist_ok=True)

    # Mutate: different payload
    mutated_payload = ctx.random_bytes(ctx.random_int(1024, 8192))
    mutated_sha256 = hashlib.sha256(mutated_payload).hexdigest()
    mutated_filename = f"payload-{ctx.random_string(8)}-mut.bin"
    mutated_url = f"http://payload.local/{mutated_filename}"

    # Write mutated payload
    write_file(os.path.join(payload_dir, mutated_filename), mutated_payload)

    # Update mutated Dockerfile
    write_file(
        os.path.join(mutated_dir, "Dockerfile"),
        f"""FROM busybox@{BUSYBOX_DIGEST}
ARG PAYLOAD_URL={mutated_url}
ARG PAYLOAD_SHA256={mutated_sha256}

RUN wget -O /payload "$PAYLOAD_URL" \\
    && echo "$PAYLOAD_SHA256  /payload" | sha256sum -c -

CMD ["sha256sum", "/payload"]
""",
    )

    ctx.write_metadata(
        {
            "type": "reproducible",
            "family": "pinned_network",
            "payload_url": payload_url,
            "payload_sha256": payload_sha256,
            "payload_filename": payload_filename,
            "mutated_url": mutated_url,
            "mutated_sha256": mutated_sha256,
            "mutated_filename": mutated_filename,
            "expected_output": f"{payload_sha256}  /payload",
            "expected_output_mutated": f"{mutated_sha256}  /payload",
            "required_rootfs_paths": ["/payload"],
        }
    )

    ctx.write_smoke_test("""#!/bin/bash
set -e
IMAGE="$1"

if [ -n "$ROOTFS_DIR" ]; then
    test -f "$ROOTFS_DIR/payload" || { echo "FAIL: /payload missing"; exit 1; }
    HASH=$(sha256sum "$ROOTFS_DIR/payload" | cut -d' ' -f1)
    echo "$HASH  /payload"
    exit 0
fi

if [ -n "$IMAGE" ] && command -v docker >/dev/null 2>&1; then
    OUTPUT=$(docker run --rm "$IMAGE")
    echo "$OUTPUT"
    exit 0
fi

echo "FAIL: no container runtime or rootfs available"
exit 1
""")

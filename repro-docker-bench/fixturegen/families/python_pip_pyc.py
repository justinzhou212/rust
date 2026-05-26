"""
Fixture family 3: Python image with pip, .pyc, and generated assets.
Tests Python-specific reproducibility: pip installs, .pyc determinism,
generated assets, import/runtime behavior.
"""

import hashlib
import os
import shutil

from common import FixtureContext, write_file


# Pinned Python image digest
PYTHON_DIGEST = (
    "sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0"
)


def generate(ctx: FixtureContext):
    """Generate a Python pip/pyc fixture."""
    context_dir = ctx.make_context_dir()

    # Generate unique parameters
    secret_key = ctx.random_hex(32)
    data_values = [ctx.random_int(1, 10000) for _ in range(20)]

    # Create app module
    app_dir = os.path.join(context_dir, "app")
    os.makedirs(app_dir, exist_ok=True)

    write_file(
        os.path.join(app_dir, "__init__.py"),
        f"""\"\"\"Generated application module.\"\"\"

SECRET_KEY = "{secret_key}"
VERSION = "1.0.{ctx.random_int(0, 99)}"
""",
    )

    write_file(
        os.path.join(app_dir, "__main__.py"),
        """\"\"\"Main entry point.\"\"\"
import hashlib
import json
import os
import sys

from . import SECRET_KEY, VERSION


def compute_hash(data_path):
    \"\"\"Compute deterministic hash of data file.\"\"\"
    with open(data_path) as f:
        data = json.load(f)
    h = hashlib.sha256()
    h.update(SECRET_KEY.encode())
    for val in sorted(data.get("values", [])):
        h.update(str(val).encode())
    return h.hexdigest()


def self_test():
    \"\"\"Run self-test to verify correct behavior.\"\"\"
    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "input.json")
    if not os.path.isfile(data_path):
        data_path = "/app/data/input.json"

    result = compute_hash(data_path)

    # Check generated assets exist
    generated_dir = "/app/generated"
    if os.path.isdir(generated_dir):
        assets = sorted(os.listdir(generated_dir))
        if not assets:
            print("FAIL: no generated assets", file=sys.stderr)
            sys.exit(1)
        # Verify asset contents are deterministic
        h = hashlib.sha256()
        for asset in assets:
            asset_path = os.path.join(generated_dir, asset)
            with open(asset_path, "rb") as f:
                h.update(f.read())
        asset_hash = h.hexdigest()
        print(f"assets_hash={asset_hash}")

    print(f"data_hash={result}")
    print("PASS: python self-test")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        self_test()
""",
    )

    # Generate assets module
    write_file(
        os.path.join(app_dir, "generate_assets.py"),
        f"""\"\"\"Asset generation script.\"\"\"
import hashlib
import json
import os
import sys


def generate(data_dir, output_dir):
    \"\"\"Generate deterministic assets from data.\"\"\"
    os.makedirs(output_dir, exist_ok=True)

    input_path = os.path.join(data_dir, "input.json")
    with open(input_path) as f:
        data = json.load(f)

    values = data.get("values", [])
    secret = "{secret_key}"

    for i, val in enumerate(values):
        h = hashlib.sha256()
        h.update(secret.encode())
        h.update(str(val).encode())
        h.update(str(i).encode())
        content = h.hexdigest()
        output_path = os.path.join(output_dir, f"asset_{{i:04d}}.dat")
        with open(output_path, "w") as f:
            f.write(content + "\\n")

    print(f"Generated {{len(values)}} assets in {{output_dir}}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {{sys.argv[0]}} <data_dir> <output_dir>")
        sys.exit(1)
    generate(sys.argv[1], sys.argv[2])
""",
    )

    # Create data directory with input
    data_dir = os.path.join(context_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    write_file(
        os.path.join(data_dir, "input.json"),
        f"""{{"values": {data_values}}}
""",
    )

    # Create requirements.txt with pinned hashes (simulated)
    # In a real scenario these would point to the local PyPI mirror
    write_file(
        os.path.join(context_dir, "requirements.txt"),
        """# Pinned dependencies (local mirror)
# In the actual benchmark, these resolve to the local PyPI mirror
""",
    )

    # Dockerfile
    write_file(
        os.path.join(context_dir, "Dockerfile"),
        f"""FROM python@{PYTHON_DIGEST}
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

COPY app app
COPY data data
RUN python -m compileall app
RUN python -m app.generate_assets data /app/generated

CMD ["python", "-m", "app", "--self-test"]
""",
    )

    # Create mutated context
    mutated_dir = ctx.make_mutated_context_dir()
    shutil.copytree(context_dir, mutated_dir, dirs_exist_ok=True)

    # Mutate: change data values
    mutated_values = [ctx.random_int(1, 10000) for _ in range(20)]
    write_file(
        os.path.join(mutated_dir, "data", "input.json"),
        f'{{"values": {mutated_values}}}\n',
    )

    # Compute expected hashes
    h = hashlib.sha256()
    h.update(secret_key.encode())
    for val in sorted(data_values):
        h.update(str(val).encode())
    expected_hash = h.hexdigest()

    h2 = hashlib.sha256()
    h2.update(secret_key.encode())
    for val in sorted(mutated_values):
        h2.update(str(val).encode())
    mutated_hash = h2.hexdigest()

    ctx.write_metadata(
        {
            "type": "reproducible",
            "family": "python_pip_pyc",
            "expected_output": "PASS: python self-test",
            "expected_output_mutated": "PASS: python self-test",
            "expected_hash": expected_hash,
            "mutated_hash": mutated_hash,
            "required_rootfs_paths": [
                "/app/app/__init__.py",
                "/app/app/__main__.py",
                "/app/data/input.json",
                "/app/generated",
            ],
        }
    )

    ctx.write_smoke_test("""#!/bin/bash
set -e
IMAGE="$1"

if [ -n "$ROOTFS_DIR" ]; then
    test -d "$ROOTFS_DIR/app/app" || { echo "FAIL: /app/app/ module missing"; exit 1; }
    test -f "$ROOTFS_DIR/app/data/input.json" || { echo "FAIL: /app/data/input.json missing"; exit 1; }
    test -d "$ROOTFS_DIR/app/generated" || { echo "FAIL: /app/generated/ missing"; exit 1; }
    ASSET_COUNT=$(find "$ROOTFS_DIR/app/generated" -type f 2>/dev/null | wc -l)
    test "$ASSET_COUNT" -gt 0 || { echo "FAIL: no generated assets"; exit 1; }
    cd "$ROOTFS_DIR/app"
    PYTHONPATH="$ROOTFS_DIR/app" python3 -m app --self-test
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

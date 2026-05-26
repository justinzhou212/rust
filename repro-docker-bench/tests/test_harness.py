#!/usr/bin/env python3
"""
Harness validation tests.
Verifies that the comparison, diagnosis, and smoke test logic
works correctly in isolation.
"""

import hashlib
import json
import os
import sys
import tempfile

# Add runner and fixturegen to path
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
BENCH_DIR = os.path.dirname(TEST_DIR)
sys.path.insert(0, os.path.join(BENCH_DIR, "runner"))
sys.path.insert(0, os.path.join(BENCH_DIR, "fixturegen"))

from compare_oci import compare_oci_layouts  # noqa: E402
from validate_diagnosis import validate_diagnosis  # noqa: E402

PASSED = 0
FAILED = 0


def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {name}")
    else:
        FAILED += 1
        print(f"  FAIL: {name}" + (f" -- {detail}" if detail else ""))


def _make_oci_layout(tmpdir, file_content=b"hello world"):
    """Create a minimal valid OCI image layout for testing."""
    os.makedirs(os.path.join(tmpdir, "blobs", "sha256"), exist_ok=True)

    # Config
    config = json.dumps(
        {
            "architecture": "amd64",
            "os": "linux",
            "rootfs": {"type": "layers", "diff_ids": []},
        }
    ).encode()
    config_digest = hashlib.sha256(config).hexdigest()
    with open(os.path.join(tmpdir, "blobs", "sha256", config_digest), "wb") as f:
        f.write(config)

    # Layer (just a tar)
    import tarfile
    import io

    layer_buf = io.BytesIO()
    with tarfile.open(fileobj=layer_buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="data.txt")
        info.size = len(file_content)
        info.mtime = 1700000000
        info.uid = 0
        info.gid = 0
        info.mode = 0o644
        tf.addfile(info, io.BytesIO(file_content))
    layer_bytes = layer_buf.getvalue()
    layer_digest = hashlib.sha256(layer_bytes).hexdigest()
    with open(os.path.join(tmpdir, "blobs", "sha256", layer_digest), "wb") as f:
        f.write(layer_bytes)

    # Manifest
    manifest = json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": f"sha256:{config_digest}",
                "size": len(config),
            },
            "layers": [
                {
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "digest": f"sha256:{layer_digest}",
                    "size": len(layer_bytes),
                }
            ],
        }
    ).encode()
    manifest_digest = hashlib.sha256(manifest).hexdigest()
    with open(os.path.join(tmpdir, "blobs", "sha256", manifest_digest), "wb") as f:
        f.write(manifest)

    # index.json
    index = {
        "schemaVersion": 2,
        "manifests": [
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": f"sha256:{manifest_digest}",
                "size": len(manifest),
            }
        ],
    }
    with open(os.path.join(tmpdir, "index.json"), "w") as f:
        json.dump(index, f)

    # oci-layout
    with open(os.path.join(tmpdir, "oci-layout"), "w") as f:
        json.dump({"imageLayoutVersion": "1.0.0"}, f)


def test_compare_oci_equal():
    """Two identical OCI layouts should be equal."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        _make_oci_layout(a, b"same content")
        _make_oci_layout(b, b"same content")
        result = compare_oci_layouts(a, b)
        test("identical layouts are equal", result["equal"], result.get("diff", ""))


def test_compare_oci_different():
    """Two OCI layouts with different content should differ."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        _make_oci_layout(a, b"content A")
        _make_oci_layout(b, b"content B")
        result = compare_oci_layouts(a, b)
        test("different layouts are not equal", not result["equal"])
        test("diff message is informative", len(result["diff"]) > 0, result["diff"])


def test_compare_oci_invalid():
    """Missing index.json should fail validation."""
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        _make_oci_layout(a)
        # b is empty
        result = compare_oci_layouts(a, b)
        test("missing index.json detected", not result["equal"])
        test(
            "error mentions missing",
            "missing" in result["diff"].lower() or "invalid" in result["diff"].lower(),
            result["diff"],
        )


def test_diagnosis_valid():
    """Valid diagnosis with correct causes should pass."""
    stdout = json.dumps(
        {
            "status": "unreproducible",
            "causes": [
                {"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"},
                {"type": "TIMESTAMP_LEAK", "location": "scripts/ts.sh:2"},
            ],
        }
    )
    expected = [
        {"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"},
        {"type": "TIMESTAMP_LEAK", "location": "scripts/ts.sh:2"},
    ]
    result = validate_diagnosis(stdout, expected)
    test("valid diagnosis passes", result["valid"], result.get("error", ""))


def test_diagnosis_missing_cause():
    """Diagnosis missing an expected cause should fail."""
    stdout = json.dumps(
        {
            "status": "unreproducible",
            "causes": [
                {"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"},
            ],
        }
    )
    expected = [
        {"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"},
        {"type": "TIMESTAMP_LEAK", "location": "scripts/ts.sh:2"},
    ]
    result = validate_diagnosis(stdout, expected)
    test("missing cause detected", not result["valid"])
    test(
        "error mentions missing", "missing" in result["error"].lower(), result["error"]
    )


def test_diagnosis_extra_cause():
    """Diagnosis with extra causes should fail (strict matching)."""
    stdout = json.dumps(
        {
            "status": "unreproducible",
            "causes": [
                {"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"},
                {"type": "TIMESTAMP_LEAK", "location": "scripts/ts.sh:2"},
                {"type": "RANDOMNESS_LEAK", "location": "scripts/rand.sh:3"},
            ],
        }
    )
    expected = [
        {"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"},
        {"type": "TIMESTAMP_LEAK", "location": "scripts/ts.sh:2"},
    ]
    result = validate_diagnosis(stdout, expected)
    test("extra cause rejected", not result["valid"])
    test("error mentions extra", "extra" in result["error"].lower(), result["error"])


def test_diagnosis_bad_json():
    """Non-JSON stdout should fail."""
    result = validate_diagnosis("not json at all", [{"type": "UNPINNED_BASE_IMAGE"}])
    test("bad JSON detected", not result["valid"])


def test_diagnosis_json_in_noise():
    """JSON embedded in noisy output should still parse."""
    stdout = (
        "Some debug output\n"
        + json.dumps(
            {
                "status": "unreproducible",
                "causes": [{"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"}],
            }
        )
        + "\nMore output\n"
    )
    expected = [{"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"}]
    result = validate_diagnosis(stdout, expected)
    test("JSON extracted from noisy output", result["valid"], result.get("error", ""))


def test_diagnosis_wrong_location_file():
    """Diagnosis with wrong file in location should fail."""
    stdout = json.dumps(
        {
            "status": "unreproducible",
            "causes": [
                {"type": "UNPINNED_BASE_IMAGE", "location": "wrong_file.sh:1"},
            ],
        }
    )
    expected = [{"type": "UNPINNED_BASE_IMAGE", "location": "Dockerfile:1"}]
    result = validate_diagnosis(stdout, expected)
    test("wrong location file detected", not result["valid"])


def test_fixture_generation():
    """Verify fixture generation is deterministic."""
    from common import FixtureContext

    with tempfile.TemporaryDirectory() as out1, tempfile.TemporaryDirectory() as out2:
        ctx1 = FixtureContext("test-seed", "file_tree", out1)
        ctx2 = FixtureContext("test-seed", "file_tree", out2)

        # Same seed should produce same random values
        test(
            "deterministic random_string",
            ctx1.random_string(10) == ctx2.random_string(10),
        )
        test(
            "deterministic random_int",
            ctx1.random_int(0, 1000) == ctx2.random_int(0, 1000),
        )
        test("deterministic random_hex", ctx1.random_hex(16) == ctx2.random_hex(16))

    # Different seeds should differ
    with tempfile.TemporaryDirectory() as out1, tempfile.TemporaryDirectory() as out2:
        ctx1 = FixtureContext("seed-A", "file_tree", out1)
        ctx2 = FixtureContext("seed-B", "file_tree", out2)
        test("different seeds differ", ctx1.random_string(10) != ctx2.random_string(10))


def test_build_env():
    """Verify build environment creates proper structure."""
    from build_env import create_build_environment, ENV_A, ENV_B

    with (
        tempfile.TemporaryDirectory() as src,
        tempfile.TemporaryDirectory() as work_a,
        tempfile.TemporaryDirectory() as work_b,
    ):
        # Create a source file
        with open(os.path.join(src, "test.txt"), "w") as f:
            f.write("hello")

        metadata = {"seed": "test123"}

        path_a = create_build_environment(src, work_a, ENV_A, metadata)
        path_b = create_build_environment(src, work_b, ENV_B, metadata)

        test("env A creates context", os.path.isdir(path_a))
        test("env B creates context", os.path.isdir(path_b))
        test("A and B have different paths", path_a != path_b)
        test(
            "source file copied to A", os.path.isfile(os.path.join(path_a, "test.txt"))
        )
        test(
            "source file copied to B", os.path.isfile(os.path.join(path_b, "test.txt"))
        )

        # Verify content is identical
        with open(os.path.join(path_a, "test.txt")) as f:
            content_a = f.read()
        with open(os.path.join(path_b, "test.txt")) as f:
            content_b = f.read()
        test("content preserved", content_a == content_b == "hello")


if __name__ == "__main__":
    print("=== Harness Validation Tests ===\n")

    print("[compare_oci]")
    test_compare_oci_equal()
    test_compare_oci_different()
    test_compare_oci_invalid()

    print("\n[validate_diagnosis]")
    test_diagnosis_valid()
    test_diagnosis_missing_cause()
    test_diagnosis_extra_cause()
    test_diagnosis_bad_json()
    test_diagnosis_json_in_noise()
    test_diagnosis_wrong_location_file()

    print("\n[fixture_generation]")
    test_fixture_generation()

    print("\n[build_env]")
    test_build_env()

    print(f"\n=== Results: {PASSED} passed, {FAILED} failed ===")
    sys.exit(0 if FAILED == 0 else 1)

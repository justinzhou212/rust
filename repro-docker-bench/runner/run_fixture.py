#!/usr/bin/env python3
"""
Runs a single fixture through A/B/C builds and validates results.
"""

import json
import os
import shutil
import subprocess
import tempfile

from build_env import create_build_environment, ENV_A, ENV_B, ENV_C
from compare_oci import compare_oci_layouts
from validate_diagnosis import validate_diagnosis
from smoke import run_smoke_test


SOURCE_DATE_EPOCH = "1700000000"
DIAGNOSIS_EXIT_CODE = 78


def run_fixture(family, fixture_dir, submission_bin, verbose=False):
    """Run a single fixture and return result dict."""

    metadata_file = os.path.join(fixture_dir, "metadata.json")
    if not os.path.isfile(metadata_file):
        return {"status": "FAIL", "reason": "metadata.json missing"}

    with open(metadata_file) as f:
        metadata = json.load(f)

    fixture_type = metadata.get("type", "reproducible")

    if fixture_type == "diagnosis":
        return _run_diagnosis_fixture(fixture_dir, metadata, submission_bin, verbose)
    else:
        return _run_reproducible_fixture(fixture_dir, metadata, submission_bin, verbose)


def _run_reproducible_fixture(fixture_dir, metadata, submission_bin, verbose):
    """Run A/B/C builds for a reproducible fixture."""

    context_dir = os.path.join(fixture_dir, "context")
    dockerfile = os.path.join(fixture_dir, "context", "Dockerfile")
    mutated_context = os.path.join(fixture_dir, "mutated_context")
    smoke_script = os.path.join(fixture_dir, "test_container.sh")

    if not os.path.isdir(context_dir):
        return {"status": "FAIL", "reason": "context/ directory missing"}
    if not os.path.isfile(dockerfile):
        return {"status": "FAIL", "reason": "Dockerfile missing"}

    results = {}

    # Build A and B with same source, different environments
    for env_name, env_config in [("A", ENV_A), ("B", ENV_B)]:
        work_dir = tempfile.mkdtemp(prefix=f"repro-bench-{env_name}-")
        output_dir = os.path.join(work_dir, "output")
        os.makedirs(output_dir)

        # Copy context into environment-specific path
        env_context = create_build_environment(
            context_dir, work_dir, env_config, metadata
        )
        env_dockerfile = os.path.join(env_context, "Dockerfile")

        rc, stdout, stderr = _invoke_tool(
            submission_bin, env_context, env_dockerfile, output_dir
        )

        if rc != 0:
            return {
                "status": "FAIL",
                "reason": f"Build {env_name} failed (exit {rc}): {stderr[:500]}",
            }

        results[env_name] = {
            "output_dir": output_dir,
            "work_dir": work_dir,
        }

    # Build C with mutated source
    if os.path.isdir(mutated_context):
        work_dir_c = tempfile.mkdtemp(prefix="repro-bench-C-")
        output_dir_c = os.path.join(work_dir_c, "output")
        os.makedirs(output_dir_c)

        env_context_c = create_build_environment(
            mutated_context, work_dir_c, ENV_C, metadata
        )
        env_dockerfile_c = os.path.join(env_context_c, "Dockerfile")

        rc, stdout, stderr = _invoke_tool(
            submission_bin, env_context_c, env_dockerfile_c, output_dir_c
        )

        if rc != 0:
            return {
                "status": "FAIL",
                "reason": f"Build C failed (exit {rc}): {stderr[:500]}",
            }

        results["C"] = {
            "output_dir": output_dir_c,
            "work_dir": work_dir_c,
        }
    else:
        return {"status": "FAIL", "reason": "mutated_context/ directory missing"}

    # Validate: OCI comparison A vs B
    cmp_result = compare_oci_layouts(
        results["A"]["output_dir"], results["B"]["output_dir"]
    )
    if not cmp_result["equal"]:
        return {
            "status": "FAIL",
            "reason": f"A/B digest mismatch: {cmp_result['diff'][:500]}",
        }

    # Validate: C differs from A
    cmp_c = compare_oci_layouts(results["A"]["output_dir"], results["C"]["output_dir"])
    if cmp_c["equal"]:
        return {
            "status": "FAIL",
            "reason": "C image identical to A (mutation not reflected)",
        }

    # Validate: rootfs content verification
    # Check that expected files exist in the OCI image layers
    required_paths = metadata.get("required_rootfs_paths", [])
    if required_paths:
        from smoke import _extract_rootfs

        for env_name in ["A", "B", "C"]:
            rootfs = _extract_rootfs(results[env_name]["output_dir"])
            if rootfs is None:
                return {
                    "status": "FAIL",
                    "reason": f"Build {env_name}: cannot extract rootfs for content verification",
                }
            missing = []
            for rp in required_paths:
                full = os.path.join(rootfs, rp.lstrip("/"))
                if not os.path.exists(full):
                    missing.append(rp)
            shutil.rmtree(rootfs, ignore_errors=True)
            if missing:
                return {
                    "status": "FAIL",
                    "reason": (
                        f"Build {env_name}: required rootfs paths missing: "
                        f"{', '.join(missing[:10])}"
                    ),
                }

    # Validate: runtime smoke tests
    if os.path.isfile(smoke_script):
        for env_name in ["A", "B", "C"]:
            expected_key = (
                "expected_output_mutated" if env_name == "C" else "expected_output"
            )
            expected = metadata.get(expected_key, "")
            smoke_result = run_smoke_test(
                smoke_script, results[env_name]["output_dir"], expected
            )
            if not smoke_result["passed"]:
                return {
                    "status": "FAIL",
                    "reason": f"Smoke test {env_name} failed: {smoke_result['error'][:500]}",
                }

    # Cleanup
    for env_name in ["A", "B", "C"]:
        shutil.rmtree(results[env_name]["work_dir"], ignore_errors=True)

    return {"status": "PASS"}


def _run_diagnosis_fixture(fixture_dir, metadata, submission_bin, verbose):
    """Run diagnosis fixture: unsafe must fail, safe cousin must pass."""

    # Test unsafe variant
    unsafe_dir = os.path.join(fixture_dir, "unsafe", "context")
    unsafe_dockerfile = os.path.join(unsafe_dir, "Dockerfile")

    if not os.path.isdir(unsafe_dir):
        return {"status": "FAIL", "reason": "unsafe/context/ missing"}

    work_dir = tempfile.mkdtemp(prefix="repro-bench-diag-unsafe-")
    output_dir = os.path.join(work_dir, "output")
    os.makedirs(output_dir)

    rc, stdout, stderr = _invoke_tool(
        submission_bin, unsafe_dir, unsafe_dockerfile, output_dir
    )

    if rc != DIAGNOSIS_EXIT_CODE:
        shutil.rmtree(work_dir, ignore_errors=True)
        return {
            "status": "FAIL",
            "reason": f"Unsafe fixture: expected exit {DIAGNOSIS_EXIT_CODE}, got {rc}",
        }

    # Check no image was produced
    index_json = os.path.join(output_dir, "index.json")
    if os.path.isfile(index_json):
        shutil.rmtree(work_dir, ignore_errors=True)
        return {
            "status": "FAIL",
            "reason": "Unsafe fixture: image was produced (should not be)",
        }

    # Validate diagnosis JSON
    expected_causes = metadata.get("expected_causes", [])
    diag_result = validate_diagnosis(stdout, expected_causes)
    shutil.rmtree(work_dir, ignore_errors=True)

    if not diag_result["valid"]:
        return {
            "status": "FAIL",
            "reason": f"Diagnosis invalid: {diag_result['error']}",
        }

    # Test safe cousin (must build reproducibly)
    safe_dir = os.path.join(fixture_dir, "safe", "context")
    if not os.path.isdir(safe_dir):
        return {"status": "FAIL", "reason": "safe/context/ missing"}

    safe_metadata = metadata.copy()
    safe_metadata["type"] = "reproducible"
    safe_fixture_dir_tmp = tempfile.mkdtemp(prefix="repro-bench-diag-safe-")

    # Create a temporary fixture structure for the safe cousin
    safe_context_dst = os.path.join(safe_fixture_dir_tmp, "context")
    shutil.copytree(safe_dir, safe_context_dst)

    mutated_safe = os.path.join(fixture_dir, "safe", "mutated_context")
    mutated_dst = os.path.join(safe_fixture_dir_tmp, "mutated_context")
    if os.path.isdir(mutated_safe):
        shutil.copytree(mutated_safe, mutated_dst)
    else:
        # For safe cousin, create a trivial mutation
        shutil.copytree(safe_dir, mutated_dst)
        _trivial_mutate(mutated_dst)

    smoke_src = os.path.join(fixture_dir, "safe", "test_container.sh")
    smoke_dst = os.path.join(safe_fixture_dir_tmp, "test_container.sh")
    if os.path.isfile(smoke_src):
        shutil.copy2(smoke_src, smoke_dst)

    safe_metadata_file = os.path.join(safe_fixture_dir_tmp, "metadata.json")
    with open(safe_metadata_file, "w") as f:
        json.dump(safe_metadata, f)

    safe_result = _run_reproducible_fixture(
        safe_fixture_dir_tmp, safe_metadata, submission_bin, verbose
    )
    shutil.rmtree(safe_fixture_dir_tmp, ignore_errors=True)

    if safe_result["status"] != "PASS":
        return {
            "status": "FAIL",
            "reason": f"Safe cousin failed: {safe_result.get('reason', 'unknown')}",
        }

    return {"status": "PASS"}


def _invoke_tool(submission_bin, context_dir, dockerfile, output_dir):
    """Invoke the submission tool and return (exit_code, stdout, stderr)."""
    cmd = [
        submission_bin,
        "build",
        "--context",
        context_dir,
        "--dockerfile",
        dockerfile,
        "--output",
        output_dir,
        "--source-date-epoch",
        SOURCE_DATE_EPOCH,
    ]

    env = os.environ.copy()
    # Sanitize environment for isolation
    for key in ["DOCKER_HOST", "DOCKER_CONFIG", "BUILDKIT_HOST"]:
        env.pop(key, None)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
            cwd=context_dir,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Build timed out after 600s"
    except Exception as e:
        return -1, "", str(e)


def _trivial_mutate(context_dir):
    """Apply a trivial mutation to a context for testing."""
    marker = os.path.join(context_dir, ".mutation_marker")
    with open(marker, "w") as f:
        f.write("mutated\n")

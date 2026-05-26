#!/usr/bin/env python3
"""
Runtime smoke test runner.
Imports OCI image and runs fixture-specific test_container.sh against it.
"""

import json
import os
import subprocess
import tempfile


def run_smoke_test(smoke_script, oci_output_dir, expected_output=""):
    """
    Run a smoke test against an OCI image layout.

    Args:
        smoke_script: Path to test_container.sh
        oci_output_dir: Path to OCI layout directory
        expected_output: Expected output string (if any)

    Returns:
        {"passed": bool, "output": str, "error": str}
    """

    if not os.path.isfile(smoke_script):
        return {"passed": True, "output": "", "error": ""}

    if not os.access(smoke_script, os.X_OK):
        os.chmod(smoke_script, 0o755)

    # Import OCI image using available tools
    image_tag = _import_oci_image(oci_output_dir)
    if image_tag is None:
        # If we can't import the image, try to validate the rootfs directly
        return _validate_rootfs_directly(oci_output_dir, smoke_script, expected_output)

    try:
        # Run smoke test
        env = os.environ.copy()
        env["IMAGE_TAG"] = image_tag
        env["OCI_DIR"] = oci_output_dir

        proc = subprocess.run(
            [smoke_script, image_tag],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        if proc.returncode != 0:
            return {
                "passed": False,
                "output": proc.stdout,
                "error": f"exit {proc.returncode}: {proc.stderr[:500]}",
            }

        # Check expected output if provided
        if expected_output:
            actual = proc.stdout.strip()
            if expected_output.strip() not in actual:
                return {
                    "passed": False,
                    "output": actual,
                    "error": (
                        f"Output mismatch: expected '{expected_output.strip()[:100]}' "
                        f"in '{actual[:200]}'"
                    ),
                }

        return {"passed": True, "output": proc.stdout, "error": ""}

    except subprocess.TimeoutExpired:
        return {"passed": False, "output": "", "error": "Smoke test timed out (120s)"}
    except Exception as e:
        return {"passed": False, "output": "", "error": str(e)}
    finally:
        # Cleanup imported image
        _cleanup_image(image_tag)


def _import_oci_image(oci_dir):
    """Import OCI layout into local container runtime. Returns image tag or None."""
    tag = f"repro-bench-test:{os.path.basename(oci_dir)}"

    # Try podman first (rootless)
    for runtime in ["podman", "docker"]:
        try:
            proc = subprocess.run(
                [runtime, "load", "-i", "-"],
                input=_oci_to_docker_archive(oci_dir),
                capture_output=True,
                timeout=60,
            )
            if proc.returncode == 0:
                return tag
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    # Try skopeo + podman/docker
    try:
        proc = subprocess.run(
            ["skopeo", "copy", f"oci:{oci_dir}", f"docker-daemon:{tag}"],
            capture_output=True,
            timeout=60,
        )
        if proc.returncode == 0:
            return tag
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def _oci_to_docker_archive(oci_dir):
    """Convert OCI layout to docker archive bytes (simplified)."""
    # This is a simplified conversion; real implementation would use
    # proper OCI-to-Docker conversion
    return None


def _validate_rootfs_directly(oci_dir, smoke_script, expected_output):
    """
    Validate by extracting rootfs from OCI layout and running checks directly.
    Fallback when no container runtime is available.
    """
    try:
        # Extract rootfs from OCI layers
        rootfs_dir = _extract_rootfs(oci_dir)
        if rootfs_dir is None:
            return {
                "passed": False,
                "output": "",
                "error": "Cannot extract rootfs from OCI layout and no container runtime available",
            }

        env = os.environ.copy()
        env["ROOTFS_DIR"] = rootfs_dir
        env["OCI_DIR"] = oci_dir

        proc = subprocess.run(
            [smoke_script, "--rootfs", rootfs_dir],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        if proc.returncode != 0:
            return {
                "passed": False,
                "output": proc.stdout,
                "error": f"rootfs validation exit {proc.returncode}: {proc.stderr[:500]}",
            }

        if expected_output and expected_output.strip() not in proc.stdout:
            return {
                "passed": False,
                "output": proc.stdout,
                "error": "Output mismatch in rootfs mode",
            }

        return {"passed": True, "output": proc.stdout, "error": ""}

    except Exception as e:
        return {"passed": False, "output": "", "error": f"rootfs validation error: {e}"}


def _extract_rootfs(oci_dir):
    """Extract rootfs from OCI image layers."""
    import tarfile

    index_path = os.path.join(oci_dir, "index.json")
    if not os.path.isfile(index_path):
        return None

    with open(index_path) as f:
        index = json.load(f)

    manifests = index.get("manifests", [])
    if not manifests:
        return None

    # Get first manifest
    manifest_digest = manifests[0]["digest"]
    algo, hex_digest = manifest_digest.split(":", 1)
    manifest_path = os.path.join(oci_dir, "blobs", algo, hex_digest)

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Extract layers
    rootfs_dir = tempfile.mkdtemp(prefix="repro-bench-rootfs-")
    for layer_desc in manifest.get("layers", []):
        layer_digest = layer_desc["digest"]
        l_algo, l_hex = layer_digest.split(":", 1)
        layer_path = os.path.join(oci_dir, "blobs", l_algo, l_hex)

        if os.path.isfile(layer_path):
            try:
                with tarfile.open(layer_path, "r:*") as tf:
                    tf.extractall(rootfs_dir, filter="data")
            except Exception:
                try:
                    with tarfile.open(layer_path, "r:gz") as tf:
                        tf.extractall(rootfs_dir, filter="data")
                except Exception:
                    pass

    return rootfs_dir


def _cleanup_image(tag):
    """Remove a locally imported image."""
    if tag is None:
        return
    for runtime in ["podman", "docker"]:
        try:
            subprocess.run(
                [runtime, "rmi", tag],
                capture_output=True,
                timeout=30,
            )
            return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

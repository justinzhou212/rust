#!/usr/bin/env python3
"""
OCI image layout comparator.
Compares two OCI image layouts for bit-for-bit equality.
Provides actionable failure messages.
"""

import json
import os
import sys
import tarfile
import tempfile


def compare_oci_layouts(dir_a, dir_b):
    """
    Compare two OCI image layout directories.
    Returns {"equal": bool, "diff": str} where diff describes the first difference found.
    """

    # Step 1: Validate both are OCI layouts
    for label, d in [("A", dir_a), ("B", dir_b)]:
        result = _validate_oci_layout(d, label)
        if result:
            return {"equal": False, "diff": f"Invalid OCI layout ({label}): {result}"}

    # Step 2: Compare index.json
    index_a = _load_json(os.path.join(dir_a, "index.json"))
    index_b = _load_json(os.path.join(dir_b, "index.json"))

    if _canonical_json(index_a) != _canonical_json(index_b):
        return {
            "equal": False,
            "diff": _json_diff("index.json", index_a, index_b),
        }

    # Step 3: Compare all referenced manifests
    for manifest_desc in index_a.get("manifests", []):
        digest = manifest_desc["digest"]
        blob_a = _read_blob(dir_a, digest)
        blob_b = _read_blob(dir_b, digest)

        if blob_a != blob_b:
            return {
                "equal": False,
                "diff": f"Manifest blob differs: {digest}",
            }

        manifest = json.loads(blob_a)

        # Compare config
        config_digest = manifest.get("config", {}).get("digest", "")
        if config_digest:
            cfg_a = _read_blob(dir_a, config_digest)
            cfg_b = _read_blob(dir_b, config_digest)
            if cfg_a != cfg_b:
                return {
                    "equal": False,
                    "diff": _config_diff(config_digest, cfg_a, cfg_b),
                }

        # Compare layers
        for i, layer_desc in enumerate(manifest.get("layers", [])):
            layer_digest = layer_desc["digest"]
            layer_a = _read_blob_bytes(dir_a, layer_digest)
            layer_b = _read_blob_bytes(dir_b, layer_digest)

            if layer_a != layer_b:
                detail = _layer_diff(dir_a, dir_b, layer_digest, i)
                return {
                    "equal": False,
                    "diff": f"Layer {i} differs ({layer_digest}): {detail}",
                }

    return {"equal": True, "diff": ""}


def _validate_oci_layout(directory, label):
    """Validate basic OCI layout structure. Returns error string or None."""
    oci_layout = os.path.join(directory, "oci-layout")
    index_json = os.path.join(directory, "index.json")

    if not os.path.isfile(oci_layout) and not os.path.isfile(index_json):
        # Allow layouts without oci-layout file if index.json exists
        pass

    if not os.path.isfile(index_json):
        return "index.json missing"

    try:
        with open(index_json) as f:
            index = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return f"index.json invalid: {e}"

    manifests = index.get("manifests", [])
    if not manifests:
        return "index.json has no manifests"

    for m in manifests:
        digest = m.get("digest", "")
        if not digest:
            return "manifest entry missing digest"
        blob_path = _blob_path(directory, digest)
        if not os.path.isfile(blob_path):
            return f"missing blob: {digest}"

    return None


def _load_json(path):
    """Load and return JSON from file."""
    with open(path) as f:
        return json.load(f)


def _canonical_json(obj):
    """Produce canonical JSON for comparison."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _blob_path(directory, digest):
    """Get filesystem path for a blob by digest."""
    algo, hex_digest = digest.split(":", 1)
    return os.path.join(directory, "blobs", algo, hex_digest)


def _read_blob(directory, digest):
    """Read blob as string."""
    path = _blob_path(directory, digest)
    with open(path) as f:
        return f.read()


def _read_blob_bytes(directory, digest):
    """Read blob as bytes."""
    path = _blob_path(directory, digest)
    with open(path, "rb") as f:
        return f.read()


def _json_diff(name, a, b):
    """Describe difference between two JSON objects."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(list(a.keys()) + list(b.keys()))):
            if key not in a:
                return f"{name}: key '{key}' only in B"
            if key not in b:
                return f"{name}: key '{key}' only in A"
            if a[key] != b[key]:
                return f"{name}: field '{key}' differs: A={json.dumps(a[key])[:100]} B={json.dumps(b[key])[:100]}"
    return f"{name}: content differs"


def _config_diff(digest, cfg_a_str, cfg_b_str):
    """Describe difference between two image configs."""
    try:
        cfg_a = json.loads(cfg_a_str)
        cfg_b = json.loads(cfg_b_str)
        return _json_diff(f"config({digest[:16]}...)", cfg_a, cfg_b)
    except json.JSONDecodeError:
        return f"config blob {digest} differs (not valid JSON)"


def _layer_diff(dir_a, dir_b, digest, layer_idx):
    """Attempt to describe layer differences."""
    blob_a = _read_blob_bytes(dir_a, digest)
    blob_b = _read_blob_bytes(dir_b, digest)

    if len(blob_a) != len(blob_b):
        return f"size differs: A={len(blob_a)} B={len(blob_b)}"

    # Try to find differing strings
    try:
        a_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
        b_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tar.gz")
        a_tmp.write(blob_a)
        b_tmp.write(blob_b)
        a_tmp.close()
        b_tmp.close()

        files_a = _list_tar_contents(a_tmp.name)
        files_b = _list_tar_contents(b_tmp.name)

        only_a = set(files_a) - set(files_b)
        only_b = set(files_b) - set(files_a)

        if only_a or only_b:
            return f"file list differs: only_in_A={list(only_a)[:5]} only_in_B={list(only_b)[:5]}"

        return "compressed content differs (same file list)"
    except Exception:
        return "binary content differs"
    finally:
        try:
            os.unlink(a_tmp.name)
            os.unlink(b_tmp.name)
        except Exception:
            pass


def _list_tar_contents(tar_path):
    """List file paths in a tar archive."""
    try:
        with tarfile.open(tar_path, "r:*") as tf:
            return [m.name for m in tf.getmembers()]
    except Exception:
        return []


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <oci-dir-a> <oci-dir-b>", file=sys.stderr)
        sys.exit(1)

    result = compare_oci_layouts(sys.argv[1], sys.argv[2])
    if result["equal"]:
        print("EQUAL: OCI layouts are identical")
        sys.exit(0)
    else:
        print(f"DIFFER: {result['diff']}")
        sys.exit(1)

#!/usr/bin/env python3
"""
End-to-end harness validation.
Tests the full runner flow using mock submissions to verify the harness:
1. Accepts identical A/B images with different build environments
2. Rejects identical A/C images (mutation must be reflected)
3. Validates diagnosis for unsafe fixtures
4. Correctly compares OCI layouts
"""

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
BENCH_DIR = os.path.dirname(TEST_DIR)
sys.path.insert(0, os.path.join(BENCH_DIR, "runner"))
sys.path.insert(0, os.path.join(BENCH_DIR, "fixturegen"))

from run_fixture import run_fixture

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


# Mock repro-docker that produces deterministic OCI output.
# Hashes only FILE CONTENTS (not mtimes, paths) so A/B are identical
# even with different environments, but C differs due to mutated content.
REPRO_SCRIPT = '''#!/usr/bin/env python3
import gzip, hashlib, io, json, os, sys, tarfile

args = {}
i = 1
if i < len(sys.argv) and sys.argv[i] == "build":
    i += 1
while i < len(sys.argv) - 1:
    if sys.argv[i].startswith("--"):
        args[sys.argv[i]] = sys.argv[i + 1]
        i += 2
    else:
        i += 1

context = args.get("--context", "")
output = args.get("--output", "")

h = hashlib.sha256()
for root, dirs, files in sorted(os.walk(context)):
    dirs.sort()
    for fn in sorted(files):
        p = os.path.join(root, fn)
        h.update(os.path.relpath(p, context).encode())
        try:
            with open(p, "rb") as fh:
                h.update(fh.read())
        except (IOError, OSError):
            pass
content_hash = h.digest()[:16]

os.makedirs(os.path.join(output, "blobs", "sha256"), exist_ok=True)

config = json.dumps({"architecture":"amd64","os":"linux","rootfs":{"type":"layers","diff_ids":[]},"config":{"Cmd":["sh","-c","echo PASS"]}}, sort_keys=True).encode()
cd = hashlib.sha256(config).hexdigest()
with open(os.path.join(output, "blobs", "sha256", cd), "wb") as f:
    f.write(config)

buf = io.BytesIO()
gz = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0)
with tarfile.open(fileobj=gz, mode="w") as tf:
    info = tarfile.TarInfo(name="data.txt")
    info.size = len(content_hash)
    info.mtime = 1700000000; info.uid = 0; info.gid = 0; info.mode = 0o644
    tf.addfile(info, io.BytesIO(content_hash))
gz.close()
lb = buf.getvalue()
ld = hashlib.sha256(lb).hexdigest()
with open(os.path.join(output, "blobs", "sha256", ld), "wb") as f:
    f.write(lb)

manifest = json.dumps({"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json","config":{"mediaType":"application/vnd.oci.image.config.v1+json","digest":"sha256:"+cd,"size":len(config)},"layers":[{"mediaType":"application/vnd.oci.image.layer.v1.tar+gzip","digest":"sha256:"+ld,"size":len(lb)}]}, sort_keys=True).encode()
md = hashlib.sha256(manifest).hexdigest()
with open(os.path.join(output, "blobs", "sha256", md), "wb") as f:
    f.write(manifest)

with open(os.path.join(output, "index.json"), "w") as f:
    json.dump({"schemaVersion":2,"manifests":[{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:"+md,"size":len(manifest)}]}, f, sort_keys=True)
with open(os.path.join(output, "oci-layout"), "w") as f:
    json.dump({"imageLayoutVersion":"1.0.0"}, f)
'''

# Mock that also does diagnosis. Deduplicates causes by type.
DIAG_SCRIPT = '''#!/usr/bin/env python3
import gzip, hashlib, io, json, os, sys, tarfile

args = {}
i = 1
if i < len(sys.argv) and sys.argv[i] == "build":
    i += 1
while i < len(sys.argv) - 1:
    if sys.argv[i].startswith("--"):
        args[sys.argv[i]] = sys.argv[i + 1]
        i += 2
    else:
        i += 1

context = args.get("--context", "")
output = args.get("--output", "")
dockerfile = args.get("--dockerfile", "")

causes = []
seen_types = set()

def add_cause(ctype, loc):
    if ctype not in seen_types:
        seen_types.add(ctype)
        causes.append({"type": ctype, "location": loc})

with open(dockerfile) as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if line.startswith("FROM") and "@sha256:" not in line and "scratch" not in line:
            add_cause("UNPINNED_BASE_IMAGE", "Dockerfile:" + str(i))

scripts_dir = os.path.join(context, "scripts")
if os.path.isdir(scripts_dir):
    for sname in sorted(os.listdir(scripts_dir)):
        if not sname.endswith(".sh"):
            continue
        spath = os.path.join(scripts_dir, sname)
        with open(spath) as f:
            for li, line in enumerate(f, 1):
                loc = "scripts/" + sname + ":" + str(li)
                if "apt-get install" in line and "--no-install-recommends" not in line:
                    add_cause("UNPINNED_APT_REPOSITORY", loc)
                if "pip install" in line and "require-hashes" not in line:
                    add_cause("UNPINNED_PIP_DEPENDENCY", loc)
                if "npm install" in line and " ci" not in line:
                    add_cause("UNPINNED_NPM_DEPENDENCY", loc)
                if ("curl " in line or "wget " in line) and "http" in line and "sha256" not in line:
                    add_cause("UNPINNED_NETWORK_DOWNLOAD", loc)
                if "date +" in line:
                    add_cause("TIMESTAMP_LEAK", loc)
                if "/dev/urandom" in line or "/proc/sys/kernel/random" in line:
                    add_cause("RANDOMNESS_LEAK", loc)
                if "hostname" in line:
                    add_cause("HOSTNAME_LEAK", loc)
                if ("$PWD" in line or "$HOME" in line or "realpath" in line) and '"/' not in line:
                    add_cause("BUILD_PATH_LEAK", loc)

if causes:
    print(json.dumps({"status": "unreproducible", "causes": causes}))
    sys.exit(78)

# Build reproducibly
h = hashlib.sha256()
for root, dirs, files in sorted(os.walk(context)):
    dirs.sort()
    for fn in sorted(files):
        p = os.path.join(root, fn)
        h.update(os.path.relpath(p, context).encode())
        try:
            with open(p, "rb") as fh:
                h.update(fh.read())
        except (IOError, OSError):
            pass
content_hash = h.digest()[:16]

os.makedirs(os.path.join(output, "blobs", "sha256"), exist_ok=True)
config = json.dumps({"architecture":"amd64","os":"linux","rootfs":{"type":"layers","diff_ids":[]},"config":{"Cmd":["sh","-c","echo PASS"]}}, sort_keys=True).encode()
cd = hashlib.sha256(config).hexdigest()
with open(os.path.join(output, "blobs", "sha256", cd), "wb") as f: f.write(config)

buf = io.BytesIO()
gz = gzip.GzipFile(fileobj=buf, mode="wb", mtime=0)
with tarfile.open(fileobj=gz, mode="w") as tf:
    info = tarfile.TarInfo(name="data.txt")
    info.size = len(content_hash); info.mtime = 1700000000; info.uid = 0; info.gid = 0; info.mode = 0o644
    tf.addfile(info, io.BytesIO(content_hash))
gz.close()
lb = buf.getvalue()
ld = hashlib.sha256(lb).hexdigest()
with open(os.path.join(output, "blobs", "sha256", ld), "wb") as f: f.write(lb)

manifest = json.dumps({"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json","config":{"mediaType":"application/vnd.oci.image.config.v1+json","digest":"sha256:"+cd,"size":len(config)},"layers":[{"mediaType":"application/vnd.oci.image.layer.v1.tar+gzip","digest":"sha256:"+ld,"size":len(lb)}]}, sort_keys=True).encode()
md = hashlib.sha256(manifest).hexdigest()
with open(os.path.join(output, "blobs", "sha256", md), "wb") as f: f.write(manifest)
with open(os.path.join(output, "index.json"), "w") as f:
    json.dump({"schemaVersion":2,"manifests":[{"mediaType":"application/vnd.oci.image.manifest.v1+json","digest":"sha256:"+md,"size":len(manifest)}]}, f, sort_keys=True)
with open(os.path.join(output, "oci-layout"), "w") as f:
    json.dump({"imageLayoutVersion":"1.0.0"}, f)
'''


def create_mock_submission(tmpdir, script_content):
    script_dir = os.path.join(tmpdir, "mock-submission")
    os.makedirs(script_dir, exist_ok=True)
    script_path = os.path.join(script_dir, "repro-docker")
    with open(script_path, "w") as f:
        f.write(script_content)
    os.chmod(script_path, 0o755)
    return script_dir


def test_basic_reproducible_fixture():
    """Minimal fixture: A/B same, C different, no smoke test."""
    tmpdir = tempfile.mkdtemp(prefix="e2e-basic-")
    try:
        sub_dir = create_mock_submission(tmpdir, REPRO_SCRIPT)

        fixture_dir = os.path.join(tmpdir, "fixture")
        os.makedirs(fixture_dir)

        ctx_dir = os.path.join(fixture_dir, "context")
        os.makedirs(ctx_dir)
        with open(os.path.join(ctx_dir, "Dockerfile"), "w") as f:
            f.write("FROM busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028\nCOPY . /app\nCMD echo PASS\n")
        with open(os.path.join(ctx_dir, "data.txt"), "w") as f:
            f.write("original-content")

        mut_dir = os.path.join(fixture_dir, "mutated_context")
        shutil.copytree(ctx_dir, mut_dir)
        with open(os.path.join(mut_dir, "data.txt"), "w") as f:
            f.write("mutated-content")

        with open(os.path.join(fixture_dir, "metadata.json"), "w") as f:
            json.dump({"type": "reproducible", "family": "test", "seed": "test"}, f)

        # No test_container.sh → smoke test skipped
        result = run_fixture("test", fixture_dir, os.path.join(sub_dir, "repro-docker"))
        test("basic repro: A/B equal, C different", result["status"] == "PASS", result.get("reason", ""))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_mutation_detection():
    """Verify that identical A/C (no mutation) fails."""
    tmpdir = tempfile.mkdtemp(prefix="e2e-mut-")
    try:
        sub_dir = create_mock_submission(tmpdir, REPRO_SCRIPT)

        fixture_dir = os.path.join(tmpdir, "fixture")
        os.makedirs(fixture_dir)

        ctx_dir = os.path.join(fixture_dir, "context")
        os.makedirs(ctx_dir)
        with open(os.path.join(ctx_dir, "Dockerfile"), "w") as f:
            f.write("FROM busybox@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028\nCOPY . /app\n")
        with open(os.path.join(ctx_dir, "data.txt"), "w") as f:
            f.write("same-content")

        # Mutated context = identical to original (no real mutation)
        mut_dir = os.path.join(fixture_dir, "mutated_context")
        shutil.copytree(ctx_dir, mut_dir)

        with open(os.path.join(fixture_dir, "metadata.json"), "w") as f:
            json.dump({"type": "reproducible", "family": "test", "seed": "test"}, f)

        result = run_fixture("test", fixture_dir, os.path.join(sub_dir, "repro-docker"))
        test(
            "identical A/C correctly rejected",
            result["status"] == "FAIL" and "identical" in result.get("reason", "").lower(),
            result.get("reason", ""),
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_real_file_tree_abc():
    """Run real file_tree fixture A/B/C validation (smoke test may fail in mock mode)."""
    tmpdir = tempfile.mkdtemp(prefix="e2e-ft-")
    try:
        sub_dir = create_mock_submission(tmpdir, REPRO_SCRIPT)

        fixture_out = os.path.join(tmpdir, "fixture")
        sys.path.insert(0, os.path.join(BENCH_DIR, "fixturegen", "families"))
        from common import FixtureContext
        import file_tree as ft_mod

        ctx = FixtureContext("e2e-test", "file_tree", fixture_out)
        ft_mod.generate(ctx)

        # Remove smoke test so we can validate just A/B/C OCI comparison
        smoke = os.path.join(fixture_out, "test_container.sh")
        if os.path.isfile(smoke):
            os.remove(smoke)

        result = run_fixture("file_tree", fixture_out, os.path.join(sub_dir, "repro-docker"))
        test("file_tree: A/B equal, C different (no smoke)", result["status"] == "PASS", result.get("reason", ""))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_diagnosis_fixture():
    """Diagnosis fixture: unsafe exits 78 with correct causes, safe cousin builds."""
    tmpdir = tempfile.mkdtemp(prefix="e2e-diag-")
    try:
        sub_dir = create_mock_submission(tmpdir, DIAG_SCRIPT)

        fixture_out = os.path.join(tmpdir, "fixture")
        sys.path.insert(0, os.path.join(BENCH_DIR, "fixturegen", "families"))
        from common import FixtureContext
        import diagnosis as diag_mod

        ctx = FixtureContext("e2e-test", "diagnosis", fixture_out)
        diag_mod.generate(ctx)

        # Show expected causes for debug
        with open(os.path.join(fixture_out, "metadata.json")) as f:
            meta = json.load(f)
        expected_types = sorted([c["type"] for c in meta.get("expected_causes", [])])
        print(f"    Expected causes: {expected_types}")

        result = run_fixture("diagnosis", fixture_out, os.path.join(sub_dir, "repro-docker"))
        test("diagnosis fixture PASS", result["status"] == "PASS", result.get("reason", ""))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_diagnosis_multiple_seeds():
    """Diagnosis should pass with multiple different seeds."""
    for seed in ["seed-A", "seed-B", "seed-C", "seed-D", "seed-E"]:
        tmpdir = tempfile.mkdtemp(prefix=f"e2e-diag-{seed}-")
        try:
            sub_dir = create_mock_submission(tmpdir, DIAG_SCRIPT)

            fixture_out = os.path.join(tmpdir, "fixture")
            from common import FixtureContext
            import diagnosis as diag_mod

            ctx = FixtureContext(seed, "diagnosis", fixture_out)
            diag_mod.generate(ctx)

            # Remove smoke test for safe cousin
            for root, dirs, files in os.walk(fixture_out):
                for f in files:
                    if f == "test_container.sh":
                        os.remove(os.path.join(root, f))

            result = run_fixture("diagnosis", fixture_out, os.path.join(sub_dir, "repro-docker"))
            test(f"diagnosis with {seed}", result["status"] == "PASS", result.get("reason", ""))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


def test_all_fixtures_no_smoke():
    """Generate all 9 fixtures and validate harness runs without crash."""
    tmpdir = tempfile.mkdtemp(prefix="e2e-all-")
    try:
        sub_dir = create_mock_submission(tmpdir, DIAG_SCRIPT)

        fixture_out = os.path.join(tmpdir, "fixtures")
        from common import FixtureContext

        families = [
            "file_tree", "go_multistage", "python_pip_pyc", "node_npm",
            "debian_apt", "internal_archive", "mixed_multistage", "pinned_network",
            "diagnosis"
        ]

        for family in families:
            fdir = os.path.join(fixture_out, family)
            ctx = FixtureContext("e2e-all", family, fdir)
            mod = __import__(family)
            mod.generate(ctx)

            # Remove smoke tests
            for root, dirs, files in os.walk(fdir):
                for f in files:
                    if f == "test_container.sh":
                        os.remove(os.path.join(root, f))

        # Test each fixture
        for family in families:
            fdir = os.path.join(fixture_out, family)
            result = run_fixture(family, fdir, os.path.join(sub_dir, "repro-docker"))
            test(f"  {family}", result["status"] == "PASS", result.get("reason", ""))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    print("=== End-to-End Harness Validation ===\n")

    print("[1] Basic reproducible fixture")
    test_basic_reproducible_fixture()

    print("\n[2] Mutation detection")
    test_mutation_detection()

    print("\n[3] Real file_tree A/B/C (no smoke)")
    test_real_file_tree_abc()

    print("\n[4] Diagnosis fixture")
    test_diagnosis_fixture()

    print("\n[5] Diagnosis with multiple seeds")
    test_diagnosis_multiple_seeds()

    print("\n[6] All 9 fixtures (no smoke)")
    test_all_fixtures_no_smoke()

    print(f"\n=== Results: {PASSED} passed, {FAILED} failed ===")
    sys.exit(0 if FAILED == 0 else 1)

#!/usr/bin/env python3
"""
Main benchmark runner. Orchestrates all fixture builds and validates results.
Exit 0 only if ALL fixtures pass (all-or-nothing).
"""

import argparse
import os
import sys
import time

from run_fixture import run_fixture


FIXTURE_FAMILIES = [
    "file_tree",
    "go_multistage",
    "python_pip_pyc",
    "node_npm",
    "debian_apt",
    "internal_archive",
    "mixed_multistage",
    "pinned_network",
    "diagnosis",
]


def main():
    parser = argparse.ArgumentParser(description="Reproducible Docker Benchmark Runner")
    parser.add_argument(
        "--submission", required=True, help="Path to submission directory"
    )
    parser.add_argument("--fixtures", required=True, help="Path to generated fixtures")
    parser.add_argument("--seed", default="20260526", help="Generation seed")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    submission_bin = os.path.join(os.path.abspath(args.submission), "repro-docker")
    if not os.path.isfile(submission_bin):
        print(f"FATAL: submission binary not found: {submission_bin}", file=sys.stderr)
        sys.exit(1)
    if not os.access(submission_bin, os.X_OK):
        print(
            f"FATAL: submission binary not executable: {submission_bin}",
            file=sys.stderr,
        )
        sys.exit(1)

    fixtures_dir = os.path.abspath(args.fixtures)
    if not os.path.isdir(fixtures_dir):
        print(f"FATAL: fixtures directory not found: {fixtures_dir}", file=sys.stderr)
        sys.exit(1)

    results = {}
    all_passed = True
    total_start = time.time()

    for family in FIXTURE_FAMILIES:
        fixture_dir = os.path.join(fixtures_dir, family)
        if not os.path.isdir(fixture_dir):
            print(f"FAIL: fixture directory missing: {fixture_dir}")
            results[family] = {"status": "MISSING"}
            all_passed = False
            continue

        print(f"\n{'=' * 60}")
        print(f"FIXTURE: {family}")
        print(f"{'=' * 60}")

        start = time.time()
        try:
            result = run_fixture(
                family=family,
                fixture_dir=fixture_dir,
                submission_bin=submission_bin,
                verbose=args.verbose,
            )
            elapsed = time.time() - start
            result["elapsed_seconds"] = round(elapsed, 2)
            results[family] = result

            if result["status"] == "PASS":
                print(f"  PASS ({elapsed:.1f}s)")
            else:
                print(f"  FAIL: {result.get('reason', 'unknown')}")
                all_passed = False
        except Exception as e:
            elapsed = time.time() - start
            results[family] = {
                "status": "ERROR",
                "reason": str(e),
                "elapsed_seconds": round(elapsed, 2),
            }
            print(f"  ERROR: {e}")
            all_passed = False

    total_elapsed = time.time() - total_start

    print(f"\n{'=' * 60}")
    print(f"SUMMARY (seed={args.seed}, elapsed={total_elapsed:.1f}s)")
    print(f"{'=' * 60}")

    for family in FIXTURE_FAMILIES:
        r = results.get(family, {"status": "MISSING"})
        status = r["status"]
        elapsed = r.get("elapsed_seconds", 0)
        marker = "PASS" if status == "PASS" else "FAIL"
        print(f"  [{marker}] {family} ({elapsed:.1f}s)")
        if status != "PASS" and "reason" in r:
            print(f"         {r['reason']}")

    passed_count = sum(1 for r in results.values() if r["status"] == "PASS")
    total_count = len(FIXTURE_FAMILIES)

    print(f"\nResult: {passed_count}/{total_count} fixtures passed")

    if all_passed:
        print("\nBENCHMARK PASSED")
        sys.exit(0)
    else:
        print("\nBENCHMARK FAILED (all-or-nothing)")
        sys.exit(1)


if __name__ == "__main__":
    main()

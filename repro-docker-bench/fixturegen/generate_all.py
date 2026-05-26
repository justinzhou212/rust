#!/usr/bin/env python3
"""
Master fixture generator. Generates one concrete instance of each fixture
family using the provided seed.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import FixtureContext
from families.file_tree import generate as gen_file_tree
from families.go_multistage import generate as gen_go_multistage
from families.python_pip_pyc import generate as gen_python_pip_pyc
from families.node_npm import generate as gen_node_npm
from families.debian_apt import generate as gen_debian_apt
from families.internal_archive import generate as gen_internal_archive
from families.mixed_multistage import generate as gen_mixed_multistage
from families.pinned_network import generate as gen_pinned_network
from families.diagnosis import generate as gen_diagnosis


GENERATORS = {
    "file_tree": gen_file_tree,
    "go_multistage": gen_go_multistage,
    "python_pip_pyc": gen_python_pip_pyc,
    "node_npm": gen_node_npm,
    "debian_apt": gen_debian_apt,
    "internal_archive": gen_internal_archive,
    "mixed_multistage": gen_mixed_multistage,
    "pinned_network": gen_pinned_network,
    "diagnosis": gen_diagnosis,
}


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark fixtures")
    parser.add_argument("--seed", required=True, help="Generation seed")
    parser.add_argument("--out", required=True, help="Output directory for fixtures")
    parser.add_argument(
        "--family", default=None, help="Generate only specific family (optional)"
    )
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    families = [args.family] if args.family else list(GENERATORS.keys())

    for family in families:
        if family not in GENERATORS:
            print(f"ERROR: unknown family '{family}'", file=sys.stderr)
            sys.exit(1)

        print(f"Generating fixture: {family}")
        fixture_dir = os.path.join(args.out, family)
        os.makedirs(fixture_dir, exist_ok=True)

        ctx = FixtureContext(
            seed=args.seed,
            family=family,
            output_dir=fixture_dir,
        )

        try:
            GENERATORS[family](ctx)
            print(f"  -> {fixture_dir}")
        except Exception as e:
            print(f"  ERROR generating {family}: {e}", file=sys.stderr)
            raise

    print(f"\nGenerated {len(families)} fixtures in {args.out}")


if __name__ == "__main__":
    main()

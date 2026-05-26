"""
Build environment simulation.
Creates isolated build environments with different paths, hostnames,
timezones, locales, umasks, HOME, TMPDIR, file mtimes, and creation order.
"""

import hashlib
import os
import random
import shutil


ENV_A = {
    "name": "A",
    "base_path": "/work/a",
    "hostname": "alpha-builder",
    "timezone": "UTC",
    "locale": "C.UTF-8",
    "umask": 0o022,
    "home": "/home/builder-a",
    "tmpdir": "/tmp/a",
}

ENV_B = {
    "name": "B",
    "base_path": "/tmp/b",
    "hostname": "beta-builder",
    "timezone": "Pacific/Kiritimati",
    "locale": "en_US.UTF-8",
    "umask": 0o077,
    "home": "/home/builder-b",
    "tmpdir": "/var/tmp/b",
}

ENV_C = {
    "name": "C",
    "base_path": "/workspace/c",
    "hostname": "gamma-builder",
    "timezone": "America/Los_Angeles",
    "locale": "C.UTF-8",
    "umask": 0o027,
    "home": "/home/builder-c",
    "tmpdir": "/tmp/c",
}


def create_build_environment(source_dir, work_dir, env_config, metadata):
    """
    Copy source into an environment-specific directory structure with
    randomized file metadata based on the environment config.

    Returns the path to the context directory within the environment.
    """
    env_name = env_config["name"]
    seed_str = f"{env_name}-{metadata.get('seed', '0')}"
    rng = random.Random(hashlib.sha256(seed_str.encode()).hexdigest())

    # Create project directory with random suffix
    project_suffix = hashlib.md5(seed_str.encode()).hexdigest()[:6]
    project_name = f"project-{project_suffix}"
    context_path = os.path.join(work_dir, "context", project_name)

    # Copy source tree
    shutil.copytree(source_dir, context_path, symlinks=True)

    # Randomize file mtimes for environments A and B
    # (C uses source as-is since it's mutated content that matters)
    if env_name in ("A", "B"):
        _randomize_mtimes(context_path, rng)

    # Write environment metadata for the build tool to discover
    env_file = os.path.join(work_dir, "env.json")
    import json

    with open(env_file, "w") as f:
        json.dump(
            {
                "hostname": env_config["hostname"],
                "timezone": env_config["timezone"],
                "locale": env_config["locale"],
                "umask": oct(env_config["umask"]),
                "home": env_config["home"],
                "tmpdir": env_config["tmpdir"],
                "source_path": context_path,
            },
            f,
            indent=2,
        )

    return context_path


def _randomize_mtimes(directory, rng):
    """Set random modification times on all files in directory."""
    # Use a range of timestamps that are clearly not "now"
    base_time = 1600000000  # Sep 2020
    range_seconds = 100000000  # ~3 years

    for root, dirs, files in os.walk(directory):
        for name in files + dirs:
            path = os.path.join(root, name)
            if os.path.islink(path):
                continue
            mtime = base_time + rng.randint(0, range_seconds)
            atime = mtime + rng.randint(0, 86400)
            try:
                os.utime(path, (atime, mtime))
            except OSError:
                pass


def get_env_exports(env_config):
    """Return environment variable dict for subprocess execution."""
    return {
        "HOSTNAME": env_config["hostname"],
        "TZ": env_config["timezone"],
        "LANG": env_config["locale"],
        "LC_ALL": env_config["locale"],
        "HOME": env_config["home"],
        "TMPDIR": env_config["tmpdir"],
    }

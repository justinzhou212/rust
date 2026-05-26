"""
Common utilities for fixture generation.
"""

import hashlib
import json
import os
import random
import string


class FixtureContext:
    """Context object passed to each fixture generator."""

    def __init__(self, seed, family, output_dir):
        self.seed = seed
        self.family = family
        self.output_dir = output_dir

        # Create deterministic RNG from seed + family
        combined = f"{seed}-{family}"
        hash_bytes = hashlib.sha256(combined.encode()).digest()
        self.rng = random.Random(int.from_bytes(hash_bytes[:8], "big"))

    def random_string(self, length=8, charset=None):
        """Generate a random string."""
        if charset is None:
            charset = string.ascii_lowercase + string.digits
        return "".join(self.rng.choices(charset, k=length))

    def random_hex(self, length=16):
        """Generate random hex string."""
        return "".join(self.rng.choices("0123456789abcdef", k=length))

    def random_int(self, low, high):
        """Generate random integer in range."""
        return self.rng.randint(low, high)

    def random_bytes(self, length):
        """Generate random bytes."""
        return bytes(self.rng.randint(0, 255) for _ in range(length))

    def random_choice(self, items):
        """Choose random item from list."""
        return self.rng.choice(items)

    def random_sample(self, items, k):
        """Choose k random items from list."""
        return self.rng.sample(items, min(k, len(items)))

    def random_shuffle(self, items):
        """Shuffle list in place using fixture RNG."""
        self.rng.shuffle(items)
        return items

    def make_context_dir(self):
        """Create and return the context/ subdirectory."""
        d = os.path.join(self.output_dir, "context")
        os.makedirs(d, exist_ok=True)
        return d

    def make_mutated_context_dir(self):
        """Create and return the mutated_context/ subdirectory."""
        d = os.path.join(self.output_dir, "mutated_context")
        os.makedirs(d, exist_ok=True)
        return d

    def write_metadata(self, metadata):
        """Write metadata.json to the fixture output directory."""
        metadata["seed"] = self.seed
        metadata["family"] = self.family
        path = os.path.join(self.output_dir, "metadata.json")
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2)

    def write_smoke_test(self, script_content):
        """Write test_container.sh to fixture output directory."""
        path = os.path.join(self.output_dir, "test_container.sh")
        with open(path, "w") as f:
            f.write(script_content)
        os.chmod(path, 0o755)

    def sha256_hex(self, data):
        """Compute sha256 hex digest of bytes or string."""
        if isinstance(data, str):
            data = data.encode()
        return hashlib.sha256(data).hexdigest()


def write_file(path, content, executable=False):
    """Write a file, creating parent directories as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode) as f:
        f.write(content)
    if executable:
        os.chmod(path, 0o755)


def write_json(path, data):
    """Write JSON to file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

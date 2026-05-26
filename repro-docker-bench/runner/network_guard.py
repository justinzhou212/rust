#!/usr/bin/env python3
"""
Network guard for build isolation.
Logs all network requests and blocks unauthorized hosts.
Provides DNS resolution for local fixture services only.
"""

import json
import os
import re
import sys
from datetime import datetime


ALLOWED_HOSTS_PATTERN = re.compile(r"^(apt|pypi|npm|payload)(\.[a-z0-9-]+)?\.local$")

DEFAULT_ALLOWED_PORTS = {80, 443, 8080, 8081, 8082, 8083}


class NetworkGuard:
    """Monitors and controls network access during builds."""

    def __init__(self, run_id, log_dir=None):
        self.run_id = run_id
        self.log_dir = log_dir or "/tmp/network-guard"
        self.requests = []
        self.violations = []
        os.makedirs(self.log_dir, exist_ok=True)

    def get_allowed_hosts(self):
        """Return the set of allowed hostnames for this run."""
        return {
            f"apt.{self.run_id}.local": "127.0.0.1",
            f"pypi.{self.run_id}.local": "127.0.0.1",
            f"npm.{self.run_id}.local": "127.0.0.1",
            f"payload.{self.run_id}.local": "127.0.0.1",
            "apt.local": "127.0.0.1",
            "pypi.local": "127.0.0.1",
            "npm.local": "127.0.0.1",
            "payload.local": "127.0.0.1",
        }

    def check_request(self, host, port=80, method="GET", path="/"):
        """
        Check if a network request is allowed.
        Returns (allowed: bool, reason: str).
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "host": host,
            "port": port,
            "method": method,
            "path": path,
        }

        allowed_hosts = self.get_allowed_hosts()

        if host in allowed_hosts:
            entry["allowed"] = True
            self.requests.append(entry)
            return True, "allowed"

        if ALLOWED_HOSTS_PATTERN.match(host):
            entry["allowed"] = True
            self.requests.append(entry)
            return True, "allowed (pattern match)"

        entry["allowed"] = False
        entry["reason"] = f"host '{host}' not in allowed list"
        self.requests.append(entry)
        self.violations.append(entry)
        return False, f"BLOCKED: host '{host}' not allowed"

    def generate_hosts_file(self):
        """Generate /etc/hosts entries for local services."""
        lines = ["127.0.0.1 localhost"]
        for host, ip in self.get_allowed_hosts().items():
            lines.append(f"{ip} {host}")
        return "\n".join(lines) + "\n"

    def generate_resolv_conf(self):
        """Generate resolv.conf that only resolves local services."""
        return "nameserver 127.0.0.1\noptions ndots:0\n"

    def generate_iptables_rules(self):
        """Generate iptables rules to block external network."""
        rules = [
            # Allow loopback
            "-A OUTPUT -o lo -j ACCEPT",
            "-A INPUT -i lo -j ACCEPT",
            # Allow established connections
            "-A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
            "-A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
            # Block everything else outbound
            "-A OUTPUT -j REJECT",
        ]
        return rules

    def has_violations(self):
        """Check if any network violations occurred."""
        return len(self.violations) > 0

    def get_log(self):
        """Return the full request log."""
        return self.requests

    def save_log(self):
        """Save request log to file."""
        log_file = os.path.join(self.log_dir, f"network-{self.run_id}.json")
        with open(log_file, "w") as f:
            json.dump(
                {
                    "run_id": self.run_id,
                    "total_requests": len(self.requests),
                    "violations": len(self.violations),
                    "requests": self.requests,
                },
                f,
                indent=2,
            )
        return log_file

    def summary(self):
        """Return a summary string."""
        return (
            f"Network guard: {len(self.requests)} requests, "
            f"{len(self.violations)} violations"
        )


def create_network_namespace_script(run_id):
    """
    Generate a shell script that sets up network isolation.
    This creates a network namespace with only loopback and local services.
    """
    guard = NetworkGuard(run_id)
    hosts_content = guard.generate_hosts_file()

    script = f"""#!/bin/bash
set -e

# Create isolated network namespace
NETNS="repro-bench-{run_id}"
ip netns add "$NETNS" 2>/dev/null || true
ip netns exec "$NETNS" ip link set lo up

# Write restricted hosts file
mkdir -p /tmp/repro-bench-{run_id}
cat > /tmp/repro-bench-{run_id}/hosts << 'HOSTS'
{hosts_content}HOSTS

# Write restricted resolv.conf
cat > /tmp/repro-bench-{run_id}/resolv.conf << 'RESOLV'
nameserver 127.0.0.1
options ndots:0
RESOLV

echo "Network namespace $NETNS ready"
"""
    return script


if __name__ == "__main__":
    run_id = sys.argv[1] if len(sys.argv) > 1 else "test-run"
    guard = NetworkGuard(run_id)

    # Demo
    print(f"Allowed hosts: {list(guard.get_allowed_hosts().keys())}")
    print()

    # Test some requests
    tests = [
        ("apt.local", 80),
        ("pypi.local", 443),
        ("registry.npmjs.org", 443),
        ("google.com", 443),
        ("payload.local", 8080),
    ]

    for host, port in tests:
        allowed, reason = guard.check_request(host, port)
        status = "ALLOW" if allowed else "BLOCK"
        print(f"  [{status}] {host}:{port} - {reason}")

    print(f"\n{guard.summary()}")

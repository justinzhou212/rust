"""
Fixture family 4: Node/npm image with lockfile and build output.
Tests npm-specific behavior: lockfile fidelity, local npm registry,
lifecycle/build scripts, node_modules, cache/log residue, bundled output.
"""

import hashlib
import json
import os
import shutil

from common import FixtureContext, write_file


# Pinned Node image digest
NODE_DIGEST = "sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0"


def generate(ctx: FixtureContext):
    """Generate a Node/npm fixture."""
    context_dir = ctx.make_context_dir()

    # Generate unique parameters
    app_name = f"app-{ctx.random_string(6)}"
    api_prefix = f"/api/{ctx.random_string(4)}"
    secret_token = ctx.random_hex(24)
    port = ctx.random_int(3000, 9000)

    # Create package.json
    write_file(
        os.path.join(context_dir, "package.json"),
        json.dumps(
            {
                "name": app_name,
                "version": "1.0.0",
                "private": True,
                "scripts": {
                    "build": "node scripts/build.js",
                    "start": "node dist/server.js",
                    "self-test": "node dist/server.js --self-test",
                },
                "dependencies": {},
                "devDependencies": {},
            },
            indent=2,
        )
        + "\n",
    )

    # Create package-lock.json (minimal)
    write_file(
        os.path.join(context_dir, "package-lock.json"),
        json.dumps(
            {
                "name": app_name,
                "version": "1.0.0",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {
                    "": {
                        "name": app_name,
                        "version": "1.0.0",
                        "dependencies": {},
                        "devDependencies": {},
                    }
                },
            },
            indent=2,
        )
        + "\n",
    )

    # Create source files
    os.makedirs(os.path.join(context_dir, "src"), exist_ok=True)
    os.makedirs(os.path.join(context_dir, "public"), exist_ok=True)
    os.makedirs(os.path.join(context_dir, "scripts"), exist_ok=True)

    # Server source
    write_file(
        os.path.join(context_dir, "src", "server.js"),
        f"""'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const SECRET = '{secret_token}';
const API_PREFIX = '{api_prefix}';
const PORT = {port};

function computeHash(input) {{
  return crypto.createHash('sha256')
    .update(input)
    .update(SECRET)
    .digest('hex');
}}

function handleRequest(req, res) {{
  if (req.url === API_PREFIX + '/hash' && req.method === 'GET') {{
    const url = new URL(req.url, `http://${{req.headers.host}}`);
    const input = url.searchParams.get('input') || 'default';
    const hash = computeHash(input);
    res.writeHead(200, {{'Content-Type': 'application/json'}});
    res.end(JSON.stringify({{ hash, input }}));
    return;
  }}

  if (req.url === '/health') {{
    res.writeHead(200);
    res.end('ok');
    return;
  }}

  // Serve static files
  const staticDir = path.join(__dirname, '..', 'public');
  const filePath = path.join(staticDir, req.url === '/' ? 'index.html' : req.url);
  if (fs.existsSync(filePath)) {{
    res.writeHead(200);
    res.end(fs.readFileSync(filePath));
    return;
  }}

  res.writeHead(404);
  res.end('Not found');
}}

// Self-test mode
if (process.argv.includes('--self-test')) {{
  const testInput = 'self-test-input';
  const expected = computeHash(testInput);
  console.log(`hash=${{expected}}`);
  console.log('PASS: node self-test');
  process.exit(0);
}}

const server = http.createServer(handleRequest);
server.listen(PORT, () => {{
  console.log(`Server listening on port ${{PORT}}`);
}});
""",
    )

    # Public assets
    index_content = f"""<!DOCTYPE html>
<html>
<head><title>{app_name}</title></head>
<body>
<h1>{app_name}</h1>
<p>Version: 1.0.0</p>
<p>Token: {ctx.random_hex(8)}</p>
</body>
</html>
"""
    write_file(os.path.join(context_dir, "public", "index.html"), index_content)

    # Build script
    write_file(
        os.path.join(context_dir, "scripts", "build.js"),
        """'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const srcDir = path.join(__dirname, '..', 'src');
const distDir = path.join(__dirname, '..', 'dist');
const publicDir = path.join(__dirname, '..', 'public');

// Create dist directory
fs.mkdirSync(distDir, { recursive: true });

// Copy source to dist
const files = fs.readdirSync(srcDir);
for (const file of files) {
  fs.copyFileSync(path.join(srcDir, file), path.join(distDir, file));
}

// Copy public to dist/public
const distPublic = path.join(distDir, '..', 'public');
fs.mkdirSync(distPublic, { recursive: true });
const publicFiles = fs.readdirSync(publicDir);
for (const file of publicFiles) {
  fs.copyFileSync(path.join(publicDir, file), path.join(distPublic, file));
}

// Generate asset manifest
const manifest = {};
for (const file of publicFiles) {
  const content = fs.readFileSync(path.join(publicDir, file));
  manifest[file] = crypto.createHash('sha256').update(content).digest('hex');
}
fs.writeFileSync(
  path.join(distDir, 'manifest.json'),
  JSON.stringify(manifest, null, 2) + '\\n'
);

console.log(`Built ${files.length} source files, ${publicFiles.length} public assets`);
""",
    )

    # Dockerfile
    write_file(
        os.path.join(context_dir, "Dockerfile"),
        f"""FROM node@{NODE_DIGEST}
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci 2>/dev/null || npm install

COPY src src
COPY public public
COPY scripts scripts
RUN npm run build

CMD ["node", "dist/server.js", "--self-test"]
""",
    )

    # Create mutated context
    mutated_dir = ctx.make_mutated_context_dir()
    shutil.copytree(context_dir, mutated_dir, dirs_exist_ok=True)

    # Mutate: change secret token (changes hash output)
    mutated_token = ctx.random_hex(24)
    mutated_server = os.path.join(mutated_dir, "src", "server.js")
    with open(mutated_server) as f:
        content = f.read()
    content = content.replace(secret_token, mutated_token)
    with open(mutated_server, "w") as f:
        f.write(content)

    # Compute expected outputs
    h1 = hashlib.sha256()
    h1.update(b"self-test-input")
    h1.update(secret_token.encode())
    expected_hash = h1.hexdigest()

    h2 = hashlib.sha256()
    h2.update(b"self-test-input")
    h2.update(mutated_token.encode())
    mutated_expected = h2.hexdigest()

    ctx.write_metadata(
        {
            "type": "reproducible",
            "family": "node_npm",
            "expected_output": "PASS: node self-test",
            "expected_output_mutated": "PASS: node self-test",
            "expected_hash": expected_hash,
            "mutated_hash": mutated_expected,
            "app_name": app_name,
            "required_rootfs_paths": [
                "/app/dist/server.js",
                "/app/dist/manifest.json",
            ],
        }
    )

    ctx.write_smoke_test("""#!/bin/bash
set -e
IMAGE="$1"

if [ -n "$ROOTFS_DIR" ]; then
    test -f "$ROOTFS_DIR/app/dist/server.js" || { echo "FAIL: /app/dist/server.js missing"; exit 1; }
    test -f "$ROOTFS_DIR/app/dist/manifest.json" || { echo "FAIL: /app/dist/manifest.json missing"; exit 1; }
    cd "$ROOTFS_DIR/app"
    node dist/server.js --self-test
    exit 0
fi

if [ -n "$IMAGE" ] && command -v docker >/dev/null 2>&1; then
    OUTPUT=$(docker run --rm "$IMAGE")
    echo "$OUTPUT"
    echo "$OUTPUT" | grep -q "PASS" || { echo "FAIL: container output missing PASS"; exit 1; }
    exit 0
fi

echo "FAIL: no container runtime or rootfs available"
exit 1
""")

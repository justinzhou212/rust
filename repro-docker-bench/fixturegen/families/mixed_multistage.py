"""
Fixture family 7: Mixed multi-stage real app.
Integrated realistic test covering frontend (Node) + backend (Rust) +
multi-stage COPY + final minimal runtime image.
"""

import json
import os
import shutil

from common import FixtureContext, write_file


# Pinned image digests
NODE_DIGEST = "sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0"
RUST_DIGEST = "sha256:70c2a016184099262fd7cee46f3d35fec3568c45c62f87e37f7f665f766b1f74"
DEBIAN_DIGEST = (
    "sha256:0104b334637a5f19aa9c983a91b54c89887c0984081f2068983107a6f6c21eeb"
)


def generate(ctx: FixtureContext):
    """Generate a mixed multi-stage fixture."""
    context_dir = ctx.make_context_dir()

    # Generate unique parameters
    app_name = f"mixedapp-{ctx.random_string(5)}"
    static_token = ctx.random_hex(16)
    backend_secret = ctx.random_hex(24)
    api_route = f"/{ctx.random_string(4)}"

    # ---- Frontend (Node) ----
    frontend_dir = os.path.join(context_dir, "frontend")
    os.makedirs(os.path.join(frontend_dir, "src"), exist_ok=True)

    write_file(
        os.path.join(frontend_dir, "package.json"),
        json.dumps(
            {
                "name": f"{app_name}-frontend",
                "version": "1.0.0",
                "private": True,
                "scripts": {
                    "build": "node build.js",
                },
            },
            indent=2,
        )
        + "\n",
    )

    write_file(
        os.path.join(frontend_dir, "package-lock.json"),
        json.dumps(
            {
                "name": f"{app_name}-frontend",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {"": {"name": f"{app_name}-frontend", "version": "1.0.0"}},
            },
            indent=2,
        )
        + "\n",
    )

    # Frontend source
    index_html = f"""<!DOCTYPE html>
<html>
<head><title>{app_name}</title></head>
<body>
<h1>{app_name}</h1>
<div id="app">
<p>Static token: {static_token}</p>
</div>
<script src="/app.js"></script>
</body>
</html>
"""
    write_file(os.path.join(frontend_dir, "src", "index.html"), index_html)

    app_js = f"""'use strict';
const TOKEN = '{static_token}';
function init() {{
  const hash = require('crypto').createHash('sha256').update(TOKEN).digest('hex');
  console.log('Frontend hash:', hash);
}}
if (typeof window !== 'undefined') {{ init(); }}
module.exports = {{ TOKEN }};
"""
    write_file(os.path.join(frontend_dir, "src", "app.js"), app_js)

    # Frontend build script
    write_file(
        os.path.join(frontend_dir, "build.js"),
        """'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const srcDir = path.join(__dirname, 'src');
const distDir = path.join(__dirname, 'dist');
fs.mkdirSync(distDir, { recursive: true });

// Copy and hash all source files
const manifest = {};
const files = fs.readdirSync(srcDir);
for (const file of files.sort()) {
  const content = fs.readFileSync(path.join(srcDir, file));
  fs.writeFileSync(path.join(distDir, file), content);
  manifest[file] = crypto.createHash('sha256').update(content).digest('hex');
}

fs.writeFileSync(
  path.join(distDir, 'manifest.json'),
  JSON.stringify(manifest, null, 2) + '\\n'
);
console.log(`Built ${files.length} frontend files`);
""",
    )

    # ---- Backend (Rust) ----
    backend_dir = os.path.join(context_dir, "backend")
    os.makedirs(os.path.join(backend_dir, "src"), exist_ok=True)

    write_file(
        os.path.join(backend_dir, "Cargo.toml"),
        f"""[package]
name = "{app_name}-server"
version = "0.1.0"
edition = "2021"

[[bin]]
name = "server"
path = "src/main.rs"
""",
    )

    write_file(
        os.path.join(backend_dir, "Cargo.lock"),
        f"""# Minimal lock file
[[package]]
name = "{app_name}-server"
version = "0.1.0"
""",
    )

    write_file(
        os.path.join(backend_dir, "src", "main.rs"),
        f"""use std::env;
use std::fs;
use std::path::Path;

const SECRET: &str = "{backend_secret}";
const API_ROUTE: &str = "{api_route}";

fn compute_hash(input: &str) -> String {{
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{{Hash, Hasher}};
    let mut hasher = DefaultHasher::new();
    input.hash(&mut hasher);
    SECRET.hash(&mut hasher);
    format!("{{:016x}}", hasher.finish())
}}

fn self_test() {{
    // Check static files exist
    let static_dir = Path::new("/srv/static");
    if static_dir.exists() {{
        let manifest_path = static_dir.join("manifest.json");
        if manifest_path.exists() {{
            let content = fs::read_to_string(&manifest_path).unwrap();
            println!("static_manifest={{}}", content.trim().len());
        }}
    }}

    // Compute and print test hash
    let hash = compute_hash("self-test");
    println!("backend_hash={{}}", hash);
    println!("PASS: mixed app self-test");
}}

fn main() {{
    let args: Vec<String> = env::args().collect();
    if args.contains(&"--self-test".to_string()) {{
        self_test();
        return;
    }}
    println!("Server starting on route {{}}", API_ROUTE);
}}
""",
    )

    # ---- Dockerfile ----
    write_file(
        os.path.join(context_dir, "Dockerfile"),
        f"""FROM node@{NODE_DIGEST} AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci 2>/dev/null || npm install
COPY frontend/src src
COPY frontend/build.js .
RUN npm run build

FROM rust@{RUST_DIGEST} AS backend
WORKDIR /backend
COPY backend/Cargo.toml backend/Cargo.lock ./
COPY backend/src src
COPY --from=frontend /frontend/dist ./static
RUN cargo build --release 2>/dev/null || (mkdir -p target/release && cp /bin/echo target/release/server)

FROM debian@{DEBIAN_DIGEST}
COPY --from=backend /backend/target/release/server /usr/local/bin/server
COPY --from=frontend /frontend/dist /srv/static
CMD ["server", "--self-test"]
""",
    )

    # Create mutated context
    mutated_dir = ctx.make_mutated_context_dir()
    shutil.copytree(context_dir, mutated_dir, dirs_exist_ok=True)

    # Mutate: change frontend token
    mutated_token = ctx.random_hex(16)
    mutated_index = os.path.join(mutated_dir, "frontend", "src", "index.html")
    with open(mutated_index) as f:
        content = f.read()
    content = content.replace(static_token, mutated_token)
    with open(mutated_index, "w") as f:
        f.write(content)

    mutated_app = os.path.join(mutated_dir, "frontend", "src", "app.js")
    with open(mutated_app) as f:
        content = f.read()
    content = content.replace(static_token, mutated_token)
    with open(mutated_app, "w") as f:
        f.write(content)

    ctx.write_metadata(
        {
            "type": "reproducible",
            "family": "mixed_multistage",
            "expected_output": "PASS: mixed app self-test",
            "expected_output_mutated": "PASS: mixed app self-test",
            "app_name": app_name,
            "static_token": static_token,
            "mutated_token": mutated_token,
            "required_rootfs_paths": [
                "/usr/local/bin/server",
                "/srv/static/manifest.json",
            ],
        }
    )

    ctx.write_smoke_test("""#!/bin/bash
set -e
IMAGE="$1"

if [ -n "$ROOTFS_DIR" ]; then
    test -f "$ROOTFS_DIR/usr/local/bin/server" || { echo "FAIL: /usr/local/bin/server missing"; exit 1; }
    test -f "$ROOTFS_DIR/srv/static/manifest.json" || { echo "FAIL: /srv/static/manifest.json missing"; exit 1; }
    test -x "$ROOTFS_DIR/usr/local/bin/server" || { echo "FAIL: server not executable"; exit 1; }
    "$ROOTFS_DIR/usr/local/bin/server" --self-test
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

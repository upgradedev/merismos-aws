"""Publish a tested Vite build to the independently provisioned AWS frontend.

Uses the AWS CLI's current scoped identity. Never deletes an object. Every release
is archived by commit; index.html is uploaded last, after all referenced assets.
Restore by downloading releases/<commit>/ from the bucket and publishing that
directory with the SAME commit. S3 versioning keeps replaced objects recoverable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import subprocess
import tempfile
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
SUFFIXES = {".html", ".json", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".ico", ".webp", ".woff", ".woff2", ".txt"}
SECRET = re.compile(rb"AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def aws(*args):
    result = subprocess.run(["aws", *args, "--no-cli-pager"], check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else {}


def build_release(directory, sha):
    if not SHA.fullmatch(sha):
        raise ValueError("a full lowercase Git commit SHA is required")
    directory = Path(directory).resolve(strict=True)
    if not (directory / "index.html").is_file():
        raise ValueError("Vite dist/index.html is missing")
    payloads = {}
    for file in sorted(directory.rglob("*")):
        if file.is_symlink():
            raise ValueError("symlinks are not release artifacts")
        if not file.is_file():
            continue
        key = file.relative_to(directory).as_posix()
        if file.suffix.lower() not in SUFFIXES or any(p.startswith(".") for p in Path(key).parts):
            raise ValueError(f"unexpected public artifact: {key}")
        data = file.read_bytes()
        if SECRET.search(data):
            raise ValueError(f"credential-shaped content in {key}")
        if key == "index.html":
            html = data.decode("utf-8")
            marker = f'<meta name="application-commit" content="{sha}">'
            html = re.sub(r'<meta name="application-commit" content="[0-9a-f]{40}">', "", html)
            if "</head>" not in html:
                raise ValueError("index has no closing head")
            data = html.replace("</head>", marker + "</head>", 1).encode("utf-8")
        if key != "release.json":
            payloads[key] = data
    index = payloads["index.html"].decode()
    assets = re.findall(r'(?:src|href)=["\'](/assets/[^"\']+)["\']', index)
    if not assets:
        raise ValueError("index references no built Vite assets")
    for asset in assets:
        if asset.lstrip("/") not in payloads:
            raise ValueError(f"missing referenced asset: {asset}")
    manifest = {"commit": sha, "files": {
        key: hashlib.sha256(value).hexdigest() for key, value in sorted(payloads.items())
    }}
    payloads["release.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return payloads


def publish(directory, sha, stack, region, command=aws):
    # CloudFormation outputs resolve the exact target. No caller-supplied bucket,
    # wildcard sync, or --delete is accepted.
    reply = command("cloudformation", "describe-stacks", "--stack-name", stack, "--region", region)
    outputs = {item["OutputKey"]: item["OutputValue"] for item in reply["Stacks"][0]["Outputs"]}
    bucket, distribution = outputs["FrontendBucket"], outputs["DistributionId"]
    if not re.fullmatch(r"(lasttake|merismos|archon)-web-[0-9]{12}-[a-z0-9-]+", bucket):
        raise ValueError("stack output is not a portfolio frontend bucket")
    payloads = build_release(directory, sha)
    with tempfile.TemporaryDirectory(prefix="frontend-release-") as tmp:
        ordered = sorted(payloads, key=lambda key: (key == "index.html", key))
        for key in ordered:
            path = Path(tmp) / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payloads[key])
            media_type = {".js": "text/javascript", ".svg": "image/svg+xml"}.get(
                path.suffix, mimetypes.guess_type(key)[0] or "application/octet-stream"
            )
            cache = "public,max-age=31536000,immutable" if key.startswith("assets/") else "no-store,max-age=0"
            for target in (f"releases/{sha}/{key}", key):
                command("s3api", "put-object", "--bucket", bucket, "--key", target,
                        "--body", str(path), "--content-type", media_type,
                        "--cache-control", cache, "--region", region)
        result = command("cloudfront", "create-invalidation", "--distribution-id", distribution,
                         "--paths", "/", "/index.html", "/release.json")
    return {"url": outputs["FrontendUrl"], "commit": sha, "files": len(payloads),
            "invalidation": result.get("Invalidation", {}).get("Id")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default="frontend/dist")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--stack", required=True, choices=["lasttake-frontend", "merismos-frontend", "archon-frontend"])
    parser.add_argument("--region", default="eu-west-1")
    args = parser.parse_args()
    print(json.dumps(publish(args.dist, args.sha, args.stack, args.region), indent=2))

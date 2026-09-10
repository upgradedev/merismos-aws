"""Package the exact CI checkout's committed backend, with no AWS access."""
from __future__ import annotations

import json
import os
import re
import subprocess
import zipfile
from pathlib import Path


def package(root, env):
    root = Path(root).resolve()

    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True).stdout

    head = git("rev-parse", "HEAD").decode().strip()
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_SHA") != head
            or not re.fullmatch(r"[0-9a-f]{40}", head) or head == "0" * 40):
        raise ValueError("CI revision must equal the checked-out full commit")
    if git("status", "--porcelain", "--untracked-files=normal", "--", "src"):
        raise ValueError("Backend source has uncommitted changes")
    paths = git("ls-tree", "-rz", "--name-only", "HEAD", "src/merismos").decode().split("\0")
    payloads = {}
    for name in filter(None, paths):
        path = Path(name).relative_to("src")
        if path.name == "build-info.json" or "__pycache__" in path.parts or path.suffix == ".pyc":
            raise ValueError("Generated files must not be committed in backend source")
        payloads[path.as_posix()] = git("show", f"HEAD:{name}")
    if "merismos/handler.py" not in payloads or "merismos/version.py" not in payloads:
        raise ValueError("Backend entry point or version reader missing")
    metadata = {"schema_version": 1, "application": "merismos", "commit": head}
    payloads["merismos/build-info.json"] = (json.dumps(metadata, sort_keys=True) + "\n").encode()
    build = root / "infra/.build"
    # Exclusive creation prevents stale files from a previous package entering the archive.
    source = build / "source"
    source.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(build / "backend.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(payloads.items()):
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return metadata


if __name__ == "__main__":
    print(json.dumps(package(Path(__file__).resolve().parents[1], os.environ)))

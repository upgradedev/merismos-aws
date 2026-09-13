"""Package the exact CI checkout's committed backend, with no AWS access."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
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


def zip_layer(build):
    """Zip build/python into build/deps.zip so identical packages always hash the same.

    zip(1) stored each file's modification time and the order the filesystem listed
    it, so two installs of the same packages hashed differently, the plan replaced
    the layer on every apply, and all four functions were updated with it. Sorted
    names, one fixed timestamp and two permission modes make the archive a function
    of the package bytes alone. Returns the hash in Terraform's filebase64sha256 form.
    """
    build = Path(build)
    files = sorted((path for path in (build / "python").rglob("*") if path.is_file()),
                   key=lambda path: path.relative_to(build).as_posix())
    archive_path = build / "deps.zip"
    # Exclusive creation, as for the backend: a stale archive is never appended to.
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(build).as_posix(),
                                   date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.stat().st_mode & 0o111 else 0o644) << 16
            archive.writestr(info, path.read_bytes())
    return base64.b64encode(hashlib.sha256(archive_path.read_bytes()).digest()).decode()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--layer"]:
        print(zip_layer(sys.argv[2]))
    else:
        print(json.dumps(package(Path(__file__).resolve().parents[1], os.environ)))

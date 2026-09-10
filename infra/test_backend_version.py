"""CI-only functional packaging and negative runtime identity controls."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import backend_version as version
import package_backend

COMMIT = "1234567890abcdef1234567890abcdef12345678"
OTHER = "abcdef1234567890abcdef1234567890abcdef12"
HEADERS = {"Content-Type": "application/json; charset=utf-8"}


def payload(commit=COMMIT):
    return {"schema_version": 1, "application": "merismos", "commit": commit,
            "status": "known", "source": "ci_package"}


class Observation(unittest.TestCase):
    def test_only_the_version_route_is_requested_and_no_redirect_is_followed(self):
        calls = []
        def request(url):
            calls.append(url)
            return 200, HEADERS, json.dumps(payload()).encode()
        self.assertEqual(version.observe("https://example.invalid/", request)["commit"], COMMIT)
        self.assertEqual(calls, ["https://example.invalid/api/version"])
        self.assertIsNone(version.NoRedirect().redirect_request(None, None, 302, "Found", {}, "/identity"))
        for code in (301, 302, 307, 308, 500, 503):
            with self.subTest(code=code), self.assertRaises(ValueError):
                version.parse_version(code, {"Location": "/identity"}, b"")

    def test_old_backend_is_unknown_and_never_source_head(self):
        with patch.dict(os.environ, {"GITHUB_SHA": COMMIT, "MERISMOS_BUILD_SHA": COMMIT}):
            for code in (400, 403, 404, 405):
                self.assertEqual(version.parse_version(code, {}, b"old route"), version.UNKNOWN)
            unknown = {"schema_version": 1, "application": "merismos", **version.UNKNOWN}
            self.assertEqual(version.parse_version(200, HEADERS, json.dumps(unknown).encode()), version.UNKNOWN)

    def test_fake_malformed_and_extra_fields_fail_closed(self):
        for value in (None, [], {}, {**payload(), "commit": "fake"}, {**payload(), "commit": "0" * 40},
                      {**payload(), "source": "environment"}, {**payload(), "commit": COMMIT + "\n"},
                      {**payload(), "schema_version": True}, {**payload(), "application": "other"},
                      {**payload(), "status": "unknown"}, {**payload(), "arn": "private"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version.parse_version(200, HEADERS, json.dumps(value).encode())
        for data in (b"<html>SPA fallback</html>", b"x" * 4097, b'{}',
                     json.dumps(payload()).replace('"schema_version": 1', '"schema_version": 9, "schema_version": 1').encode()):
            with self.subTest(data=data[:100]), self.assertRaises(ValueError):
                version.parse_version(200, HEADERS, data)
        with self.assertRaises(ValueError):
            version.parse_version(200, {}, json.dumps(payload()).encode())

    def test_a_changed_or_disappearing_backend_cannot_be_receipted(self):
        known = {"commit": COMMIT, "status": "known", "source": "ci_package"}
        self.assertEqual(version.stable_backend(known, known), COMMIT)
        self.assertIsNone(version.stable_backend(version.UNKNOWN, version.UNKNOWN))
        for other in ({**known, "commit": OTHER}, version.UNKNOWN, {}, None, {**known, "source": "env"}):
            with self.subTest(other=other), self.assertRaises(ValueError):
                version.stable_backend(known, other)
        with self.assertRaises(ValueError):
            version.stable_backend(version.UNKNOWN, known)


class Package(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        package = self.root / "src/merismos"
        package.mkdir(parents=True)
        actual = Path(__file__).resolve().parents[1] / "src/merismos"
        for name in ("__init__.py", "handler.py", "version.py"):
            (package / name).write_bytes((actual / name).read_bytes())
        self.git("init")
        self.git("add", "src")
        self.git("-c", "core.hooksPath=/dev/null", "-c", "user.name=Fixture",
                 "-c", "user.email=fixture@example.invalid", "commit", "-m", "backend fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.env = {"GITHUB_ACTIONS": "true", "GITHUB_SHA": self.head}

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout

    def test_packaged_archive_imports_its_own_commit_despite_runtime_env_and_other_cwd(self):
        package_backend.package(self.root, self.env)
        archive = self.root / "infra/.build/backend.zip"
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(json.loads(bundle.read("merismos/build-info.json")),
                             {"schema_version": 1, "application": "merismos", "commit": self.head})
            self.assertEqual(bundle.read("merismos/handler.py"),
                             (self.root / "src/merismos/handler.py").read_bytes())
        result = subprocess.run([sys.executable, "-S", "-c",
                                 "import json; from merismos.version import build_version; print(json.dumps(build_version()))"],
                                env={**os.environ, "PYTHONPATH": str(archive), "GITHUB_SHA": OTHER,
                                     "MERISMOS_BUILD_SHA": OTHER}, cwd=self.root.parent,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["commit"], self.head)
        with self.assertRaises(FileExistsError):
            package_backend.package(self.root, self.env)

    def test_fake_missing_and_different_ci_revision_refused_before_output(self):
        for env in ({}, {**self.env, "GITHUB_ACTIONS": "false"}, {**self.env, "GITHUB_SHA": "fake"},
                    {**self.env, "GITHUB_SHA": OTHER}, {**self.env, "GITHUB_SHA": "0" * 40}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                package_backend.package(self.root, env)
            self.assertFalse((self.root / "infra/.build").exists())

    def test_modified_and_untracked_source_cannot_claim_the_committed_revision(self):
        path = self.root / "src/merismos/handler.py"
        path.write_text("different runtime")
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            package_backend.package(self.root, self.env)
        path.write_text(self.git("show", "HEAD:src/merismos/handler.py"))
        (path.parent / "build-info.json").write_text(json.dumps(payload(OTHER)))
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            package_backend.package(self.root, self.env)


if __name__ == "__main__":
    unittest.main(verbosity=2)

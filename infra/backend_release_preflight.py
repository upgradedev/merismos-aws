"""CI-only, read-only prerequisite for publishing a correlation-aware frontend.

Two bounded GETs to the fixed owned origin. No session, AWS credentials or writes.
This is an early release guard, not a replacement for post-publication Playwright.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from urllib.request import HTTPRedirectHandler, Request, build_opener

from backend_version import parse_version

ORIGIN = "https://d2qnkmlhs7y5fp.cloudfront.net"
VERSION_URL = ORIGIN + "/api/version"
RUNTIME_PATHS = ("src", "pyproject.toml", ".python-version", "requirements*", "uv.lock",
                 "infra/build.sh", "infra/package_backend.py")
SHA = re.compile(r"[a-f0-9]{40}")
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")
LAMBDA_ID = re.compile(r"[A-Za-z0-9-]{16,80}")
MAX_BYTES = 4096


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def fetch_version():
    request = Request(VERSION_URL, headers={"Cache-Control": "no-cache"}, method="GET")
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        require(response.geturl() == VERSION_URL, "Unexpected response origin or redirect")
        return response.status, response.headers, response.read(MAX_BYTES + 1)


def one_header(headers, name):
    values = headers.get_all(name) or []
    require(len(values) == 1 and isinstance(values[0], str), "Missing or repeated " + name)
    return values[0]


def decode_version(reply):
    status, headers, raw = reply
    require(status == 200, "Backend version endpoint is not healthy")
    require(0 < len(raw) <= MAX_BYTES, "Backend version body exceeds bounds or is empty")
    require(one_header(headers, "content-type").split(";", 1)[0].strip() ==
            "application/json", "Backend version must be JSON")
    require(one_header(headers, "x-merismos-correlation-mode") == "lambda-context",
            "Deployed backend lacks Lambda correlation capability")
    request_id = one_header(headers, "x-merismos-request-id")
    lambda_id = one_header(headers, "x-merismos-lambda-request-id")
    require(UUID.fullmatch(request_id) is not None, "Invalid server request ID")
    require(LAMBDA_ID.fullmatch(lambda_id) is not None, "Invalid Lambda request ID")
    # Same strict duplicate/schema/zero-SHA rules as post-publication acceptance.
    body = parse_version(status, dict(headers.items()), raw)
    require(body.get("status") == "known", "Unknown backend identity")
    commit = body.get("commit")
    require(isinstance(commit, str) and SHA.fullmatch(commit), "Invalid backend commit")
    return {"backend_commit": commit, "request_id": request_id, "lambda_request_id": lambda_id}


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, check=False)


def verify_source(candidate, backend, run_git=git):
    require(isinstance(candidate, str) and SHA.fullmatch(candidate), "Invalid frontend commit")
    head = run_git("rev-parse", "HEAD")
    require(head.returncode == 0 and head.stdout.strip() == candidate, "Checkout is not candidate")
    ancestry = run_git("merge-base", "--is-ancestor", backend, candidate)
    require(ancestry.returncode == 0, "Backend is unavailable or not candidate ancestry")
    diff = run_git("diff", "--exit-code", backend, candidate, "--", *RUNTIME_PATHS)
    require(diff.returncode == 0, "Deployed runtime source/dependencies differ from candidate")


def inspect(candidate, fetch=fetch_version, run_git=git):
    require(isinstance(candidate, str) and SHA.fullmatch(candidate), "Invalid frontend commit")
    rows = [decode_version(fetch()) for _ in range(2)]
    require(rows[0]["backend_commit"] == rows[1]["backend_commit"], "Backend changed during guard")
    for key in ("request_id", "lambda_request_id"):
        require(rows[0][key] != rows[1][key], "Repeated invocation identity: " + key)
    verify_source(candidate, rows[0]["backend_commit"], run_git)
    return {"schema": "merismos/release-backend-preflight/v1", "status": "PASSED",
            "frontend_commit": candidate, "observations": rows,
            "scope": "Two answering version requests and runtime-source/dependency parity only.",
            "limits": "Not fleet attestation, cloud cost, model value or live journey acceptance."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    require(os.environ.get("GITHUB_ACTIONS") == "true", "This release probe runs in CI only")
    print(json.dumps(inspect(args.sha), sort_keys=True))


if __name__ == "__main__":
    main()

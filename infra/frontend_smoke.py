"""Read-only checks of a deployed frontend, API routing, and exact release."""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request


def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "portfolio-release-check/1"}), timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def check(url, sha, request=fetch):
    url = url.rstrip("/") + "/"
    status, headers, body = request(url)
    assert status == 200, f"judge URL HTTP {status}"
    assert f'content="{sha}"'.encode() in body, "served HTML is not the release commit"
    lower = {key.lower(): value for key, value in headers.items()}
    assert "content-security-policy" in lower, "missing CSP"
    assert lower.get("x-content-type-options") == "nosniff"
    assert lower.get("x-frame-options") == "DENY"
    status, _, manifest = request(url + "release.json")
    assert status == 200 and json.loads(manifest)["commit"] == sha, "release metadata mismatch"
    assets = re.findall(rb'(?:src|href)=["\'](/assets/[^"\']+)["\']', body)
    assert assets, "no Vite assets in deployed HTML"
    for path in assets:
        asset_status, _, content = request(url.rstrip("/") + path.decode())
        assert asset_status == 200 and content, f"asset not reachable: {path!r}"
    status, _, missing = request(url + "assets/definitely-not-a-build-file.js")
    assert status in {403, 404} and b'application-commit' not in missing, "missing asset became SPA 200"
    status, _, missing = request(url + "api/definitely-not-a-route")
    assert status in {400, 404, 405} and b'application-commit' not in missing, "API errors became HTML success"
    return {"url": url, "commit": sha, "assets_checked": len(assets), "read_only": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.url, args.sha), indent=2))

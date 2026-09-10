"""Observe only the harmless backend version route, without redirects or AWS SDKs."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

UNKNOWN = {"commit": None, "status": "unknown", "source": "unknown"}
FIELDS = {"schema_version", "application", "commit", "status", "source"}


def valid_commit(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) and value != "0" * 40


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_version(url):
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read(4097)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), b""


def parse_version(status, headers, body):
    # Old deployments do not have this route. They stay explicitly unknown.
    if status in {400, 403, 404, 405}:
        return dict(UNKNOWN)
    if status != 200:
        raise ValueError("Backend version request failed or redirected")
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
    if content_type.split(";")[0].strip().lower() != "application/json" or len(body) > 4096:
        raise ValueError("Backend version is not bounded JSON")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate backend version field")
            result[key] = value
        return result
    value = json.loads(body, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != FIELDS
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["application"] != "merismos"):
        raise ValueError("Unexpected backend version schema")
    observed = {key: value[key] for key in UNKNOWN}
    if observed == UNKNOWN:
        return observed
    if not (valid_commit(value["commit"]) and value["status"] == "known" and value["source"] == "ci_package"):
        raise ValueError("Unsubstantiated backend version")
    return observed


def observe(url, request=fetch_version):
    return parse_version(*request(url.rstrip("/") + "/api/version"))


def stable_backend(before, after):
    for value in (before, after):
        if not isinstance(value, dict) or set(value) != set(UNKNOWN):
            raise ValueError("Backend observation missing")
        if value != UNKNOWN and not (valid_commit(value["commit"]) and value["status"] == "known"
                                     and value["source"] == "ci_package"):
            raise ValueError("Invalid backend observation")
    if before != after:
        raise ValueError("Backend identity changed during acceptance")
    return before["commit"]

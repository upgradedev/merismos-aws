"""Actual entry surfaces never probe AWS or trust a caller's version claim."""

import json
from unittest.mock import Mock

import pytest

from merismos import handler, version

COMMIT = "1234567890abcdef1234567890abcdef12345678"
OTHER = "abcdef1234567890abcdef1234567890abcdef12"


@pytest.fixture
def metadata(monkeypatch, tmp_path):
    path = tmp_path / "build-info.json"
    monkeypatch.setattr(version, "files", lambda name: tmp_path)
    return path


@pytest.mark.parametrize("path", ["/version", "/api/version", "/api/version/"])
@pytest.mark.parametrize("surface", ["http-v2", "rest-v1", "raw-path"])
@pytest.mark.parametrize("role", ["reader", "writer", "evaluator"])
def test_version_on_actual_lambda_surfaces_is_read_only(monkeypatch, metadata, path, surface, role):
    metadata.write_text(json.dumps({"schema_version": 1, "application": "merismos", "commit": COMMIT}))
    monkeypatch.setenv("MERISMOS_ROLE", role)
    monkeypatch.setenv("MERISMOS_BUILD_SHA", OTHER)
    monkeypatch.setenv("GITHUB_SHA", OTHER)
    forbidden = Mock(side_effect=AssertionError("version reached a stateful dependency"))
    for name in ("boto3.client", "boto3.resource", "merismos.handler.identity",
                 "merismos.handler.corpus_from_env", "merismos.handler.ledger_from_env",
                 "merismos.handler._screens", "merismos.workspace_store.WorkspaceStore"):
        monkeypatch.setattr(name, forbidden)
    event = {"queryStringParameters": {"all": "1", "commit": OTHER, "mode": "live"}}
    if surface == "http-v2":
        event["requestContext"] = {"http": {"method": "GET", "path": path}}
    elif surface == "rest-v1":
        event.update(httpMethod="GET", path=path)
    else:
        event["rawPath"] = path
    response = handler.handler(event)
    assert response["statusCode"] == 200
    assert response["headers"]["cache-control"] == "no-store"
    assert response["headers"]["content-type"] == "application/json"
    assert json.loads(response["body"]) == {
        "schema_version": 1, "application": "merismos", "commit": COMMIT,
        "status": "known", "source": "ci_package"}
    forbidden.assert_not_called()


@pytest.mark.parametrize("raw", [None, "", "not-json", "[]", "null", '{"commit":"fake"}',
                                  '{"commit":"' + COMMIT + '"}', "x" * 1025,
                                  '{"schema_version":9,"schema_version":1,'
                                  '"application":"merismos","commit":"' + COMMIT + '"}'])
def test_missing_malformed_metadata_never_uses_environment(monkeypatch, metadata, raw):
    monkeypatch.setenv("MERISMOS_BUILD_SHA", COMMIT)
    monkeypatch.setenv("GITHUB_SHA", COMMIT)
    if raw is not None:
        metadata.write_text(raw)
    assert version.build_version() == {"schema_version": 1, "application": "merismos",
                                      "commit": None, "status": "unknown", "source": "unknown"}


@pytest.mark.parametrize("change", [
    {"commit": "fake"}, {"commit": "0" * 40}, {"commit": "a438849"}, {"commit": True},
    {"commit": COMMIT.upper()}, {"schema_version": True}, {"application": "other"},
    {"secret": "must never be exposed"}, {"commit": None}, {"commit": COMMIT + "\n"},
])
def test_invalid_or_extra_metadata_fields_return_only_unknown(metadata, change):
    metadata.write_text(json.dumps({"schema_version": 1, "application": "merismos",
                                    "commit": COMMIT, **change}))
    result = version.build_version()
    assert result["commit"] is None
    assert result["source"] == result["status"] == "unknown"
    assert "secret" not in str(result)


@pytest.mark.parametrize("path", ["/version", "/api/version"])
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def test_non_get_does_not_load_metadata_or_probe(monkeypatch, path, method):
    forbidden = Mock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(version, "build_version", forbidden)
    monkeypatch.setattr("boto3.client", forbidden)
    response = handler.handler({"httpMethod": method, "path": path})
    assert response["statusCode"] == 405
    forbidden.assert_not_called()

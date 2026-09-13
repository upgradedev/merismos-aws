"""An object body was read however large, however deep, and whatever it repeated.

Refusing bodies that are not JSON objects left four readings of a body that *is*
an object to chance. A field named twice: parsers disagree on which value wins,
so a proxy and this handler could each act on a different request. The constants
NaN and Infinity, which Python's parser accepts, no JSON client emits, and which
compare false with every bound a route checks. Nesting deep enough to exhaust the
parser's recursion, which surfaced as a crash rather than a refusal. And a body
larger than any client of this API sends, parsed in full before anything looked.

Each is now refused before any route runs, with a plain sentence and no
traceback, while the largest donor CSV a coordinator may upload still fits.
"""

from __future__ import annotations

import base64
import json

import pytest

from merismos import handler
from merismos.csv_intake import MAX_BYTES as CSV_MAX_BYTES
from merismos.ledger import ledger_from_env, reset_memory_ledger


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    reset_memory_ledger()


def coordinator_post(path: str, body: str, **extra) -> dict:
    return handler.handler({
        "requestContext": {"http": {"method": "POST", "path": path},
                           "authorizer": {"lambda": {"network": handler.NETWORK,
                                                     "principalId": "fixture-coordinator",
                                                     "permissions": ["merismos:coordinate"]}}},
        "headers": {"content-type": "application/json"},
        "body": body,
        **extra,
    })


def route(body: str, **extra) -> dict:
    _, _, parsed = handler._route({
        "requestContext": {"http": {"method": "POST", "path": "/run"}},
        "headers": {"content-type": "application/json"},
        "body": body,
        **extra,
    })
    return parsed


def nothing_ran() -> bool:
    ledger = ledger_from_env()
    return not any(ledger.recall(f"{handler.NETWORK}/offers/{offer}", "run.started")
                   for offer in ("offer-4471", "offer-4477", "offer-4483"))


def refused(reply: dict, status: int, words: str) -> None:
    assert reply["statusCode"] == status, reply["body"]
    detail = json.loads(reply["body"])["detail"]
    assert words in detail
    assert "Traceback" not in reply["body"]
    assert nothing_ran(), "a run started on a body that should have been refused"


@pytest.mark.parametrize("body", [
    '{"offer": "offer-4471", "offer": "offer-4477"}',
    '{"offer": "offer-4471", "plan": {"kg": 1, "kg": 2}}',
])
def test_a_field_named_twice_is_refused(body):
    refused(coordinator_post("/run", body), 400, "twice")


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_number_that_json_does_not_have_is_refused(constant):
    refused(coordinator_post("/run", '{"offer": "offer-4471", "quantity": %s}' % constant),
            400, constant)


def nested(levels: int) -> str:
    inner = "[" * (levels - 1) + "]" * (levels - 1)
    return '{"offer": "offer-4471", "x": %s}' % inner


def test_nesting_at_the_bound_is_read_and_one_level_more_is_refused():
    assert route(nested(handler.MAX_BODY_DEPTH))["offer"] == "offer-4471"
    with pytest.raises(handler.MalformedBody, match="deeper"):
        route(nested(handler.MAX_BODY_DEPTH + 1))


def test_nesting_that_would_exhaust_the_parser_is_a_refusal_not_a_crash():
    bomb = '{"x": ' + "[" * 200_000 + "]" * 200_000 + "}"
    refused(coordinator_post("/run", bomb), 400, "deeper")


def test_a_body_larger_than_any_client_sends_is_refused():
    body = json.dumps({"offer": "offer-4471", "note": "x" * handler.MAX_BODY_BYTES})
    refused(coordinator_post("/run", body), 413, "larger than")


def test_multibyte_text_is_measured_in_bytes_not_characters():
    body = json.dumps({"note": "α" * (handler.MAX_BODY_BYTES // 2 + 1)}, ensure_ascii=False)
    assert len(body) < handler.MAX_BODY_BYTES < len(body.encode("utf-8"))
    refused(coordinator_post("/run", body), 413, "larger than")


def test_the_bound_applies_when_the_gateway_base64_encodes_the_body():
    body = json.dumps({"note": "x" * handler.MAX_BODY_BYTES}).encode("utf-8")
    encoded = base64.b64encode(body).decode("ascii")
    refused(coordinator_post("/run", encoded, isBase64Encoded=True), 413, "larger than")


@pytest.mark.parametrize("worst", ['"' * CSV_MAX_BYTES, "α" * (CSV_MAX_BYTES // 2)],
                         ids=["every-byte-a-quote", "every-character-greek"])
def test_the_largest_csv_a_coordinator_may_upload_still_fits(worst):
    # Every character escaped: quotes double, non-ASCII becomes a six-byte escape.
    body = json.dumps({"csv": worst})
    assert len(body.encode("utf-8")) <= handler.MAX_BODY_BYTES
    assert route(body)["csv"] == worst
    encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")
    assert route(encoded, isBase64Encoded=True)["csv"] == worst


def test_an_ordinary_body_and_an_empty_one_are_unchanged():
    assert route('{"offer": "offer-4471", "allocations": [{"member": "a", "kg": 40}]}') == {
        "offer": "offer-4471", "allocations": [{"member": "a", "kg": 40}]}
    assert route("") == {}


def test_the_bounds_are_published_where_a_stranger_can_read_them():
    published = handler.config()
    assert published["max_request_body_bytes"] == handler.MAX_BODY_BYTES
    assert published["max_request_body_depth"] == handler.MAX_BODY_DEPTH

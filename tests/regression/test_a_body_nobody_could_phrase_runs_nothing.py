"""A malformed request body became ``{}`` and the route ran with defaults.

``_route`` swallowed every JSON error and answered with an empty object, and a
JSON array or string became an empty object too. A coordinator whose client
mis-encoded a body then started a run against whatever the route's defaults
named, and the test that covered it asserted the 200. The body of a request is
what the caller asked for; when nobody managed to phrase it, nothing should run.

Empty bodies stay allowed, because GETs have none, and form-encoded legacy posts
keep working, because the compatible screens send them.
"""

from __future__ import annotations

import base64
import json

import pytest

from merismos import handler
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


def nothing_ran() -> bool:
    ledger = ledger_from_env()
    return not any(ledger.recall(f"{handler.NETWORK}/offers/{offer}", "run.started")
                   for offer in ("offer-4471", "offer-4477", "offer-4483"))


@pytest.mark.parametrize("body", ["{not json", "[1, 2]", '"a string"', "42", "null"])
def test_a_body_that_is_not_an_object_is_refused_before_any_route(body):
    reply = coordinator_post("/run", body)

    assert reply["statusCode"] == 400
    assert "request body" in json.loads(reply["body"])["detail"]
    assert nothing_ran(), "a run started on a request nobody managed to phrase"


def test_the_refusal_says_which_of_the_two_things_went_wrong():
    assert "not valid JSON" in json.loads(coordinator_post("/run", "{oops")["body"])["detail"]
    assert "must be a JSON object" in json.loads(coordinator_post("/run", "[]")["body"])["detail"]


def test_a_body_that_is_not_utf8_is_refused_rather_than_a_stack_trace():
    reply = coordinator_post("/run", base64.b64encode(b"\xff\xfe{").decode(),
                             isBase64Encoded=True)

    assert reply["statusCode"] == 400
    assert "decoded" in json.loads(reply["body"])["detail"]


def test_base64_that_is_not_base64_is_refused_the_same_way():
    reply = coordinator_post("/run", "not*base64*at*all", isBase64Encoded=True)

    assert reply["statusCode"] == 400
    assert "Traceback" not in reply["body"]


def test_the_api_routes_are_refused_before_the_session_is_looked_up():
    reply = handler.handler({
        "requestContext": {"http": {"method": "POST", "path": "/api/offers/offer-4471/run"}},
        "headers": {"x-merismos-session": "x" * 43},
        "body": "{not json",
    })

    assert reply["statusCode"] == 400
    assert "not valid JSON" in json.loads(reply["body"])["detail"], (
        "the session was checked before the body could be read"
    )


def test_an_empty_body_is_still_an_empty_object():
    reply = handler.handler({
        "requestContext": {"http": {"method": "GET", "path": "/identity"}},
        "headers": {}, "body": "",
    })

    assert reply["statusCode"] == 200


def test_a_form_encoded_body_still_reads_as_a_form():
    reply = handler.handler({
        "requestContext": {"http": {"method": "POST", "path": "/run"},
                           "authorizer": {"lambda": {"network": handler.NETWORK,
                                                     "principalId": "fixture-coordinator",
                                                     "permissions": ["merismos:coordinate"]}}},
        "headers": {"content-type": "application/x-www-form-urlencoded"},
        "body": "offer=offer-4477",
    })

    assert reply["statusCode"] == 200
    assert json.loads(reply["body"])["outcome"] == "blocked"


def test_the_refusal_carries_no_token_and_no_trace():
    reply = coordinator_post("/run", "{not json")

    assert "Traceback" not in reply["body"]
    assert "fixture-coordinator" not in reply["body"]

"""`/thread` ignored the parameter every URL on the site carries.

Every screen produces `?run=run-xxxx`. The endpoint read `run_id`. So the obvious
thing to do with an endpoint called thread, copying the run id out of the address
bar, returned `{"run_id": "", "entries": []}`. That is what happened when it was
tried against the live site.

The parameter name is the smaller half. An empty ``entries`` list for a missing
parameter is indistinguishable from a real run that recorded nothing, so the
answer to "you did not name a run" looked exactly like the answer to "that run
recorded nothing". Silence read as data, in the endpoint whose entire purpose is
evidence.
"""

from __future__ import annotations

import json

import pytest

from merismos import handler
from merismos.fleet import new_run_id, subject_for_offer
from merismos.ledger import Thread, ledger_from_env


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()


def api(query: dict) -> dict:
    reply = handler.handler(
        {
            "requestContext": {"http": {"method": "GET", "path": "/thread"}},
            "headers": {"content-type": "application/json"},
            "body": "{}",
            "queryStringParameters": query,
        }
    )
    assert reply["statusCode"] == 200
    return json.loads(reply["body"])


@pytest.fixture
def a_run() -> str:
    offer = handler._offer("offer-4471")
    run = new_run_id()
    Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(handler.NETWORK, offer),
        run_id=run,
    ).append("run.started", offer_id="offer-4471")
    handler._run_in_background(
        {
            "source": "merismos.background",
            "offer_id": "offer-4471",
            "run_id": run,
            "network": handler.NETWORK,
        }
    )
    return run


def test_the_spelling_the_sites_own_urls_use_is_accepted(a_run):
    """`?run=` is what a person copies out of the address bar."""
    answered = api({"run": a_run})

    assert answered["run_id"] == a_run
    assert answered["entries"], "the run id from the site's own URL returned nothing"


def test_the_spelling_the_api_documented_still_works(a_run):
    assert api({"run_id": a_run})["entries"]


def test_both_spellings_return_the_same_thread(a_run):
    assert api({"run": a_run}) == api({"run_id": a_run})


def test_naming_no_run_is_answered_rather_than_returned_as_an_empty_run():
    """The half that matters. These two were the same answer."""
    answered = api({})

    assert answered["entries"] == []
    assert "detail" in answered, (
        "a missing parameter returned an empty entries list and nothing else, "
        "which is exactly what a real run with no entries returns"
    )
    assert "/thread?run=" in answered["detail"], "it says something is wrong and not what to do"


def test_a_run_that_does_not_exist_is_not_reported_as_a_bad_request():
    """An unknown run genuinely has no entries, and says nothing else."""
    answered = api({"run": "run-000000000000"})

    assert answered["run_id"] == "run-000000000000"
    assert answered["entries"] == []
    assert "detail" not in answered, (
        "an unknown run is being told it did not name a run, which is a "
        "different problem with a different fix"
    )

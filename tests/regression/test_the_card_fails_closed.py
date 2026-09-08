"""A ledger read on the approval card route, and what it does when it fails.

``key`` used to be a string interpolation that could not fail. Making a
correction take the next address in the series turned it into a ledger read, and
that put a transient DynamoDB error on the one route where a person is actually
in the loop. The failure was a 500 carrying the word AttributeError.

**The recovery is the interesting part, because the obvious one is wrong.** If
the thread cannot be read we do not know whether a record for this offer already
exists. Falling back to the base key looks reasonable and publishes on top of a
record somebody may have acted on, which is the exact thing the series exists to
prevent. So it fails closed and says which of the two states it is in.

The failure injected here is deliberately partial: only the lookup of what has
been published breaks, and the run itself still reads. A ledger that is wholly
unreachable never reaches this code, so breaking everything would have proved
nothing about it.
"""

from __future__ import annotations

import json

import pytest

from merismos import handler


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()


def get(path: str, **kw) -> dict:
    return handler.handler(
        {
            "requestContext": {"http": {"method": kw.get("method", "GET"), "path": path}},
            "headers": {"content-type": "application/json"},
            "body": json.dumps(kw.get("form", {})),
            "queryStringParameters": kw.get("query", {}),
        }
    )


def a_run(offer_id: str = "offer-4471") -> str:
    """A finished run, the way the other integration tests make one."""
    from merismos.fleet import new_run_id, subject_for_offer
    from merismos.ledger import Thread, ledger_from_env

    offer = handler._offer(offer_id)
    run = new_run_id()
    Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(handler.NETWORK, offer),
        run_id=run,
    ).append("run.started", offer_id=offer_id)

    # Driven directly rather than through the POST, which dispatches the chore
    # to another function and returns before it has finished. A card needs a run
    # that completed.
    handler._run_in_background(
        {
            "source": "merismos.background",
            "offer_id": offer_id,
            "run_id": run,
            "network": handler.NETWORK,
        }
    )
    return run


class OnlyPublishedFails:
    """The real ledger, except that asking what has been published raises.

    Wrapping rather than replacing is the point. The run still has to be
    readable, or the route returns 404 long before it reaches the line under
    test and the test proves nothing.
    """

    def __init__(self, real):
        self._real = real

    def recall(self, subject, kind, limit=20):
        if kind == "record.published":
            raise RuntimeError("ProvisionedThroughputExceededException")
        return self._real.recall(subject, kind, limit)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def break_published_lookup(monkeypatch):
    """Break the lookup **after** the run exists, not before.

    ``run_chore`` recalls ``record.published`` too, to give the specialists what
    the network decided last time. Breaking it up front takes the chore down and
    the card then 404s for want of a finished run, which says nothing about the
    line under test. So this is a function the test calls once it has one.
    """

    def apply() -> None:
        from merismos.ledger import ledger_from_env

        monkeypatch.setattr(
            handler, "ledger_from_env", lambda: OnlyPublishedFails(ledger_from_env())
        )

    return apply


def card(run: str, offer_id: str = "offer-4471") -> dict:
    return get(f"/approve/{offer_id}", query={"run": run})


def test_the_card_is_served_normally_when_the_thread_reads():
    """The control. Without it the next two pass on a route that never works."""
    reply = card(a_run())

    assert reply["statusCode"] == 200
    assert "records/offer-4471.md" in reply["body"]


def test_an_unreadable_thread_does_not_answer_with_a_stack_trace(break_published_lookup):
    run = a_run()
    break_published_lookup()
    reply = card(run)

    assert reply["statusCode"] != 500, "the card answered with a stack trace"
    assert "AttributeError" not in reply["body"]
    assert "cannot be assembled" in reply["body"]


def test_it_says_which_of_the_two_states_it_is_in(break_published_lookup):
    """"Something went wrong" leaves a coordinator with nothing to do."""
    run = a_run()
    break_published_lookup()
    body = card(run)["body"]

    assert "already been published is" in body
    assert "unknown" in body
    assert "will not publish on a guess" in body
    assert "nothing has been lost" in body.lower()


def test_it_fails_closed_rather_than_falling_back_to_the_base_key(break_published_lookup):
    """The wrong recovery is the one that looks reasonable.

    Guessing the base key when the thread is unreadable is how a correction
    overwrites the record it was correcting.
    """
    run = a_run()
    break_published_lookup()
    reply = card(run)

    assert reply["statusCode"] == 503, (
        "the card was served anyway, so it carries an address chosen without "
        "knowing whether that address is already in use"
    )
    assert "records/offer-4471.md" not in reply["body"], (
        "the page still names the base key, so a reader is being shown the "
        "address the card would have published to"
    )

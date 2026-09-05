"""The approval card, bound to the run the coordinator actually read.

Found by asking why the deployed site had returned 503 to a stranger. The
approve route called ``_decide``, which runs the whole chore again, inside the
request. Two things were wrong with that and the second is the serious one.

**It cannot fit in a request.** A gateway integration gets thirty seconds and
four specialists reading with a model take minutes. That is the exact problem the
background chore was built to solve, still present on the one route the product
exists for, and it held a concurrency slot for as long as it ran.

**And it re-decided.** The coordinator reads a decision produced by one run and
then approves bytes produced by a different one. The digest binds the card to the
publish, which is the tampering case. Nothing bound the card to the decision that
was read, which is the honesty case, and with a model in the fleet two runs can
genuinely disagree.

So the test that matters here is the one that makes a second run impossible and
asserts the card still renders.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import pytest

from merismos import handler
from merismos.corpus import LocalCorpus, offers


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    monkeypatch.delenv("MERISMOS_CRITIC_MODEL", raising=False)
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()


OFFER_ID = "offer-4471"


def request(path: str, method: str = "GET", form: dict | None = None, query: dict | None = None):
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": {"content-type": "application/json"},
        "body": "{}",
        "queryStringParameters": query or {},
    }
    if form is not None:
        event["headers"]["content-type"] = "application/x-www-form-urlencoded"
        event["body"] = urlencode(form)
    return handler.handler(event)


def a_finished_run() -> str:
    """One chore run to completion in the background shape, and its run id.

    The chore is invoked directly rather than through the POST that starts it.
    The POST needs a Lambda to invoke and there is none here, and a run that
    failed to start is recorded as failed, which is the right behaviour and the
    wrong starting point for these.
    """
    from merismos.fleet import new_run_id, subject_for_offer
    from merismos.ledger import Thread, ledger_from_env

    offer = next(o for o in offers(LocalCorpus()) if o["id"] == OFFER_ID)
    run_id = new_run_id()
    Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(handler.NETWORK, offer),
        run_id=run_id,
    ).append("run.started", offer_id=OFFER_ID)

    handler._run_in_background(
        {
            "source": "merismos.background",
            "offer_id": OFFER_ID,
            "run_id": run_id,
            "network": handler.NETWORK,
        }
    )
    return run_id


def test_the_decision_screen_hands_the_run_id_to_the_approve_link():
    """Without this the card cannot know which run it is about."""
    run_id = a_finished_run()

    body = request(f"/offer/{OFFER_ID}", query={"run": run_id})["body"]

    assert f"/approve/{OFFER_ID}?run={run_id}" in body


def test_the_card_renders_the_recorded_run_and_never_starts_a_second_one(monkeypatch):
    """The assertion this module exists for.

    ``run_chore`` is made to raise. If the approve route still renders a card,
    the card came from the thread. If it does not, the route re-decided, and on
    the deployed path that second run is a chore with four model reads inside a
    thirty second request.
    """
    run_id = a_finished_run()

    def never(*args, **kwargs):
        raise AssertionError("the approve route ran the chore again")

    monkeypatch.setattr(handler, "run_chore", never)

    reply = request(f"/approve/{OFFER_ID}", query={"run": run_id})

    assert reply["statusCode"] == 200
    assert "Approve this record" in reply["body"]
    assert "You are approving" in reply["body"]


def test_the_bytes_on_the_card_are_the_bytes_of_the_decision_that_was_read():
    """Byte for byte, not merely both plausible."""
    run_id = a_finished_run()
    from merismos import background
    from merismos.ledger import ledger_from_env

    record = background.completed_result(ledger_from_env().thread(run_id))
    assert record, "the run recorded nothing"
    drafted = record["draft_body"]

    card = request(f"/approve/{OFFER_ID}", query={"run": run_id})["body"]

    # The card escapes the body for HTML, so compare on a line that survives it.
    for line in drafted.splitlines():
        if line.startswith("| ") and "%" in line:
            assert line.replace("&", "&amp;") in card, f"the card is missing {line!r}"


def test_the_digest_on_the_card_is_over_the_recorded_bytes():
    """What the person signs has to be a hash of what they were shown."""
    run_id = a_finished_run()
    from merismos import background
    from merismos.approval import digest
    from merismos.ledger import ledger_from_env

    record = background.completed_result(ledger_from_env().thread(run_id))
    expected = digest(handler.NETWORK, f"records/{OFFER_ID}.md", record["draft_body"])

    card = request(f"/approve/{OFFER_ID}", query={"run": run_id})["body"]

    assert expected in card


def test_the_form_carries_the_run_forward_so_the_publish_covers_the_same_bytes():
    run_id = a_finished_run()

    card = request(f"/approve/{OFFER_ID}", query={"run": run_id})["body"]

    assert f'name="run" value="{run_id}"' in card


def test_a_run_that_is_not_in_the_thread_is_refused_rather_than_re_decided():
    """An expired or invented run must not silently become a fresh decision."""
    reply = request(f"/approve/{OFFER_ID}", query={"run": "run-000000000000"})

    assert reply["statusCode"] == 404
    assert "no longer in the thread" in reply["body"]
    assert "nothing to approve" in reply["body"]


def test_a_run_belonging_to_a_different_offer_is_refused():
    """Otherwise a card could be assembled from somebody else's decision."""
    run_id = a_finished_run()

    reply = request("/approve/offer-4477", query={"run": run_id})

    assert reply["statusCode"] == 404


def test_with_no_run_id_it_still_decides_because_the_cli_and_the_suite_do():
    """The fallback, so an absent id degrades to the old path rather than a break."""
    reply = request(f"/approve/{OFFER_ID}")

    assert reply["statusCode"] == 200
    assert "Approve this record" in reply["body"]


def test_publishing_uses_the_recorded_run_rather_than_deciding_again(monkeypatch):
    """The POST half. It is the half that writes, so it matters more."""
    run_id = a_finished_run()

    def never(*args, **kwargs):
        raise AssertionError("the publish route ran the chore again")

    monkeypatch.setattr(handler, "run_chore", never)

    asked = {}

    def fake_writer(FunctionName, Payload):  # noqa: N803 - boto3's own casing
        asked["payload"] = json.loads(json.loads(Payload)["body"])
        return {
            "Payload": type(
                "R",
                (),
                {
                    "read": lambda self: json.dumps(
                        {
                            "statusCode": 200,
                            "body": json.dumps(
                                {
                                    "approved_by": "the coordinator",
                                    "key": f"records/{OFFER_ID}.md",
                                    "published_url": "https://example.invalid/x",
                                    "content_digest": "d",
                                    "nonce": "n",
                                }
                            ),
                        }
                    )
                },
            )()
        }

    import boto3

    class FakeAws:
        """One object for both clients this path reaches: dynamodb, then lambda."""

        invoke = staticmethod(fake_writer)

        def put_item(self, **kwargs):
            return {}

    monkeypatch.setenv("MERISMOS_WRITER_FUNCTION", "merismos-writer")
    monkeypatch.setenv("MERISMOS_APPROVALS_TABLE", "merismos-approvals")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: FakeAws())

    reply = request(
        f"/approve/{OFFER_ID}",
        method="POST",
        form={"approved_by": "the coordinator", "run": run_id},
    )

    assert reply["statusCode"] == 200, reply["body"][:300]

    from merismos import background
    from merismos.ledger import ledger_from_env

    record = background.completed_result(ledger_from_env().thread(run_id))
    assert asked["payload"]["body"] == record["draft_body"], (
        "the bytes sent to the writer are not the bytes the coordinator read"
    )

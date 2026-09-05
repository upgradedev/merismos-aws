"""The intake route, end to end across the two identities it crosses.

A coordinator's form is the only untrusted text that enters this system through
a door rather than through a commit, so the interesting assertions are not that
it works. They are these three, and each one is a way this feature could quietly
undo the architecture around it:

* the identity a stranger is talking to still cannot write anything, and files
  an offer by asking the identity that can;
* the writer builds the offer itself from the form rather than trusting one the
  reader assembled, exactly as it recomputes the digest rather than trusting a
  publish payload;
* the key is constructed from a validated id, so this route cannot be aimed at
  a published record, at the register of members, or at the policy the gate
  applies.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import boto3
import pytest
from botocore.stub import Stubber

from merismos import handler

BUCKET = "merismos-corpus"

FORM = {
    "title": "End of day bread and vegetables",
    "donor": "Neighbourhood bakery",
    "quantity": "240",
    "unit": "kg",
    "category": "ambient",
    "collection_date": "2026-09-14",
    "note": "Collect before 19:00.",
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    monkeypatch.setenv("MERISMOS_WRITER_FUNCTION", "merismos-writer")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()


def post(path: str, form: dict) -> dict:
    return handler.handler(
        {
            "requestContext": {"http": {"method": "POST", "path": path}},
            "headers": {"content-type": "application/x-www-form-urlencoded"},
            "body": urlencode(form),
        }
    )


def get(path: str) -> dict:
    return handler.handler(
        {
            "requestContext": {"http": {"method": "GET", "path": path}},
            "headers": {"content-type": "application/json"},
            "body": "{}",
        }
    )


# --------------------------------------------------------------------------
# The reader's side. It validates, and then it asks.
# --------------------------------------------------------------------------


def test_the_form_is_reachable_and_says_what_happens_to_what_you_type():
    reply = get("/offers/new")

    assert reply["statusCode"] == 200
    body = reply["body"]
    assert "Add an offer" in body
    assert "never sent anywhere else" in body
    assert 'action="/offers/new"' in body


def test_the_inbox_offers_a_way_in_because_a_page_nobody_can_reach_is_not_a_feature():
    assert "/offers/new" in get("/")["body"]


def test_a_refused_form_comes_back_with_what_the_person_typed_still_in_it(monkeypatch):
    """Retyping four correct fields to fix the fifth is how a form loses a user."""
    called = []
    monkeypatch.setattr(
        handler, "_ask_the_writer_to_file", lambda *a: called.append(a) or (200, "")
    )

    reply = post("/offers/new", {**FORM, "note": "Ring 6944 123 456 on arrival"})

    assert reply["statusCode"] == 400
    assert "End of day bread and vegetables" in reply["body"]
    assert "Neighbourhood bakery" in reply["body"]
    assert not called, "a refused form was still sent to the writer"


def test_a_good_form_is_handed_to_the_writer_and_the_person_lands_on_the_offer(monkeypatch):
    seen = {}

    def fake(offer_id, form):
        seen["offer_id"] = offer_id
        seen["form"] = form
        return 200, ""

    monkeypatch.setattr(handler, "_ask_the_writer_to_file", fake)

    reply = post("/offers/new", FORM)

    assert reply["statusCode"] in (302, 303)
    assert seen["offer_id"].startswith("offer-")
    assert reply["headers"]["location"] == f"/offer/{seen['offer_id']}"
    # The form is passed on as typed. The writer builds the offer, not this side.
    assert seen["form"]["title"] == FORM["title"]


def test_the_id_offered_continues_the_filings_own_sequence(monkeypatch):
    from merismos.corpus import LocalCorpus, offers

    seen = {}
    monkeypatch.setattr(
        handler,
        "_ask_the_writer_to_file",
        lambda offer_id, form: (seen.setdefault("id", offer_id), (200, ""))[1],
    )

    post("/offers/new", FORM)

    highest = max(int(o["id"].split("-")[1]) for o in offers(LocalCorpus()))
    assert seen["id"] == f"offer-{highest + 1}"


def test_a_writer_that_refuses_is_reported_in_the_persons_own_words(monkeypatch):
    monkeypatch.setattr(
        handler, "_ask_the_writer_to_file", lambda *a: (409, "offer-4484 was taken")
    )

    reply = post("/offers/new", FORM)

    assert reply["statusCode"] == 409, "a clash of ids was reported as an outage"
    assert "was taken" in reply["body"]


def test_no_writer_configured_is_a_message_and_not_a_stack_trace(monkeypatch):
    monkeypatch.delenv("MERISMOS_WRITER_FUNCTION", raising=False)

    reply = post("/offers/new", FORM)

    assert reply["statusCode"] == 502
    assert "No writer is configured" in reply["body"]


def test_the_reader_reaches_the_writer_over_the_grant_it_already_had(monkeypatch):
    """No new AWS authority. The payload is an invoke, shaped like the publish one."""
    invoked = {}

    class FakeLambda:
        def invoke(self, FunctionName, Payload):  # noqa: N803 - boto3's own casing
            invoked["function"] = FunctionName
            invoked["payload"] = json.loads(Payload)
            return {
                "Payload": type(
                    "R", (), {"read": lambda self: json.dumps({"statusCode": 200, "body": "{}"})}
                )()
            }

    monkeypatch.setattr(boto3, "client", lambda name, *a, **k: FakeLambda())

    status, detail = handler._ask_the_writer_to_file("offer-4484", FORM)

    assert (status, detail) == (200, "")
    assert invoked["function"] == "merismos-writer"
    assert invoked["payload"]["requestContext"]["http"]["path"] == "/intake"
    body = json.loads(invoked["payload"]["body"])
    assert body["offer_id"] == "offer-4484"
    assert body["form"]["title"] == FORM["title"]
    assert "s3" not in str(invoked), "the reader touched S3"


# --------------------------------------------------------------------------
# The writer's side. It trusts nothing it was handed.
# --------------------------------------------------------------------------


def _intake_event(payload: dict) -> dict:
    return {
        "requestContext": {"http": {"method": "POST", "path": "/intake"}},
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload),
    }


@pytest.mark.parametrize("who", ["reader", "evaluator"])
def test_only_the_writer_files_an_offer(monkeypatch, who):
    monkeypatch.setenv("MERISMOS_ROLE", who)

    reply = handler.take_offer({"offer_id": "offer-4484", "form": FORM})

    assert reply["statusCode"] == 403
    assert who in json.loads(reply["body"])["detail"]


def test_the_writer_validates_the_form_itself_rather_than_trusting_the_caller(monkeypatch):
    """The reader could be wrong, or talked into being wrong. This is the second lock.

    Same argument as the digest at publish time: the identity that holds the
    authority re-derives what it is about to write instead of accepting a
    caller's word that it was checked.
    """
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: pytest.fail("it wrote anyway"))

    reply = handler.take_offer(
        {"offer_id": "offer-4484", "form": {**FORM, "note": "Call maria@example.gr"}}
    )

    assert reply["statusCode"] == 400
    assert "published record" in json.loads(reply["body"])["detail"]


@pytest.mark.parametrize(
    "offer_id",
    [
        "../records/offer-4471",
        "offer-4484/../../orgs/pantry",
        "offer-",
        "",
        "orgs/pantry",
        "offer-4484.json",
        "offer-" + "9" * 40,
    ],
)
def test_an_id_that_is_not_this_networks_own_sequence_is_refused(monkeypatch, offer_id):
    """Traversal fails before a key is built, and the key is built and never taken."""
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: pytest.fail("it wrote anyway"))

    reply = handler.take_offer({"offer_id": offer_id, "form": FORM})

    assert reply["statusCode"] == 400


def test_a_key_supplied_by_the_caller_is_ignored(monkeypatch):
    """The one field that would turn an intake into an overwrite of a record."""
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_CORPUS_BUCKET", BUCKET)
    client = boto3.client("s3", region_name="eu-west-1")
    stubber = Stubber(client)
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": BUCKET,
            "Key": "offers/offer-4484.json",
            "Body": _any(),
            "ContentType": "application/json; charset=utf-8",
            "IfNoneMatch": "*",
        },
    )
    monkeypatch.setattr(boto3, "client", lambda *a, **k: client)

    with stubber:
        reply = handler.take_offer(
            {
                "offer_id": "offer-4484",
                "key": "records/offer-4471.md",
                "Key": "records/offer-4471.md",
                "form": FORM,
            }
        )

    assert reply["statusCode"] == 200
    assert json.loads(reply["body"])["key"] == "offers/offer-4484.json"
    stubber.assert_no_pending_responses()


def test_the_write_is_a_create_that_s3_itself_refuses_to_turn_into_an_overwrite(monkeypatch):
    """IfNoneMatch is the control. Without it, intake could replace a decided offer."""
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_CORPUS_BUCKET", BUCKET)
    client = boto3.client("s3", region_name="eu-west-1")
    stubber = Stubber(client)
    stubber.add_client_error(
        "put_object", service_error_code="PreconditionFailed", http_status_code=412
    )
    monkeypatch.setattr(boto3, "client", lambda *a, **k: client)

    with stubber:
        reply = handler.take_offer({"offer_id": "offer-4471", "form": FORM})

    assert reply["statusCode"] == 409
    detail = json.loads(reply["body"])["detail"]
    assert "Nothing was overwritten" in detail


def test_a_prefixed_corpus_is_written_under_its_own_prefix(monkeypatch):
    """A network pointing the fleet at a subdirectory of its own bucket.

    Not the deployed shape: ``MERISMOS_CORPUS_PREFIX`` is unset in ``main.tf``
    and the writer's grant is ``corpus.arn/offers/*``, which a prefixed key would
    not match. Said out loud here because a green test pinning a path IAM forbids
    is exactly the shape of defect that has cost this project the most. If a
    prefix is ever configured, the Terraform resource has to move with it.
    """
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_CORPUS_BUCKET", BUCKET)
    monkeypatch.setenv("MERISMOS_CORPUS_PREFIX", "networks/kypseli")
    client = boto3.client("s3", region_name="eu-west-1")
    stubber = Stubber(client)
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": BUCKET,
            "Key": "networks/kypseli/offers/offer-4484.json",
            "Body": _any(),
            "ContentType": "application/json; charset=utf-8",
            "IfNoneMatch": "*",
        },
    )
    monkeypatch.setattr(boto3, "client", lambda *a, **k: client)

    with stubber:
        reply = handler.take_offer({"offer_id": "offer-4484", "form": FORM})

    assert reply["statusCode"] == 200
    stubber.assert_no_pending_responses()


def test_what_is_written_is_the_offer_the_fleet_will_read(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_CORPUS_BUCKET", BUCKET)
    written = {}

    class FakeS3:
        def put_object(self, **kwargs):
            written.update(kwargs)
            return {}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: FakeS3())

    handler.take_offer({"offer_id": "offer-4484", "form": FORM})

    offer = json.loads(written["Body"].decode("utf-8"))
    assert offer["id"] == "offer-4484"
    assert offer["title"] == FORM["title"]
    assert offer["quantity"] == 240.0
    assert written["IfNoneMatch"] == "*"


def test_filing_an_offer_is_recorded_on_the_thread_like_everything_else(monkeypatch):
    """An offer from a stranger must be as traceable as one from the fixture."""
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_CORPUS_BUCKET", BUCKET)

    class FakeS3:
        def put_object(self, **kwargs):
            return {}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: FakeS3())

    handler.take_offer({"offer_id": "offer-4484", "form": FORM})

    from merismos.ledger import ledger_from_env

    filed = ledger_from_env().recall(handler.NETWORK, "offer.filed", limit=5)
    assert filed, "an offer was filed and the thread does not know"
    assert filed[0].body["offer_id"] == "offer-4484"
    assert filed[0].body["donor"] == FORM["donor"]


def test_a_missing_form_is_a_message_and_not_a_crash(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "writer")

    reply = handler.take_offer({"offer_id": "offer-4484"})

    assert reply["statusCode"] == 400
    assert "form" in json.loads(reply["body"])["detail"]


def test_no_corpus_configured_is_reported_rather_than_raised(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.delenv("MERISMOS_CORPUS_BUCKET", raising=False)

    reply = handler.take_offer({"offer_id": "offer-4484", "form": FORM})

    assert reply["statusCode"] == 500
    assert "no corpus" in json.loads(reply["body"])["detail"]


def test_the_route_reaches_take_offer_on_the_writer_and_nowhere_else(monkeypatch):
    """The dispatcher, not the function. A function nothing routes to is dead code."""
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_CORPUS_BUCKET", BUCKET)

    class FakeS3:
        def put_object(self, **kwargs):
            return {}

    monkeypatch.setattr(boto3, "client", lambda *a, **k: FakeS3())

    reply = handler.handler(_intake_event({"offer_id": "offer-4484", "form": FORM}))

    assert reply["statusCode"] == 200

    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    assert handler.handler(_intake_event({"offer_id": "offer-4484", "form": FORM}))[
        "statusCode"
    ] == 403


class _any:
    """Stubber compares expected params by equality, and the body is derived."""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, bytes) and b'"id"' in other

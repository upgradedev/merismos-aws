"""The deployed ledger, checked against DynamoDB's own API shape.

Coverage that exercises only the in-memory ledger is a fiction: the two are
swapped by an environment variable and only one of them ever runs in front of a
judge. So the deployed adapter is stubbed against botocore's service model,
which rejects a misspelled key or a wrongly typed attribute value the way a real
call would.

The condition expressions are the assertions worth reading. ``append`` carries
``attribute_not_exists(entry_id)`` so a replayed write is a condition failure
rather than a silent overwrite of an entry somebody has already read. On this
platform, append-only is a condition expression and not a hope.
"""

from __future__ import annotations

import json

import boto3
import pytest
from botocore.stub import ANY, Stubber

from merismos.ledger import (
    DynamoDbLedger,
    Entry,
    InMemoryLedger,
    Thread,
    UnknownKind,
    entries_as_json,
    ledger_from_env,
    subject_for,
)

TABLE = "merismos-thread"


@pytest.fixture
def client():
    return boto3.client("dynamodb", region_name="eu-west-1")


def _item(entry_id="e1", kind="offer.received", subject="net:pantry", run_id="run-1", parent="-"):
    return {
        "subject": {"S": subject},
        "entry_id": {"S": entry_id},
        "parent_id": {"S": parent},
        "kind": {"S": kind},
        "run_id": {"S": run_id},
        "at": {"N": "1000.0"},
        "scope": {"S": "live"},
        "body": {"S": json.dumps({"offer_id": "offer-4471"})},
    }


def test_append_is_a_conditional_put_that_cannot_overwrite(client):
    stubber = Stubber(client)
    stubber.add_response(
        "put_item",
        {},
        {
            "TableName": TABLE,
            "Item": ANY,
            "ConditionExpression": "attribute_not_exists(entry_id)",
        },
    )
    ledger = DynamoDbLedger(table_name=TABLE, client=client)

    with stubber:
        entry = ledger.append(
            Entry(kind="offer.received", subject="net:pantry", run_id="run-1")
        )

    stubber.assert_no_pending_responses()
    assert entry.entry_id


def test_a_thread_is_queried_by_run_and_returned_in_time_order(client):
    stubber = Stubber(client)
    stubber.add_response(
        "query",
        {
            "Items": [
                {**_item("b"), "at": {"N": "2000.0"}},
                {**_item("a"), "at": {"N": "1000.0"}},
            ]
        },
        {
            "TableName": TABLE,
            "IndexName": "by-run",
            "KeyConditionExpression": "run_id = :r",
            "ExpressionAttributeValues": {":r": {"S": "run-1"}},
        },
    )
    ledger = DynamoDbLedger(table_name=TABLE, client=client)

    with stubber:
        entries = ledger.thread("run-1")

    assert [e.entry_id for e in entries] == ["a", "b"]
    assert entries[0].body == {"offer_id": "offer-4471"}


def test_recall_filters_on_subject_and_kind_and_returns_newest_first(client):
    stubber = Stubber(client)
    stubber.add_response(
        "query",
        {
            "Items": [
                {**_item("old", kind="record.published"), "at": {"N": "1000.0"}},
                {**_item("new", kind="record.published"), "at": {"N": "3000.0"}},
            ]
        },
        {
            "TableName": TABLE,
            "KeyConditionExpression": "subject = :s",
            "FilterExpression": "kind = :k",
            "ExpressionAttributeValues": {
                ":s": {"S": "net:pantry"},
                ":k": {"S": "record.published"},
            },
            "ScanIndexForward": False,
            "Limit": ANY,
        },
    )
    ledger = DynamoDbLedger(table_name=TABLE, client=client)

    with stubber:
        entries = ledger.recall("net:pantry", "record.published", limit=2)

    assert [e.entry_id for e in entries] == ["new", "old"]


def test_an_escalated_deferral_drops_out_of_the_open_set(client):
    """Otherwise the fleet re-escalates the same parked decision forever."""
    stubber = Stubber(client)
    def _by_kind(kind):
        return {
            "TableName": TABLE,
            "IndexName": "by-kind",
            "KeyConditionExpression": "kind = :k",
            "ExpressionAttributeValues": {":k": {"S": kind}},
        }

    stubber.add_response(
        "query",
        {
            "Items": [
                _item("d1", kind="finding.deferred"),
                _item("d2", kind="finding.deferred"),
            ]
        },
        _by_kind("finding.deferred"),
    )
    stubber.add_response(
        "query",
        {
            "Items": [
                {
                    **_item("x", kind="deferral.escalated"),
                    "body": {"S": json.dumps({"deferral_id": "d1"})},
                }
            ]
        },
        _by_kind("deferral.escalated"),
    )
    ledger = DynamoDbLedger(table_name=TABLE, client=client)

    with stubber:
        still_open = ledger.open_deferrals()

    assert [e.entry_id for e in still_open] == ["d2"]


def test_the_deployed_ledger_refuses_to_exist_without_a_table_name():
    with pytest.raises(ValueError) as raised:
        DynamoDbLedger(table_name="", client=object())

    assert "MERISMOS_LEDGER_TABLE" in str(raised.value)


def test_the_backend_is_dynamodb_unless_memory_is_asked_for_by_name():
    """A demo that quietly falls back to memory shows a stub and nobody can tell."""
    deployed = ledger_from_env({"MERISMOS_LEDGER_TABLE": TABLE})
    offline = ledger_from_env({"MERISMOS_LEDGER": "memory"})

    assert deployed.backend == "dynamodb"
    assert offline.backend == "memory"


def test_an_entry_with_an_unpublished_kind_is_refused_at_construction():
    with pytest.raises(UnknownKind):
        Entry(kind="record.quietly_amended", subject="net", run_id="run-1")


@pytest.mark.parametrize("missing", ["subject", "run_id"])
def test_an_entry_names_what_it_is_about_and_which_run_made_it(missing):
    fields = {"kind": "offer.received", "subject": "net", "run_id": "run-1"}
    fields[missing] = "  "

    with pytest.raises(ValueError):
        Entry(**fields)


def test_the_round_trip_through_dynamodbs_shape_preserves_the_entry(client):
    """A field lost in serialisation is a field missing from an audit."""
    from merismos.ledger import _from_item, _to_item

    original = Entry(
        kind="gate.verdict",
        subject="net:pantry",
        run_id="run-9",
        body={"passed": False, "findings": ["no-phone-number"]},
        parent_id="parent-1",
        at=1234.5,
    )

    restored = _from_item(_to_item(original))

    assert restored.as_dict() == original.as_dict()


def test_an_entry_with_no_parent_round_trips_as_no_parent(client):
    """DynamoDB rejects an empty string in a key-shaped attribute, hence the '-'."""
    from merismos.ledger import _from_item, _to_item

    root = Entry(kind="run.started", subject="net", run_id="run-1")

    assert _to_item(root)["parent_id"] == {"S": "-"}
    assert _from_item(_to_item(root)).parent_id == ""


# --------------------------------------------------------------------------
# The thread, which is what makes "follow it back" a walk instead of a sort.
# --------------------------------------------------------------------------


def test_the_thread_links_each_entry_to_the_one_before_it():
    thread = Thread(ledger=InMemoryLedger(), subject="net:pantry", run_id="run-1")

    first = thread.append("run.started")
    second = thread.append("offer.received", offer_id="offer-4471")
    third = thread.append("fleet.dispatch", woken=["equity"])

    assert first.parent_id == ""
    assert second.parent_id == first.entry_id
    assert third.parent_id == second.entry_id


def test_walking_the_thread_returns_it_oldest_first():
    thread = Thread(ledger=InMemoryLedger(), subject="net:pantry", run_id="run-1")
    for kind in ("run.started", "offer.received", "plan.proposed"):
        thread.append(kind)

    assert [e.kind for e in thread.walk()] == [
        "run.started",
        "offer.received",
        "plan.proposed",
    ]


def test_an_orphan_is_shown_rather_than_hidden():
    """The orphan is the entry written by the step that crashed before linking.

    A thread view that dropped it would hide precisely the row somebody is
    looking for.
    """
    ledger = InMemoryLedger()
    thread = Thread(ledger=ledger, subject="net:pantry", run_id="run-1")
    thread.append("run.started")
    ledger.append(
        Entry(kind="run.failed", subject="net:pantry", run_id="run-1", at=9999.0)
    )

    kinds = [e.kind for e in thread.walk()]

    assert "run.failed" in kinds


def test_recall_never_returns_the_run_that_is_asking():
    """A run recalling itself would read its own draft as prior knowledge."""
    ledger = InMemoryLedger()
    older = Thread(ledger=ledger, subject="net:pantry", run_id="run-old")
    older.append("record.published", orgs=["Omonoia Soup Kitchen"])
    current = Thread(ledger=ledger, subject="net:pantry", run_id="run-new")
    current.append("record.published", orgs=["Kypseli Food Pantry"])

    prior = current.recall("record.published")

    assert [e.run_id for e in prior] == ["run-old"]


def test_one_subjects_memory_is_not_anothers():
    """The bug a single tenant cannot show: a shared key and a scoped key agree."""
    ledger = InMemoryLedger()
    Thread(ledger=ledger, subject="net-a:pantry", run_id="r1").append(
        "finding.deferred", reason="a"
    )
    Thread(ledger=ledger, subject="net-b:pantry", run_id="r2").append(
        "finding.deferred", reason="b"
    )

    assert len(ledger.recall("net-a:pantry", "finding.deferred")) == 1
    assert len(ledger.open_deferrals("net-a:pantry")) == 1
    assert len(ledger.open_deferrals()) == 2


@pytest.mark.parametrize(
    ("repository", "paths", "expected"),
    [
        ("net", [], "net"),
        ("net", ["offers/ambient/a.json", "offers/ambient/b.json"], "net:offers/ambient"),
        ("net", ["offers/a.json", "orgs/b.json"], "net"),
        ("net", ["a/b/c/d.json"], "net:a/b"),
        # One file. The basename must not reach the key, or this delivery gets a
        # private memory that nothing else in the network ever reads.
        ("net", ["offers/x.json"], "net:offers"),
        ("", ["offers/x.json"], "unknown-network:offers"),
        # A file at the root shares nothing, so it falls back to the network
        # rather than borrowing a narrower key from somewhere else.
        ("net", ["README.md"], "net"),
    ],
)
def test_the_subject_is_derived_from_the_delivery(repository, paths, expected):
    """Coarse on purpose: recalling more is the safe direction for this memory."""
    assert subject_for(repository, paths) == expected


def test_two_files_in_one_area_share_a_memory_and_two_areas_do_not():
    """The property the key exists for, asserted as behaviour rather than shape."""
    together = subject_for("net", ["offers/ambient/a.json"])
    sibling = subject_for("net", ["offers/ambient/b.json"])
    elsewhere = subject_for("net", ["orgs/c.json"])

    assert together == sibling
    assert together != elsewhere


def test_a_thread_exports_as_readable_json():
    thread = Thread(ledger=InMemoryLedger(), subject="net", run_id="run-1")
    thread.append("run.started")

    exported = entries_as_json(thread.walk())

    assert json.loads(exported)[0]["kind"] == "run.started"
    assert "\n  " in exported, "an evidence pack is pretty-printed (STANDARDS F8)"

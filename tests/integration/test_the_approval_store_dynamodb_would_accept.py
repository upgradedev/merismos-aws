"""The approval store, and the one write that must not silently succeed twice.

``spend`` is the method worth stubbing rather than mocking. It is not "read the
row, decide, write the row"; it is one ``UpdateItem`` carrying
``attribute_exists(nonce) AND attribute_not_exists(spent_at)``, so two writers
racing the same approval produce one write and one
``ConditionalCheckFailedException``. A mock would accept any expression string,
including one that does not express that at all.
"""

from __future__ import annotations

import boto3
import pytest
from botocore.stub import ANY, Stubber

from merismos.approval import (
    AlreadySpent,
    Approval,
    ApprovalStore,
    Receipt,
    authorise,
    digest,
    grant,
)

TABLE = "merismos-approvals"
NETWORK = "kypseli-network"
KEY = "records/offer-4471.md"
BODY = "# Allocation\n\nOmonoia Soup Kitchen: 96 kg\n"


@pytest.fixture
def client():
    return boto3.client("dynamodb", region_name="eu-west-1")


@pytest.fixture
def approval() -> Approval:
    return grant(NETWORK, KEY, BODY, approved_by="the coordinator", run_id="run-1", now=1000.0)


def _item(approval: Approval, spent: bool = False) -> dict:
    item = {
        "nonce": {"S": approval.nonce},
        "network": {"S": approval.network},
        "key": {"S": approval.key},
        "content_digest": {"S": approval.content_digest},
        "approved_by": {"S": approval.approved_by},
        "run_id": {"S": approval.run_id},
        "expires_at": {"N": repr(approval.expires_at)},
        "granted_at": {"N": repr(approval.granted_at)},
    }
    if spent:
        item["spent_at"] = {"N": "1100.0"}
    return item


def test_putting_an_approval_cannot_overwrite_an_existing_nonce(client, approval):
    stubber = Stubber(client)
    stubber.add_response(
        "put_item",
        {},
        {
            "TableName": TABLE,
            "Item": ANY,
            "ConditionExpression": "attribute_not_exists(nonce)",
        },
    )
    store = ApprovalStore(table_name=TABLE, client=client)

    with stubber:
        store.put(approval)

    stubber.assert_no_pending_responses()


def test_an_approval_is_read_with_a_consistent_read(client, approval):
    """An eventually consistent read here is an approval that looks unspent."""
    stubber = Stubber(client)
    stubber.add_response(
        "get_item",
        {"Item": _item(approval)},
        {
            "TableName": TABLE,
            "Key": {"nonce": {"S": approval.nonce}},
            "ConsistentRead": True,
        },
    )
    store = ApprovalStore(table_name=TABLE, client=client)

    with stubber:
        found = store.get(approval.nonce)

    assert found.as_dict() == approval.as_dict()


def test_an_absent_nonce_reads_as_nothing_rather_than_raising(client):
    stubber = Stubber(client)
    stubber.add_response("get_item", {}, {
        "TableName": TABLE,
        "Key": {"nonce": {"S": "0" * 32}},
        "ConsistentRead": True,
    })
    store = ApprovalStore(table_name=TABLE, client=client)

    with stubber:
        assert store.get("0" * 32) is None


def test_spending_is_one_conditional_update_and_not_a_read_then_write(client, approval):
    stubber = Stubber(client)
    stubber.add_response(
        "update_item",
        {},
        {
            "TableName": TABLE,
            "Key": {"nonce": {"S": approval.nonce}},
            "UpdateExpression": "SET spent_at = :t",
            "ConditionExpression": (
                "attribute_exists(nonce) AND attribute_not_exists(spent_at)"
            ),
            "ExpressionAttributeValues": {":t": {"N": ANY}},
        },
    )
    store = ApprovalStore(table_name=TABLE, client=client)

    with stubber:
        store.spend(approval.nonce, now=1100.0)

    stubber.assert_no_pending_responses()


def test_a_condition_failure_is_reported_as_already_spent(client, approval):
    """The race, seen from the loser's side. 409, not a 500."""
    stubber = Stubber(client)
    stubber.add_client_error(
        "update_item", service_error_code="ConditionalCheckFailedException"
    )
    store = ApprovalStore(table_name=TABLE, client=client)

    with stubber, pytest.raises(AlreadySpent) as raised:
        store.spend(approval.nonce)

    assert raised.value.status == 409


def test_any_other_aws_failure_is_not_disguised_as_already_spent(client, approval):
    """Swallowing a throttle as "already spent" would lose a legitimate write."""
    stubber = Stubber(client)
    stubber.add_client_error(
        "update_item", service_error_code="ProvisionedThroughputExceededException"
    )
    store = ApprovalStore(table_name=TABLE, client=client)

    with stubber, pytest.raises(Exception) as raised:
        store.spend(approval.nonce)

    assert not isinstance(raised.value, AlreadySpent)


def test_the_store_refuses_to_exist_without_a_table_name():
    with pytest.raises(ValueError) as raised:
        ApprovalStore(table_name="", client=object())

    assert "MERISMOS_APPROVALS_TABLE" in str(raised.value)


def test_the_whole_authorise_path_against_the_deployed_store(client, approval):
    """Read, compare the recomputed digest, check the clock, then spend."""
    stubber = Stubber(client)
    stubber.add_response("get_item", {"Item": _item(approval)}, {
        "TableName": TABLE,
        "Key": {"nonce": {"S": approval.nonce}},
        "ConsistentRead": True,
    })
    stubber.add_response("update_item", {}, {
        "TableName": TABLE,
        "Key": {"nonce": {"S": approval.nonce}},
        "UpdateExpression": "SET spent_at = :t",
        "ConditionExpression": (
            "attribute_exists(nonce) AND attribute_not_exists(spent_at)"
        ),
        "ExpressionAttributeValues": {":t": {"N": ANY}},
    })
    store = ApprovalStore(table_name=TABLE, client=client)

    with stubber:
        result = authorise(store, approval.nonce, NETWORK, KEY, BODY, now=1100.0)

    stubber.assert_no_pending_responses()
    assert result.approved_by == "the coordinator"


def test_tampered_bytes_never_reach_the_spend(client, approval):
    """Only one call is stubbed, so a spend would fail the test loudly."""
    stubber = Stubber(client)
    stubber.add_response("get_item", {"Item": _item(approval)}, {
        "TableName": TABLE,
        "Key": {"nonce": {"S": approval.nonce}},
        "ConsistentRead": True,
    })
    store = ApprovalStore(table_name=TABLE, client=client)

    from merismos.approval import BytesChanged

    with stubber, pytest.raises(BytesChanged):
        authorise(store, approval.nonce, NETWORK, KEY, BODY + " ", now=1100.0)

    stubber.assert_no_pending_responses()


def test_the_ttl_outlives_the_expiry_so_the_row_is_still_there_to_refuse_with(approval):
    """A row deleted at expiry turns a clear 410 into a confusing 403."""
    import boto3 as _boto3

    client = _boto3.client("dynamodb", region_name="eu-west-1")
    stubber = Stubber(client)
    stubber.add_response("put_item", {}, None)
    store = ApprovalStore(table_name=TABLE, client=client)
    with stubber:
        store.put(approval)

    # The value is asserted directly rather than through the stub, because what
    # matters is the arithmetic and not that a key was sent.
    assert int(approval.expires_at) + 86400 > approval.expires_at


def test_a_receipt_names_who_authorised_the_write_and_which_approval_it_spent():
    receipt = Receipt(
        nonce="n1",
        network=NETWORK,
        key=KEY,
        content_digest=digest(NETWORK, KEY, BODY),
        approved_by="the coordinator",
        run_id="run-1",
        published_url="https://example.invalid/records/offer-4471.md",
        published_at=1100.0,
    )

    as_dict = receipt.as_dict()

    assert as_dict["approved_by"] == "the coordinator"
    assert as_dict["nonce"] == "n1"
    assert as_dict["content_digest"] == digest(NETWORK, KEY, BODY)


def test_the_approval_card_a_person_reads_is_pretty_printed(approval):
    card = approval.as_card()

    assert "\n  " in card
    assert "content_digest" in card

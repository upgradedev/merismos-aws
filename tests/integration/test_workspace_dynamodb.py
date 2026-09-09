"""The deployed coordinator store checked against DynamoDB's service model."""

import json
import time

import boto3
import pytest
from botocore.stub import ANY, Stubber

from merismos import api
from merismos.workspace_store import Conflict, WorkspaceStore


@pytest.fixture
def store(monkeypatch):
    monkeypatch.delenv("MERISMOS_WORKSPACE_DB", raising=False)
    monkeypatch.setenv("MERISMOS_LEDGER_TABLE", "merismos-thread")
    return WorkspaceStore(boto3.client("dynamodb", region_name="eu-west-1"))


def test_deployed_store_reads_consistently_and_checks_expiry(store):
    key = store.key("session")
    args = {"TableName": store.table, "Key": key, "ConsistentRead": True}
    with Stubber(store.client) as stub:
        stub.add_response("get_item", {}, args)
        assert store.get("session") is None
        stub.add_response("get_item", {"Item": {**key, "expires": {"N": "1"},
                                                "data": {"S": "{}"}}}, args)
        assert store.get("session") is None
        stub.add_response("get_item", {"Item": {**key, "expires": {"N": "9999999999"},
                                                "data": {"S": '{"version":1}'}}}, args)
        assert store.get("session") == {"version": 1}


def test_deployed_cas_creates_then_updates_with_expected_version(store):
    state = api.initial_state("sandbox")
    with Stubber(store.client) as stub:
        stub.add_response("put_item", {}, {"TableName": store.table, "Item": ANY,
                                           "ConditionExpression": "attribute_not_exists(entry_id)"})
        saved = store.save("session", state, 0)
        assert saved["version"] == 1
        stub.add_response("put_item", {}, {"TableName": store.table, "Item": ANY,
                                           "ConditionExpression": "version = :expected",
                                           "ExpressionAttributeValues": {":expected": {"N": "1"}}})
        assert store.save("session", saved, 1)["version"] == 2


def test_deployed_cas_refuses_conflict_and_propagates_service_failure(store):
    with Stubber(store.client) as stub:
        stub.add_client_error("put_item", "ConditionalCheckFailedException")
        with pytest.raises(Conflict):
            store.save("session", {}, 0)
        stub.add_client_error("put_item", "AccessDeniedException")
        with pytest.raises(Exception, match="AccessDenied"):
            store.save("session", {}, 0)


def test_default_adapter_requires_config_and_constructs_client(monkeypatch):
    monkeypatch.delenv("MERISMOS_WORKSPACE_DB", raising=False)
    monkeypatch.delenv("MERISMOS_LEDGER_TABLE", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        _ = WorkspaceStore().client
    monkeypatch.setenv("MERISMOS_LEDGER_TABLE", "merismos-thread")
    assert WorkspaceStore().client.meta.service_model.service_name == "dynamodb"


def test_pending_action_and_expired_commitment_stay_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("MERISMOS_OFFLINE_HTTP", "1")
    monkeypatch.setenv("MERISMOS_WORKSPACE_DB", str(tmp_path / "workspace.sqlite"))
    store = WorkspaceStore()
    state = api.initial_state("sandbox")
    state["expires_at"] = time.time() - 1
    store.save("expired", state, 0)
    assert store.get("expired") is None
    assert json.loads(json.dumps(state))["mode"] == "sandbox"

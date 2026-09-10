"""Actual handler, Strands sandbox and durable storage: CSV to changed pickup plan."""

import copy
import uuid

import pytest

from merismos import api
from tests.integration.test_coordinator_api import client as client
from tests.integration.test_coordinator_api import post
from tests.unit.test_csv_intake import document, form


def imported(client):
    text = document()
    code, preview = client("/api/intake/preview", "POST", {"csv": text})
    assert code == 200
    code, answer = client("/api/offers/new", "POST", {
        "csv": text, "row": 2, "csv_digest": preview["digest"],
        "version": preview["version"], "request_id": uuid.uuid4().hex})
    assert code == 200, answer
    return next(o["offer"]["id"] for o in answer["offers"]
                if o["offer"]["title"] == "Synthetic greens")


def find(state, identifier):
    return next(o for o in state["offers"] if o["offer"]["id"] == identifier)


def test_preview_and_invalid_selection_are_side_effect_free(client, monkeypatch):
    before = client.store.get(api.fingerprint(client.handle))
    def forbidden(*args, **kwargs):
        raise AssertionError("preview cannot save or run a model")
    monkeypatch.setattr(api.WorkspaceStore, "save", forbidden)
    monkeypatch.setattr(api, "run_chore", forbidden)
    text = document(form(), form(note="Call 6941234567"), form(quantity="120.00"))
    code, preview = client("/api/intake/preview", "POST", {"csv": text})
    assert code == 200 and [r["status"] for r in preview["rows"]] == [
        "valid", "invalid", "duplicate"]
    for row in (1, 3, 4):
        code, _ = client("/api/offers/new", "POST", {
            "csv": text, "row": row, "csv_digest": preview["digest"],
            "version": preview["version"], "request_id": uuid.uuid4().hex})
        assert code == 400
    assert client.store.get(api.fingerprint(client.handle)) == before


def test_selected_row_only_replay_and_duplicate_facts_are_checked_at_commit(client):
    text = document(form(), form(title="Second donation"))
    _, preview = client("/api/intake/preview", "POST", {"csv": text})
    body = {"csv": text, "row": 3, "csv_digest": preview["digest"],
            "version": preview["version"], "request_id": uuid.uuid4().hex}
    code, after = client("/api/offers/new", "POST", body)
    assert code == 200 and after["records"] == [] and after["pickups"] == []
    assert not any(o["offer"]["title"] == "Synthetic greens" for o in after["offers"])
    assert client("/api/offers/new", "POST", body)[1]["version"] == after["version"]
    _, fresh = client("/api/intake/preview", "POST", {"csv": text})
    assert [r["status"] for r in fresh["rows"]] == ["valid", "duplicate"]
    body.update(request_id=uuid.uuid4().hex, version=after["version"])
    assert client("/api/offers/new", "POST", body)[0] == 400
    assert client()[1]["version"] == after["version"]


@pytest.mark.parametrize("path", ["/api/intake/preview", "/api/offers/new",
                                  "/api/offers/offer-4471/disrupt"])
def test_live_import_and_disruption_cannot_invent_authority(client, path):
    assert client(path, "POST", {"mode": "live", "csv": document(), "consent": True,
                                "principalId": "admin"})[0] == 403


def test_disruption_replan_preserves_prior_bytes_invalidates_claims_and_requires_fresh_approval(
    client,
):
    identifier = imported(client)
    state, _ = post(client, "run", offer=identifier)
    first = find(state, identifier)
    plan = first["plan"]
    assert len(first["result"]["draft_allocations"]) == 5
    assert "Collection capacity limit 20 kg" in next(
        a["reason"] for a in first["result"]["draft_allocations"]
        if a["org"] == "Elpida Night Shelter")
    post(client, "approve", {**plan, "consent": True}, offer=identifier)
    args = {**plan, "org": "Omonoia Soup Kitchen", "role": "kitchen lead", "action": "claim"}
    state, _ = post(client, "pickup", args, offer=identifier)
    receipt = copy.deepcopy(state["records"][0])
    original = copy.deepcopy(client.store.get(api.fingerprint(client.handle))["runs"][identifier])
    state, payload = post(client, "disrupt", {**plan, "org": args["org"], "capacity": 0,
                                            "consent": True}, offer=identifier)
    disrupted = find(state, identifier)
    assert disrupted["status"] == "needs_replan" and disrupted["plan"] is None
    assert disrupted["replan"]["before_digest"] == plan["digest"]
    assert any(p["state"] == "invalidated" for p in state["pickups"])
    saved = client.store.get(api.fingerprint(client.handle))
    assert saved["run_history"][0]["run"] == original
    assert state["records"][0] == receipt
    assert client(f"/api/offers/{identifier}/disrupt", "POST", payload)[0] == 200
    post(client, "approve", {**plan, "consent": True}, offer=identifier, expected=409)
    post(client, "pickup", {**args, "action": "confirm", "consent": True},
         offer=identifier, expected=409)
    state, _ = post(client, "run", offer=identifier)
    second = find(state, identifier)
    assert second["plan"]["digest"] != plan["digest"] and not second["plan"]["recorded"]
    assert args["org"] not in [a["org"] for a in second["result"]["draft_allocations"]]
    assert "capacity is zero" in second["result"]["draft_barred_because"][args["org"]]
    assert second["replan"]["before"]["run_id"] == original["run_id"]
    post(client, "pickup", {**args, **second["plan"]}, offer=identifier, expected=409)
    state, _ = post(client, "approve", {**second["plan"], "consent": True}, offer=identifier)
    assert len(state["records"]) == 2 and state["records"][0]["superseded_by"]
    assert state["records"][0]["content_digest"] == receipt["content_digest"]
    assert client.store.get(api.fingerprint(client.handle))["run_history"][0]["run"] == original
    # The unrelated original demonstration and all real/public state are untouched.
    assert find(state, "offer-4471")["result"] == {}


@pytest.mark.parametrize("change", [{"consent": False}, {"capacity": -1}, {"capacity": True},
                                   {"capacity": 1000}, {"capacity": "0"}, {"capacity": 0.001},
                                   {"org": "Unknown"}])
def test_invalid_disruption_cannot_change_original_state(client, change):
    identifier = imported(client)
    state, _ = post(client, "run", offer=identifier)
    plan = find(state, identifier)["plan"]
    before = client.store.get(api.fingerprint(client.handle))
    post(client, "disrupt", {**plan, "org": "Omonoia Soup Kitchen", "capacity": 0,
                             "consent": True, **change}, offer=identifier, expected=400)
    assert client.store.get(api.fingerprint(client.handle)) == before


def test_a_confirmed_pickup_cannot_be_disrupted(client):
    identifier = imported(client)
    state, _ = post(client, "run", offer=identifier)
    plan = find(state, identifier)["plan"]
    post(client, "approve", {**plan, "consent": True}, offer=identifier)
    args = {**plan, "org": "Omonoia Soup Kitchen", "role": "kitchen lead"}
    post(client, "pickup", {**args, "action": "claim"}, offer=identifier)
    post(client, "pickup", {**args, "action": "confirm", "consent": True}, offer=identifier)
    post(client, "disrupt", {**args, "capacity": 0, "consent": True},
         offer=identifier, expected=409)

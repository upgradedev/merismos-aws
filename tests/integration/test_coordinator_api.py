"""The JSON boundary, real offline Strands loop and durable CAS persistence."""

import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from merismos import api, handler, pickup
from merismos.approval import InMemoryApprovalStore
from merismos.ledger import Thread, ledger_from_env, reset_memory_ledger
from merismos.workspace_store import Conflict, WorkspaceStore


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MERISMOS_OFFLINE_HTTP", "1")
    monkeypatch.setenv("MERISMOS_WORKSPACE_DB", str(tmp_path / "workspace.sqlite"))
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_MODEL", "scripted")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    reset_memory_ledger()
    handle = ""

    def call(path="/api/workspace", method="GET", data=None, token=None, context=None):
        response = handler.handler({"requestContext": {
            "http": {"method": method, "path": path}, **(context or {})},
            "headers": {"x-merismos-session": handle if token is None else token},
            "body": json.dumps({"mode": "sandbox", **(data or {})})})
        return response["statusCode"], json.loads(response["body"])

    code, created = call("/api/sessions", "POST")
    assert code == 201
    handle = created["session"]
    call.handle = handle
    call.store = WorkspaceStore()
    return call


def post(client, kind, extra=None, offer="offer-4471", expected=200):
    _, state = client()
    payload = {"version": state["version"], "request_id": uuid.uuid4().hex, **(extra or {})}
    code, answer = client(f"/api/offers/{offer}/{kind}", "POST", payload)
    assert code == expected, answer
    return answer, payload


def plan(client):
    state, _ = post(client, "run")
    result = next(o for o in state["offers"] if o["offer"]["id"] == "offer-4471")
    assert result["result"]["outcome"] == "awaiting_approval", result
    return result["plan"]


def approved(client):
    current = plan(client)
    post(client, "approve", {**current, "consent": True})
    return current


def test_real_strands_split_exact_consent_and_durable_collection(client):
    current = approved(client)
    args = {**current, "org": "Omonoia Soup Kitchen", "role": "kitchen lead", "action": "claim"}
    state, payload = post(client, "pickup", args)
    assert next(p for p in state["pickups"] if p["org"] == args["org"])["quantity"] == 96
    version = state["version"]
    code, replay = client("/api/offers/offer-4471/pickup", "POST", payload)
    assert code == 200 and replay["version"] == version
    when = datetime.fromtimestamp(time.time() + 3600, timezone.utc).isoformat()
    state, _ = post(client, "pickup", {**args, "action": "schedule", "agreed_at": when})
    assert any(p["state"] == "scheduled" for p in state["pickups"])
    state, _ = post(client, "pickup", {**args, "action": "confirm", "consent": True})
    assert any(p["state"] == "confirmed" for p in state["pickups"])
    post(client, "pickup", {**args, "action": "confirm", "consent": True}, expected=409)
    post(client, "run", expected=409)
    persisted = WorkspaceStore().get(api.fingerprint(client.handle))
    assert len(persisted["records"]) == 1
    assert len(persisted["claims"]) == 1
    assert "strands" in json.dumps(persisted["runs"]).lower() or any(
        e["kind"] == "specialist.answered" for e in persisted["runs"]["offer-4471"]["entries"])


@pytest.mark.parametrize("edit,code", [
    ({"digest": "wrong"}, 409), ({"run_id": "wrong"}, 409),
    ({"key": "records/other.md"}, 400), ({"consent": False}, 400),
])
def test_approval_is_exact_and_requires_explicit_consent(client, edit, code):
    current = plan(client)
    post(client, "approve", {**current, "consent": True, **edit}, expected=code)
    assert client()[1]["records"] == []


def test_unknown_stale_and_reused_request_ids_are_refused(client):
    current = plan(client)
    post(client, "approve", {**current, "consent": True, "version": 0}, expected=409)
    _, state = client()
    data = {**current, "consent": True, "version": state["version"], "request_id": "bad"}
    assert client("/api/offers/offer-4471/approve", "POST", data)[0] == 400
    _, payload = post(client, "approve", {**current, "consent": True})
    assert client("/api/offers/offer-4471/approve", "POST", {**payload, "key": "changed"})[0] == 409
    post(client, "approve", {**current, "consent": True}, expected=409)


def test_session_isolation_expiry_unknown_routes_and_role(client, monkeypatch):
    assert client(token="")[0] == 401
    assert client(token="x" * 43)[0] == 410
    assert client(data={"mode": "unknown"})[0] == 400
    assert client("/api/missing")[0] == 404
    assert client("/api/offers/offer-999999")[0] == 404
    assert client("/api/offers/offer-4471/run")[0] == 405
    assert client("/api/offers/offer-4471")[0] == 200
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    assert client()[0] == 403


def test_anonymous_live_writes_fail_even_with_forged_identity_fields(client):
    code, answer = client("/api/offers/offer-4471/run", "POST", {
        "mode": "live", "version": 0, "request_id": uuid.uuid4().hex,
        "principalId": "admin", "permissions": ["merismos:coordinate"],
    })
    assert code == 403 and "authenticated" in answer["detail"]
    assert client(data={"mode": "live"})[1]["can_write"] is False


def test_changed_evidence_and_recomputed_plan_invalidate_claims(client):
    current = approved(client)
    args = {**current, "org": "Omonoia Soup Kitchen", "role": "duty manager", "action": "claim"}
    post(client, "pickup", args)
    state = client.store.get(api.fingerprint(client.handle))
    document = json.loads(state["files"]["offers/offer-4471.json"])
    document["quantity"] = 200
    state["files"]["offers/offer-4471.json"] = json.dumps(document)
    client.store.save(api.fingerprint(client.handle), state, state["version"])
    post(client, "pickup", {**args, "action": "confirm", "consent": True}, expected=409)
    new = plan(client)
    assert new["digest"] != current["digest"]
    state, _ = post(client, "approve", {**new, "consent": True})
    assert any(p["state"] == "invalidated" for p in state["pickups"])
    assert any(r["superseded_by"] for r in state["records"])
    assert state["records"][0]["content_digest"] == current["digest"]


@pytest.mark.parametrize("args,status", [
    ({"action": "claim", "role": "person name"}, 400),
    ({"action": "claim", "role": "duty manager", "org": "Unknown organisation"}, 400),
    ({"action": "confirm", "consent": True}, 409),
])
def test_pickup_refuses_unknown_org_role_and_unclaimed_confirmation(client, args, status):
    current = approved(client)
    post(client, "pickup", {**current, "org": "Omonoia Soup Kitchen", **args}, expected=status)


@pytest.mark.parametrize("when", ["", "bad", "2020-01-01T00:00:00Z", "2090-01-01T00:00:00Z",
                                  "2026-09-10T10:00:00"])
def test_schedule_requires_timezone_and_a_near_future_time(client, when):
    current = approved(client)
    args = {**current, "org": "Omonoia Soup Kitchen", "role": "duty manager"}
    post(client, "pickup", {**args, "action": "claim"})
    post(client, "pickup", {**args, "action": "schedule", "agreed_at": when}, expected=400)
    post(client, "pickup", {**args, "action": "confirm", "consent": False}, expected=400)
    post(client, "pickup", {**args, "action": "unexpected"}, expected=400)


def test_claim_before_approval_and_duplicate_claim_are_refused(client):
    current = plan(client)
    args = {**current, "org": "Omonoia Soup Kitchen", "role": "duty manager", "action": "claim"}
    post(client, "pickup", args, expected=409)
    post(client, "approve", {**current, "consent": True})
    post(client, "pickup", args)
    post(client, "pickup", args, expected=409)


def test_safety_refusal_has_no_approval_path(client):
    state, _ = post(client, "run", offer="offer-4477")
    row = next(o for o in state["offers"] if o["offer"]["id"] == "offer-4477")
    assert row["status"] == "blocked" and row["plan"] is None
    assert "cold" in row["result"]["note"].lower()


def test_add_offer_uses_existing_validation_and_flows_to_the_fleet(client):
    form = {"title": "Synthetic bread", "donor": "Demo bakery", "quantity": "120.25",
            "unit": "kg", "category": "ambient", "collection_date": "2026-09-12",
            "use_by": "2026-09-14", "allergens": "gluten", "note": "Collect before evening."}
    _, state = client()
    payload = {"version": state["version"], "request_id": uuid.uuid4().hex, "form": form}
    code, added = client("/api/offers/new", "POST", payload)
    assert code == 200, added
    new = next(o for o in added["offers"] if o["offer"]["title"] == form["title"])
    assert new["offer"]["quantity"] == 120.25
    state, _ = post(client, "run", offer=new["offer"]["id"])
    assert next(o for o in state["offers"] if o["offer"]["id"] == new["offer"]["id"])["plan"]
    payload.update(version=state["version"], request_id=uuid.uuid4().hex,
                   form={**form, "note": "call 6941234567"})
    assert client("/api/offers/new", "POST", payload)[0] == 400
    payload.update(request_id=uuid.uuid4().hex, form={**form, "allergens": "a@example.invalid"})
    assert client("/api/offers/new", "POST", payload)[0] == 400


def test_expired_pending_and_full_sessions_refuse_without_fabricating_success(client):
    store, key = client.store, api.fingerprint(client.handle)
    state = store.get(key)
    state["operations"] = {str(i): {} for i in range(100)}
    store.save(key, state, state["version"])
    post(client, "run", expected=409)
    state = store.get(key)
    state["expires_at"] = 1
    store.save(key, state, state["version"])
    assert client()[0] == 410


def test_public_text_refuses_pii_and_confirmed_history_does_not_expire():
    assert "withheld" in api.safe_text("call 6941234567")
    result = api.public_result({"draft_body": "Email a@example.invalid"})
    assert result["outcome"] == "refused_by_gate"
    claim = pickup.Claim("offer-1", "Kitchen", "duty manager", 10, "kg", "digest",
                         claimed_at=1, confirmed_at=2)
    assert pickup.still_valid(claim, "digest", now=10**10)


def test_sqlite_cas_survives_new_adapter_and_refuses_races(client):
    store = WorkspaceStore()
    state = api.initial_state("sandbox")
    saved = store.save("other", state, 0)
    assert WorkspaceStore().get("other") == saved
    with pytest.raises(Conflict):
        store.save("other", state, 0)
    with pytest.raises(Conflict):
        store.save("other", state, 3)
    with pytest.raises(ValueError, match="full"):
        store.save("big", {"large": "x" * 350_001}, 0)


def test_sqlite_cannot_be_implicitly_enabled(monkeypatch):
    monkeypatch.setenv("MERISMOS_WORKSPACE_DB", "unused")
    monkeypatch.delenv("MERISMOS_OFFLINE_HTTP", raising=False)
    with pytest.raises(RuntimeError, match="explicit"):
        WorkspaceStore()


def test_an_unrelated_offer_does_not_invalidate_an_approved_pickup(client):
    current = approved(client)
    _, state = client()
    payload = {"version": state["version"], "request_id": uuid.uuid4().hex,
               "form": {"title": "Other synthetic donation", "donor": "Demo shop",
                        "quantity": "50", "collection_date": "2026-09-14"}}
    assert client("/api/offers/new", "POST", payload)[0] == 200
    post(client, "pickup", {**current, "org": "Omonoia Soup Kitchen",
                             "role": "duty manager", "action": "claim"})
    post(client, "pickup", {**current, "org": "Omonoia Soup Kitchen",
                             "action": "confirm", "consent": True})


def test_live_authorized_journey_uses_the_separate_writer_and_never_overwrites(client, monkeypatch):
    """Real handler on both sides of a local Lambda transport, no live AWS call."""
    import io
    import os

    import boto3

    state = client.store.get(api.fingerprint(client.handle))
    files = state["files"]
    offer = json.loads(files["offers/offer-4471.json"])
    offer["collection_date"] = (date.today() + timedelta(days=1)).isoformat()
    offer["use_by"] = (date.today() + timedelta(days=2)).isoformat()
    files["offers/offer-4471.json"] = json.dumps(offer)
    corpus = api.SnapshotCorpus(files)
    monkeypatch.setattr(api, "corpus_from_env", lambda: corpus)
    monkeypatch.setattr(handler, "corpus_from_env", lambda: corpus)
    approvals = InMemoryApprovalStore()
    monkeypatch.setattr(api, "ApprovalStore", lambda: approvals)
    monkeypatch.setattr(handler, "ApprovalStore", lambda: approvals)
    monkeypatch.setenv("MERISMOS_WRITER_FUNCTION", "offline-writer")
    monkeypatch.setenv("MERISMOS_RECORDS_BUCKET", "offline-records")
    writes = []

    class Transport:
        def invoke(self, FunctionName, Payload):  # noqa: N803
            assert FunctionName == "offline-writer"
            previous = os.environ.get("MERISMOS_ROLE")
            os.environ["MERISMOS_ROLE"] = "writer"
            try:
                response = handler.handler(json.loads(Payload))
            finally:
                os.environ["MERISMOS_ROLE"] = previous
            return {"Payload": io.BytesIO(json.dumps(response).encode())}

        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            assert not any(w["Key"] == kwargs["Key"] for w in writes)
            writes.append(kwargs)

    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: Transport())

    def finish(offer_id, run_id, network):
        thread = Thread(ledger_from_env(), api.subject_for_offer(network, offer), run_id)
        result = api.run_chore(corpus, offer, thread, analyst=api.bedrock.scripted_analyst())
        thread.append("run.completed", **result.as_dict())

    monkeypatch.setattr(api.background, "start", finish)
    context = {"authorizer": {"lambda": {"network": handler.NETWORK,
               "principalId": "trusted-user", "permissions": ["merismos:coordinate"]}}}

    def live(kind, extra=None):
        _, current = client(data={"mode": "live"}, context=context)
        return client(f"/api/offers/offer-4471/{kind}", "POST", {
            "mode": "live", "version": current["version"],
            "request_id": uuid.uuid4().hex, **(extra or {}),
        }, context=context)

    code, current = live("run")
    assert code == 200, current
    exact = next(o for o in current["offers"] if o["offer"]["id"] == offer["id"])["plan"]
    code, published = live("approve", {**exact, "consent": True})
    assert code == 200, published
    assert len(writes) == 1 and writes[0]["Body"].decode() == exact["body"]
    assert len(published["records"]) == 1
    assert "trusted-user" not in json.dumps(published)
    assert live("approve", {**exact, "consent": True})[0] == 409
    code, result = live("pickup", {**exact, "action": "claim",
                                    "org": "Omonoia Soup Kitchen", "role": "duty manager"})
    assert code == 200, result


def test_outcome_unknown_is_not_retried_and_new_actions_are_held(client, monkeypatch):
    monkeypatch.setattr(api.bedrock, "scripted_analyst", lambda: (_ for _ in ()).throw(
        RuntimeError("offline agent unavailable")))
    state, payload = post(client, "run", expected=500)
    assert state["detail"] == "RuntimeError"
    code, answer = client("/api/offers/offer-4471/run", "POST", payload)
    assert code == 409 and "unknown" in answer["detail"]
    post(client, "run", expected=409)


def test_overdue_and_expired_claims_have_distinct_states(client):
    current = approved(client)
    args = {**current, "org": "Omonoia Soup Kitchen", "role": "duty manager", "action": "claim"}
    post(client, "pickup", args)
    key = api.fingerprint(client.handle)
    state = client.store.get(key)
    state["claims"][0]["agreed_at"] = datetime.fromtimestamp(
        time.time() - 60, timezone.utc).isoformat()
    client.store.save(key, state, state["version"])
    assert any(p["state"] == "overdue" for p in client()[1]["pickups"])
    state = client.store.get(key)
    state["claims"][0]["claimed_at"] = time.time() - 15 * 86400
    client.store.save(key, state, state["version"])
    assert any(p["state"] == "invalidated" for p in client()[1]["pickups"])
    post(client, "pickup", {**args, "action": "confirm", "consent": True}, expected=409)

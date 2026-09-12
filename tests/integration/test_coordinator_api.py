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


def test_correlation_is_not_business_idempotency_or_coordinator_authority(client):
    current = plan(client)
    _, state = client()
    payload = {"mode": "sandbox", "version": state["version"],
               "request_id": uuid.uuid4().hex, **current, "consent": True}
    event = {"httpMethod": "POST", "path": "/api/offers/offer-4471/approve",
             "headers": {"x-merismos-session": client.handle,
                         "x-merismos-request-id": "caller-correlation-not-authority",
                         "x-merismos-lambda-request-id": "caller-correlation-not-authority"},
             "body": json.dumps(payload)}
    first, replay = handler.handler(event), handler.handler(event)
    assert first["statusCode"] == replay["statusCode"] == 200
    assert json.loads(first["body"]) == json.loads(replay["body"])
    assert first["headers"]["x-merismos-request-id"] != replay["headers"][
        "x-merismos-request-id"]
    assert "x-merismos-lambda-request-id" not in replay["headers"]
    assert len(client()[1]["records"]) == 1
    event["body"] = json.dumps({**payload, "mode": "live"})
    assert handler.handler(event)["statusCode"] == 403
    assert len(client()[1]["records"]) == 1


@pytest.mark.parametrize("seconds_after_expiry,expected", [(-1, 200), (0, 410), (137, 410)])
def test_aged_session_boundary_preserves_bytes_and_requires_explicit_restart(
        client, monkeypatch, seconds_after_expiry, expected):
    """Age actual persisted session expiry, not a browser label or an unknown token."""
    identifier = api.fingerprint(client.handle)
    state = client.store.get(identifier)
    with client.store.connection() as db:
        before = db.execute("SELECT * FROM workspace WHERE id = ?", (identifier,)).fetchone()
    with monkeypatch.context() as aged:
        aged.setattr(time, "time", lambda: state["expires_at"] + seconds_after_expiry)
        saves = []

        def refuse_save(*args, **kwargs):
            saves.append(args)
            raise AssertionError("Reading or refusing expired access must never save")

        aged.setattr(WorkspaceStore, "save", refuse_save)
        assert client()[0] == expected
        if expected == 410:
            assert client("/api/offers/new", "POST", {"request_id": uuid.uuid4().hex})[0] == 410
        assert saves == []
    with client.store.connection() as db:
        assert db.execute("SELECT * FROM workspace WHERE id = ?", (identifier,)).fetchone() == before
    code, new_session = client("/api/sessions", "POST")
    assert code == 201 and new_session["session"] != client.handle
    code, fresh = client(token=new_session["session"])
    assert code == 200
    assert fresh["records"] == fresh["pickups"] == fresh["operations"] == []
    assert client.store.get(identifier) == state


def test_withdrawn_workspace_access_does_not_recreate_or_write(client, monkeypatch):
    """Store-level absent access shares the existing unknown/expired contract."""
    identifier = api.fingerprint(client.handle)
    original_get = WorkspaceStore.get
    original_state = client.store.get(identifier)
    with monkeypatch.context() as withdrawn:
        withdrawn.setattr(WorkspaceStore, "get", lambda self, key: None if key == identifier else original_get(self, key))
        assert client()[0] == 410
        assert client("/api/offers/new", "POST", {"request_id": uuid.uuid4().hex})[0] == 410
    assert client.store.get(identifier) == original_state


def test_missing_unknown_sessions_routes_and_role(client, monkeypatch):
    assert client(token="")[0] == 401
    assert client(token="x" * 43)[0] == 410
    assert client(data={"mode": "unknown"})[0] == 400
    assert client("/api/missing")[0] == 404
    assert client("/api/offers/offer-999999")[0] == 404
    assert client("/api/offers/offer-4471/run")[0] == 405
    assert client("/api/offers/offer-4471")[0] == 200
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    assert client()[0] == 403


def test_two_valid_sandbox_sessions_isolate_state_plans_and_request_replays(client, monkeypatch):
    """Real handler + SQLite: unknown-token refusal is not session isolation.

    B first stays empty throughout A's intake/run/approval. Then B explicitly
    files its own different donation at the same session-local offer address,
    so cross-session refusals must reach plan validation, not just a missing ID.
    """
    code, created = client("/api/sessions", "POST")
    assert code == 201
    session_a, session_b = client.handle, created["session"]
    assert session_a != session_b
    key_a, key_b = map(api.fingerprint, (session_a, session_b))

    def read(token):
        status, state = client(token=token)
        assert status == 200, state
        assert state["mode"] == "sandbox" and state["can_write"] is True
        return state

    writes = []
    real_save = WorkspaceStore.save

    def observed_save(store, identifier, state, expected):
        writes.append(identifier)
        return real_save(store, identifier, state, expected)

    monkeypatch.setattr(WorkspaceStore, "save", observed_save)
    baseline_b, stored_b = read(session_b), client.store.get(key_b)
    assert stored_b is not None
    assert stored_b["runs"] == stored_b["operations"] == {}
    assert stored_b["records"] == stored_b["claims"] == []
    assert all(row["plan"] is None and row["result"] == {} for row in baseline_b["offers"])

    def unchanged_b():
        assert read(session_b) == baseline_b
        assert client.store.get(key_b) == stored_b

    def send(token, path, extra=None):
        payload = {"version": read(token)["version"], "request_id": uuid.uuid4().hex,
                   **(extra or {})}
        status, state = client(path, "POST", payload, token=token)
        assert status == 200, state
        return state, payload

    today = datetime.now(timezone.utc).date()
    form = {"title": "Synthetic session bread", "donor": "Demonstration bakery",
            "quantity": "120.25", "unit": "kg", "category": "ambient",
            "collection_date": (today + timedelta(days=2)).isoformat(),
            "use_by": (today + timedelta(days=4)).isoformat(),
            "allergens": "gluten", "note": "Invented donation; collect before evening."}
    added_a, _ = send(session_a, "/api/offers/new", {"form": form})
    offer_id = next(row["offer"]["id"] for row in added_a["offers"]
                    if row["offer"]["title"] == form["title"])
    assert offer_id not in {row["offer"]["id"] for row in baseline_b["offers"]}
    unchanged_b()
    path = f"/api/offers/{offer_id}"
    planned_a, run_request = send(session_a, path + "/run")
    plan_a = next(row["plan"] for row in planned_a["offers"] if row["offer"]["id"] == offer_id)
    assert plan_a and not plan_a["recorded"]
    unchanged_b()
    approved_a, approval_request = send(session_a, path + "/approve",
                                        {**plan_a, "consent": True})
    assert len(approved_a["records"]) == 1
    assert approved_a["records"][0]["content_digest"] == plan_a["digest"]
    assert approved_a["records"][0]["mode"] == "sandbox"
    unchanged_b()
    assert writes and set(writes) == {key_a}

    def refused_without_write(payload, expected=409, action="approve"):
        before_a = client.store.get(key_a)
        before_writes = list(writes)
        status, error = client(path + "/" + action, "POST",
                               {**payload, "version": baseline_b["version"]}, token=session_b)
        assert status == expected, error
        assert error["detail"] == ("No such offer." if expected == 404 else
                                   "This plan is stale. Refresh and review the allocation again.")
        # Pass-through spy observes the actual writer lifecycle, not a stubbed response.
        assert writes == before_writes
        unchanged_b()
        assert client.store.get(key_a) == before_a

    refused_without_write(approval_request, expected=404)

    # B's only changes below are these explicit, legitimate positive controls.
    added_b, _ = send(session_b, "/api/offers/new", {
        "form": {**form, "title": "Synthetic session vegetables", "quantity": "90.25"}})
    assert next(row for row in added_b["offers"] if row["offer"]["id"] == offer_id)["plan"] is None
    baseline_b, stored_b = read(session_b), client.store.get(key_b)
    assert stored_b["runs"] == {} and stored_b["records"] == stored_b["claims"] == []
    # Same A approval request ID, exact B version and an existing offer: neither
    # expired-session, missing-offer nor stale-version rejection can pass this check.
    refused_without_write(approval_request)

    planned_b, _ = send(session_b, path + "/run")
    plan_b = next(row["plan"] for row in planned_b["offers"] if row["offer"]["id"] == offer_id)
    assert plan_b and not plan_b["recorded"]
    assert plan_a["run_id"] != plan_b["run_id"]
    assert plan_a["digest"] != plan_b["digest"]
    # Record addresses are workspace-local, not global authority.
    assert plan_a["key"] == plan_b["key"]
    baseline_b, stored_b = read(session_b), client.store.get(key_b)
    for foreign in (approval_request,
                    {**plan_b, "run_id": plan_a["run_id"], "consent": True},
                    {**plan_b, "digest": plan_a["digest"], "consent": True}):
        refused_without_write({"request_id": uuid.uuid4().hex, **foreign})
    refused_without_write({**approval_request, "action": "claim", "role": "duty manager",
                           "org": approved_a["pickups"][0]["org"]}, action="pickup")

    before_a, before_writes = client.store.get(key_a), list(writes)
    for action, payload in (("run", run_request), ("approve", approval_request)):
        status, replay = client(path + "/" + action, "POST", payload, token=session_a)
        assert status == 200 and replay == approved_a
        assert client.store.get(key_a) == before_a
        unchanged_b()
        assert writes == before_writes
    assert baseline_b["records"] == baseline_b["pickups"] == []
    assert approval_request["request_id"] not in stored_b["operations"]
    assert run_request["request_id"] not in stored_b["operations"]


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


def test_public_result_checks_exported_prose_not_internal_timing_and_hashes():
    result = {"outcome": "awaiting_approval", "draft_body": "Synthetic food split.",
              "run_id": "run-694123456789", "reads": {"at": 1788940271.694123},
              "envelopes": [{"specialist": "fairness", "status": "ok",
                             "meta": {"digest": "694123456789"}}]}
    public = api.public_result(result)
    assert public["outcome"] == "awaiting_approval"
    assert "reads" not in public and "meta" not in public["envelopes"][0]
    result["envelopes"][0]["reason"] = "Call 6941234567"
    assert api.public_result(result)["outcome"] == "refused_by_gate"


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


@pytest.mark.parametrize("percentage", [25, 12.5])
def test_api_projects_the_applied_network_ceiling_without_rounding(client, percentage):
    key = api.fingerprint(client.handle)
    state = client.store.get(key)
    path = "registers/allocation-policy.md"
    state["files"][path] = state["files"][path].replace("**40%**", f"**{percentage}%**")
    client.store.save(key, state, state["version"])
    response, _ = post(client, "run")
    row = next(o for o in response["offers"] if o["offer"]["id"] == "offer-4471")
    assert row["result"]["fairness_cap"] == {"share": percentage / 100, "source": path}
    assert all("meta" not in e for e in row["result"]["envelopes"])


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


def test_known_sandbox_failure_requires_a_reviewed_new_request(client, monkeypatch):
    analyst = api.bedrock.scripted_analyst
    monkeypatch.setattr(api.bedrock, "scripted_analyst", lambda: (_ for _ in ()).throw(
        RuntimeError("offline agent unavailable")))
    state, payload = post(client, "run", expected=500)
    assert state["detail"] == "RuntimeError"
    code, answer = client("/api/offers/offer-4471/run", "POST", payload)
    assert code == 409 and "failed before a write" in answer["detail"]
    assert client()[1]["records"] == []
    monkeypatch.setattr(api.bedrock, "scripted_analyst", analyst)
    post(client, "run")


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


def test_handoff_reports_preserve_observations_without_confirming_collection(client):
    current = approved(client)
    args = {**current, "org": "Omonoia Soup Kitchen", "role": "duty manager"}
    post(client, "pickup", {**args, "action": "claim"})
    report = {**args, "action": "feedback", "feedback": "driver_ready", "consent": True}
    post(client, "pickup", {**report, "consent": False}, expected=400)
    post(client, "pickup", {**report, "role": "a real name"}, expected=400)
    state, _ = post(client, "pickup", report)
    item = next(p for p in state["pickups"] if p["org"] == args["org"])
    assert item["state"] == "claimed" and item["confirmed_at"] is None
    assert item["feedback"][0]["code"] == "driver_ready"
    post(client, "pickup", report, expected=409)
    post(client, "pickup", {**report, "feedback": "no_show"}, expected=409)
    key = api.fingerprint(client.handle)
    saved = client.store.get(key)
    saved["claims"][0]["agreed_at"] = datetime.fromtimestamp(
        time.time() - 60, timezone.utc).isoformat()
    client.store.save(key, saved, saved["version"])
    state, _ = post(client, "pickup", {**report, "feedback": "no_show"})
    item = next(p for p in state["pickups"] if p["org"] == args["org"])
    assert item["state"] == "overdue" and item["confirmed_at"] is None
    state, _ = post(client, "pickup", {**args, "action": "confirm", "consent": True})
    item = next(p for p in state["pickups"] if p["org"] == args["org"])
    assert item["state"] == "confirmed"
    assert [r["code"] for r in item["feedback"]] == ["driver_ready", "no_show"]

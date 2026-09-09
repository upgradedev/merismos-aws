"""Publication identity, real receipt shape, recovery and history boundaries."""

import io
import json
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from botocore.exceptions import ClientError

from merismos import api, custody, handler
from merismos.approval import InMemoryApprovalStore, grant, published_history
from merismos.corpus import LocalCorpus, offers
from merismos.fleet import _took_last_two, record_key, run_chore, subject_for_offer
from merismos.ledger import InMemoryLedger, Thread
from tests.integration.test_coordinator_api import client as client
from tests.integration.test_coordinator_api import plan, post


@pytest.mark.parametrize("path", ["/approve/offer-4471", "/approve/offer-4471/",
                                 "/offers/new", "/offer/offer-4471", "/run"])
@pytest.mark.parametrize("encoding", ["json", "form", "base64"])
def test_every_public_legacy_mutation_refuses_forged_identity(path, encoding, monkeypatch):
    import base64
    from urllib.parse import urlencode

    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: pytest.fail("writer reached"))
    body = {"approved_by": "coordinator", "principalId": "admin", "consent": True}
    event = {"requestContext": {"http": {"method": "POST", "path": path}},
             "body": json.dumps(body), "headers": {"content-type": "application/json"}}
    if encoding == "form":
        event["headers"]["content-type"] = "application/x-www-form-urlencoded"
        event["body"] = urlencode(body)
    elif encoding == "base64":
        event["isBase64Encoded"] = True
        event["body"] = base64.b64encode(event["body"].encode()).decode()
    assert handler.handler(event)["statusCode"] == 403


@pytest.mark.parametrize("verdict", [None, {}, {"passed": False}, {"passed": "true"}])
def test_a_draft_body_is_not_a_passing_plan(client, verdict):
    current = plan(client)
    key = api.fingerprint(client.handle)
    saved = client.store.get(key)
    saved["runs"]["offer-4471"]["result"]["verdict"] = verdict
    client.store.save(key, saved, saved["version"])
    assert client()[1]["offers"][0]["plan"] is None
    post(client, "approve", {**current, "consent": True}, expected=409)


@pytest.fixture
def writer(monkeypatch):
    corpus = api.SnapshotCorpus(api.snapshot(LocalCorpus()))
    offer = offers(corpus)[0]
    tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
    offer.update(collection_date=tomorrow.isoformat(),
                 use_by=(tomorrow + timedelta(days=2)).isoformat())
    corpus.files[f"offers/{offer['id']}.json"] = json.dumps(offer)
    ledger, approvals, objects = InMemoryLedger(), InMemoryApprovalStore(), {}
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_RECORDS_BUCKET", "fixture-records")
    monkeypatch.setattr(handler, "corpus_from_env", lambda: corpus)
    monkeypatch.setattr(handler, "ledger_from_env", lambda: ledger)
    monkeypatch.setattr(api, "ledger_from_env", lambda: ledger)
    monkeypatch.setattr(handler, "ApprovalStore", lambda: approvals)

    class Storage:
        failure = ""
        writes = 0

        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            if self.failure or kwargs["Key"] in objects:
                raise ClientError({"Error": {"Code": self.failure or "PreconditionFailed"}},
                                  "PutObject")
            self.writes += 1
            objects[kwargs["Key"]] = {**kwargs, "LastModified": datetime.now(timezone.utc)}

        def get_object(self, Bucket, Key):  # noqa: N803
            obj = objects[Key]
            return {**obj, "Body": io.BytesIO(obj["Body"])}

    storage = Storage()
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: storage)

    def prepare(run="run-first", key=None):
        thread = Thread(ledger, subject_for_offer(handler.NETWORK, offer), run)
        thread.append("run.started")
        result = run_chore(corpus, offer, thread)
        thread.append("run.completed", **result.as_dict())
        history = [entry.body for entry in published_history(ledger, handler.NETWORK, [offer])]
        approval = grant(handler.NETWORK, key or record_key(offer["id"], history),
                         result.draft.body, "coordinator:trusted", run,
                         evidence_digest=api.evidence_digest(
                             corpus, offer, api.fairness_history(
                                 {"mode": "live"}, handler.NETWORK, offer)),
                         offer_id=offer["id"], category=offer["category"],
                         orgs=tuple(a["org"] for a in result.draft.allocations))
        approvals.put(approval)
        return approval, {"nonce": approval.nonce, "key": approval.key, "body": result.draft.body}

    return prepare, storage, objects, ledger, corpus, offer


def test_actual_writer_receipt_correction_keeps_original_bytes_and_custody(writer):
    prepare, storage, objects, ledger, _, offer = writer
    first, payload = prepare()
    assert handler.publish(payload)["statusCode"] == 200
    original = objects[first.key]["Body"]
    second, correction = prepare("run-correction")
    assert second.key == "records/offer-4471-c2.md"
    assert handler.publish(correction)["statusCode"] == 200
    assert objects[first.key]["Body"] == original
    receipts = published_history(ledger, handler.NETWORK, [offer])
    assert all(e.subject == handler.NETWORK for e in receipts)
    assert all(e.body["category"] == offer["category"] and e.body["orgs"] for e in receipts)
    assert custody.summary(offer["id"], ledger.thread(second.run_id))["verified"]
    assert storage.writes == 2


def test_competing_approvals_cannot_overwrite_even_without_optional_api_body_field(writer):
    prepare, storage, objects, _, _, _ = writer
    first, payload = prepare()
    _, competitor = prepare("run-other", key=first.key)
    assert handler.publish(payload)["statusCode"] == 200
    original = objects[first.key]["Body"]
    refused = handler.publish(competitor)
    assert refused["statusCode"] == 409
    assert json.loads(refused["body"])["write_state"] == "not_written"
    assert objects[first.key]["Body"] == original and storage.writes == 1


def test_saved_object_after_receipt_failure_reconciles_without_second_write(writer, monkeypatch):
    prepare, storage, _, ledger, _, offer = writer
    approval, payload = prepare()
    append = handler._append_receipt
    monkeypatch.setattr(handler, "_append_receipt", lambda _: (_ for _ in ()).throw(
        RuntimeError("receipt unavailable")))
    with pytest.raises(RuntimeError):
        handler.publish(payload)
    monkeypatch.setattr(handler, "_append_receipt", append)
    for _ in range(2):
        response = handler.publication_status({"nonce": approval.nonce})
        assert json.loads(response["body"])["state"] == "recorded"
    assert storage.writes == 1
    assert len(published_history(ledger, handler.NETWORK, [offer])) == 1


def test_unknown_or_mismatched_object_is_not_reported_as_published(writer):
    prepare, storage, objects, _, _, _ = writer
    approval, payload = prepare()
    assert json.loads(handler.publication_status({"nonce": approval.nonce})["body"])[
        "state"] == "unknown"
    assert handler.publish(payload)["statusCode"] == 200
    objects[approval.key]["Metadata"]["approval-nonce"] = "different"
    assert json.loads(handler.publication_status({"nonce": approval.nonce})["body"])[
        "state"] == "unknown"
    assert storage.writes == 1


def test_receipt_history_rotates_distinct_offers_only_and_preserves_other_category():
    receipts = [{"offer_id": "offer-3", "category": "ambient", "orgs": ["Kitchen"]},
                {"offer_id": "offer-3", "category": "ambient", "orgs": ["Kitchen"]},
                {"offer_id": "offer-2", "category": "ambient", "orgs": ["Kitchen"]}]
    assert _took_last_two(receipts[:2], "ambient") == []
    assert _took_last_two(receipts, "ambient") == ["Kitchen"]
    assert _took_last_two(receipts, "produce") == []


def test_three_same_category_runs_use_saved_writer_receipts_and_keep_the_cap(writer):
    prepare, _, _, ledger, corpus, offer = writer
    for index in range(2):
        offer["id"] = f"offer-{5000 + index}"
        corpus.files[f"offers/{offer['id']}.json"] = json.dumps(offer)
        _, payload = prepare(f"run-donation-{index}")
        assert handler.publish(payload)["statusCode"] == 200
    receipts = [entry.body for entry in published_history(ledger, handler.NETWORK, [offer])]
    assert len(receipts) == 2
    assert {r["offer_id"] for r in receipts} == {"offer-5000", "offer-5001"}
    offer["id"] = "offer-5002"
    corpus.files["offers/offer-5002.json"] = json.dumps(offer)
    thread = Thread(ledger, subject_for_offer(handler.NETWORK, offer), "run-donation-third")
    third = run_chore(corpus, offer, thread, network=handler.NETWORK)
    equity = next(envelope for envelope in third.envelopes if envelope.specialist == "equity")
    assert equity.meta["back_of_queue"]
    assert equity.meta["ceiling_share"] == 0.4
    assert all(a["quantity"] <= offer["quantity"] * 0.4 for a in third.draft.allocations)
    other = {**offer, "id": "offer-5003", "category": "produce"}
    control = run_chore(corpus, other, Thread(
        ledger, subject_for_offer(handler.NETWORK, other), "run-different-category"),
        network=handler.NETWORK)
    equity = next(envelope for envelope in control.envelopes if envelope.specialist == "equity")
    assert equity.meta["back_of_queue"] == []
    assert equity.meta["ceiling_share"] == 0.4


def test_custody_resumes_across_independent_thread_handles_and_detects_missing_rows():
    ledger = InMemoryLedger()
    Thread(ledger, "net:offers/ambient", "run-new").append("run.started")
    Thread(ledger, "net:offers/ambient", "run-new").append("offer.received")
    Thread(ledger, "net", "run-new").append("record.published")
    entries = ledger.thread("run-new")
    assert custody.summary("offer-1", entries)["verified"]
    assert not custody.summary("offer-1", [entries[0], entries[2]])["verified"]
    assert not custody.summary("offer-1", [entries[0], entries[2], entries[1]])["verified"]


def test_public_get_never_reconciles_a_pending_saved_publication(client, monkeypatch):
    state = api.initial_state("live")
    state["operations"]["reserved-approval"] = {
        "status": "pending", "action": "approve", "offer_id": "offer-4471",
        "nonce": "private-nonce", "signature": "private-signature",
    }
    client.store.save(f"live:{handler.NETWORK}", state, 0)
    monkeypatch.setattr(api, "invoke_writer", lambda *a: pytest.fail("GET invoked writer"))
    monkeypatch.setattr(api.WorkspaceStore, "save", lambda *a: pytest.fail("GET saved state"))
    for path in ("/api/workspace", "/api/offers/offer-4471"):
        code, answer = client(path, data={"mode": "live"})
        assert code == 200
        assert "private-nonce" not in json.dumps(answer)
        assert "private-signature" not in json.dumps(answer)


def test_only_trusted_explicit_recovery_completes_the_reserved_attempt(client, monkeypatch):
    state = api.initial_state("live")
    state["operations"]["reserved-approval"] = {
        "status": "pending", "action": "approve", "offer_id": "offer-4471",
        "nonce": "exact-reserved-nonce", "signature": "private-signature",
    }
    saved = client.store.save(f"live:{handler.NETWORK}", state, 0)
    calls = []

    def status_only(payload, path):
        assert path == "/publication-status"
        assert payload == {"nonce": "exact-reserved-nonce"}
        calls.append(payload)
        return {"state": "recorded"}

    monkeypatch.setattr(api, "invoke_writer", status_only)
    payload = {"mode": "live", "version": saved["version"],
               "request_id": "recovery-request-0001", "operation_id": "reserved-approval"}
    path = "/api/offers/offer-4471/recover"
    assert client(path, "POST", payload)[0] == 403
    assert calls == []
    context = {"authorizer": {"lambda": {"network": handler.NETWORK,
               "principalId": "fixture-coordinator", "permissions": ["merismos:coordinate"]}}}
    assert client(path, "POST", payload, context=context)[0] == 200
    assert len(calls) == 1
    saved = client.store.get(f"live:{handler.NETWORK}")
    assert saved["operations"]["reserved-approval"]["status"] == "complete"
    assert client(path, "POST", {**payload, "version": saved["version"]},
                  context=context)[0] == 200
    assert len(calls) == 1


@pytest.mark.parametrize("role", ["reader", "evaluator"])
def test_public_capability_probe_cannot_borrow_the_writer_identity(role, monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", role)
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: pytest.fail("AWS reached"))
    assert handler.publication_capabilities()["statusCode"] == 403


@pytest.mark.parametrize("denied", [False, True])
def test_writer_capability_probe_only_reads_and_reports_actual_denial(monkeypatch, denied):
    monkeypatch.setenv("MERISMOS_ROLE", "writer")
    monkeypatch.setenv("MERISMOS_LEDGER_TABLE", "fixture-thread")
    monkeypatch.setattr(handler, "corpus_from_env", LocalCorpus)
    calls = []

    class ReadOnly:
        def get_item(self, **request):
            calls.append(request)
            if denied:
                raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "GetItem")
            return {}

    monkeypatch.setattr(boto3, "client", lambda *a, **kw: ReadOnly())
    result = json.loads(handler.publication_capabilities()["body"])
    assert result["read_only"] is True
    assert result["checks"]["corpus_freshness_read"]["allowed"] is True
    assert result["checks"]["custody_head_read"]["allowed"] is not denied
    assert calls == [{"TableName": "fixture-thread", "ConsistentRead": True,
                      "Key": {"subject": {"S": "custody:capability-probe"},
                              "entry_id": {"S": "head"}}}]


def test_other_categories_cannot_hide_the_last_two_saved_donations():
    ledger = InMemoryLedger()
    for index in range(205):
        category = "ambient" if index < 2 else "produce"
        Thread(ledger, handler.NETWORK, f"run-{index}").append(
            "record.published", key=f"records/offer-{index}.md", offer_id=f"offer-{index}",
            category=category, orgs=["Kitchen"])
    history = published_history(ledger, handler.NETWORK, [{"category": "ambient"}],
                                category="ambient")
    assert len(history) == 2
    assert _took_last_two([entry.body for entry in history], "ambient") == ["Kitchen"]


def test_saved_plan_is_refused_after_relevant_fairness_history_changes(writer):
    prepare, storage, _, _, corpus, offer = writer
    offer["id"] = "offer-6000"
    corpus.files["offers/offer-6000.json"] = json.dumps(offer)
    _, first = prepare("run-prepared-one")
    offer["id"] = "offer-6001"
    corpus.files["offers/offer-6001.json"] = json.dumps(offer)
    _, second_stale = prepare("run-prepared-two")
    offer["id"] = "offer-6002"
    corpus.files["offers/offer-6002.json"] = json.dumps(offer)
    _, third_stale = prepare("run-prepared-three")
    assert handler.publish(first)["statusCode"] == 200
    assert handler.publish(second_stale)["statusCode"] == 409
    offer["id"] = "offer-6001"
    _, second_reviewed = prepare("run-reviewed-two")
    assert handler.publish(second_reviewed)["statusCode"] == 200
    assert handler.publish(third_stale)["statusCode"] == 409
    assert storage.writes == 2


def test_same_category_lane_holds_unknown_attempt_until_proven_recovery(writer, monkeypatch):
    prepare, storage, _, _, _, _ = writer
    first, payload = prepare()
    second, other = prepare("run-other-lane")
    approvals = handler.ApprovalStore()
    assert approvals.acquire_lane(first)
    assert handler.publish(other)["statusCode"] == 409
    assert storage.writes == 0
    approvals.release_lane(second)
    assert not approvals.acquire_lane(second), "different nonce released the lane"
    approvals.release_lane(first)
    assert handler.publish(payload)["statusCode"] == 200
    assert approvals.acquire_lane(second)


@pytest.mark.parametrize("unknown", [False, True])
def test_live_run_dispatch_distinguishes_known_failure_from_unknown(client, monkeypatch, unknown):
    context = {"authorizer": {"lambda": {"network": handler.NETWORK,
               "principalId": "fixture-coordinator", "permissions": ["merismos:coordinate"]}}}
    monkeypatch.delenv("MERISMOS_READER_FUNCTION", raising=False)
    if unknown:
        monkeypatch.setattr(api.background, "start", lambda *a: (_ for _ in ()).throw(
            TimeoutError("dispatch outcome unknown")))
    payload = {"mode": "live", "version": 0, "request_id": "dispatch-request-0001"}
    code, _ = client("/api/offers/offer-4471/run", "POST", payload, context=context)
    assert code == 500
    saved = client.store.get(f"live:{handler.NETWORK}")
    assert saved["operations"][payload["request_id"]]["status"] == (
        "pending" if unknown else "failed")
    monkeypatch.setattr(api.background, "start", lambda *a: None)
    retry = {**payload, "version": saved["version"], "request_id": "dispatch-request-0002"}
    code, _ = client("/api/offers/offer-4471/run", "POST", retry, context=context)
    assert code == (409 if unknown else 200)

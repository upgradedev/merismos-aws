"""Structured coordinator API, separate from the compatible server-rendered UI.

Sandbox capabilities authorize only their own synthetic workspace. Live writes
require an API Gateway Lambda authorizer's network-scoped coordinator grant.
No body/header value can confer that grant. Approval and collection are separate
facts. Every mutation uses compare-and-swap and a request id bound to its inputs.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from importlib.resources import files

from . import background, bedrock, gate, intake, pickup
from .approval import ApprovalStore, InMemoryApprovalStore, authorise, digest, grant
from .corpus import corpus_from_env, offers
from .fleet import new_run_id, record_key, run_chore, subject_for_offer
from .ledger import InMemoryLedger, Thread, ledger_from_env
from .workspace_store import Conflict, WorkspaceStore


class ApiError(ValueError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class SnapshotCorpus:
    backend = "sandbox snapshot"

    def __init__(self, files: dict):
        self.files = files

    def list_paths(self):
        return sorted(self.files)

    def read(self, path: str):
        return self.files[path]


def snapshot(corpus) -> dict:
    return {p: corpus.read(p) for p in corpus.list_paths()}


def evidence_digest(corpus, offer: dict) -> str:
    """Target offer plus the sources that determine its eligibility and split.

    Another offer arriving is not evidence about this donation. Organisations,
    registers and the target manifest are: changing them requires a new review.
    """
    relevant = {p: corpus.read(p) for p in corpus.list_paths()
                if p.startswith(("orgs/", "registers/"))}
    manifest = str(offer.get("manifest", ""))
    if manifest:
        path = manifest if manifest.startswith("offers/") else f"offers/{manifest}"
        if path in corpus.list_paths():
            relevant[path] = corpus.read(path)
    return fingerprint({"offer": offer, "sources": relevant})


def initial_state(mode: str) -> dict:
    return {"version": 0, "mode": mode, "runs": {}, "claims": [], "records": [],
            "operations": {}, "expires_at": time.time() + (86400 if mode == "sandbox"
                                                         else 3650 * 86400)}


def coordinator(event: dict, network: str) -> str:
    context = (event.get("requestContext", {}).get("authorizer") or {}).get("lambda") or {}
    permissions = context.get("permissions", [])
    if context.get("network") != network or not isinstance(permissions, list) or (
        "merismos:coordinate" not in permissions
    ) or not context.get("principalId"):
        raise ApiError(403, "Live changes require an authenticated network coordinator. "
                       "Use the separate sandbox to rehearse this journey.")
    # Do not put a person's identity in public read models or records.
    return "coordinator:" + fingerprint(str(context["principalId"]))[:16]


def safe_text(value) -> str:
    text = str(value or "")
    if gate.check_personal_data(gate.Draft(body=text)):
        return "Text withheld by the public-record personal-data check."
    return text


def public_offer(offer: dict) -> dict:
    keys = ("id", "title", "donor", "category", "quantity", "unit", "collection_date",
            "use_by", "allergens", "note")
    return {k: safe_text(offer[k]) if isinstance(offer.get(k), str) else offer.get(k)
            for k in keys}


def public_result(result: dict) -> dict:
    # Export only coordinator-facing content. Internal read logs, numeric timing
    # and hashes are not prose, and must neither leak nor trigger phone checks.
    public = {k: result.get(k) for k in ("outcome", "note", "draft_body",
              "draft_allocations", "draft_barred_because", "verdict", "woken")}
    public["envelopes"] = [{k: e.get(k) for k in
                           ("specialist", "status", "reason", "findings", "notes")}
                          for e in result.get("envelopes", [])]
    text = json.dumps(public, default=str)
    if gate.check_personal_data(gate.Draft(body=text)):
        return {"outcome": "refused_by_gate", "note": "Personal-data check refused this output.",
                "draft_allocations": [], "draft_barred_because": {}, "draft_body": "",
                "run_id": result.get("run_id", ""), "envelopes": []}
    return {**public, "run_id": result.get("run_id", "")}


def live_result(offer: dict, saved: dict, network: str) -> dict:
    ledger = ledger_from_env()
    run = saved.get("run_id")
    if not run:
        # Fleet memory is category-scoped, not offer-scoped. Pick the matching
        # offer's newest result without mistaking its sibling's run for corruption.
        found = [e for e in ledger.recall(subject_for_offer(network, offer),
                                        "run.completed", limit=200)
                 if e.body.get("offer_id") == offer["id"]]
        if found:
            run = found[0].run_id
    if not run:
        return {}
    entries = ledger.thread(run)
    result = background.completed_result(entries)
    if result and result.get("offer_id") != offer["id"]:
        raise ApiError(409, "Run does not belong to this offer.")
    return {**saved, "run_id": run, "result": dict(result) if result else {},
            "progress": background.progress(entries), "failure": background.failure(entries)}


def live_records(current_offers: list, network: str) -> list:
    ledger = ledger_from_env()
    # Legacy writer stored receipts at network scope; fleet recalls offer scope.
    found = list(ledger.recall(network, "record.published", limit=200))
    for offer in current_offers:
        found.extend(ledger.recall(subject_for_offer(network, offer), "record.published", 200))
    unique = {e.body["key"]: dict(e.body) for e in sorted(found, key=lambda e: e.at)
              if "key" in e.body}
    return [{"key": r["key"], "run_id": r.get("run_id", ""),
             "content_digest": r.get("content_digest", ""),
             "published_at": r.get("published_at"), "mode": "live",
             "offer_id": r["key"].removeprefix("records/").split("-c")[0].removesuffix(".md")}
            for r in unique.values()]


def plan_for(offer: dict, run: dict, records: list, network: str) -> dict | None:
    result = run.get("result") or {}
    if result.get("outcome") not in ("awaiting_approval", "approved"):
        return None
    mine = next((r for r in records if r["run_id"] == run.get("run_id")), None)
    key = mine["key"] if mine else record_key(offer["id"], records)
    content = result.get("draft_body", "")
    return {"key": key, "digest": digest(network, key, content), "body": content,
            "run_id": run["run_id"], "recorded": bool(mine),
            "evidence_digest": run.get("evidence_digest", "")}


def pickup_rows(offer: dict, run: dict, plan: dict | None, claims: list) -> list:
    if not plan:
        return []
    allocations = (run.get("result") or {}).get("draft_allocations", [])
    relevant = [pickup.Claim(**{k: v for k, v in c.items() if k != "state"})
                for c in claims if c["offer_id"] == offer["id"]]
    status = pickup.outstanding(allocations, relevant, plan["digest"])
    rows = [{**a, "state": "unclaimed", "role": "", "agreed_at": ""}
            for a in status["unclaimed"]] if plan["recorded"] else []
    for name in ("unconfirmed", "confirmed", "void"):
        for row in status[name]:
            state = "invalidated" if name == "void" else row["state"]
            if state == "agreed":
                state = "overdue" if datetime.fromisoformat(row["agreed_at"]).timestamp() \
                    < time.time() else "scheduled"
            rows.append({**row, "state": state})
    return [{**r, "offer_id": offer["id"], "title": offer["title"], "unit": offer["unit"],
             "commitment_digest": r.get("plan_digest", plan["digest"]),
             "plan_digest": plan["digest"], "run_id": run["run_id"]} for r in rows]


def summary(offer: dict, result: dict, recorded: bool, mode: str) -> str:
    lines = ["SYNTHETIC DEMO · " + ("SANDBOX" if mode == "sandbox" else "LIVE RECORD VIEW"),
             str(offer["title"])]
    lines.extend(f"{a['org']}: {a['quantity']} {offer['unit']}. {a.get('reason', '')}"
                 for a in result.get("draft_allocations", []) or [])
    lines.extend(f"No allocation for {org}: {why}" for org, why in
                 (result.get("draft_barred_because") or {}).items())
    lines.append("Recorded allocation; collection still requires confirmation." if recorded else
                 "DRAFT. No publication approved. Do not arrange collection from this draft.")
    return safe_text("\n".join(lines))


def view(state: dict, corpus, network: str, event: dict) -> dict:
    current_offers = offers(corpus)
    records = state["records"] if state["mode"] == "sandbox" else live_records(
        current_offers, network)
    from .handler import _mark_superseded, config

    records = _mark_superseded([dict(r) for r in records])
    rows, collections = [], []
    for offer in current_offers:
        run = state["runs"].get(offer["id"], {})
        if state["mode"] == "live":
            run = live_result(offer, run, network)
        result = public_result(run["result"]) if run.get("result") else {}
        safe_run = {**run, "result": result}
        plan = plan_for(offer, safe_run, records, network)
        status = result.get("outcome", "not_started")
        if run.get("failure"):
            status = "failed"
        elif run and not result:
            status = "running"
        if plan and plan["recorded"]:
            status = "recorded" if state["mode"] == "sandbox" else "published"
        rows.append({"offer": public_offer(offer), "status": status, "result": result,
                     "plan": plan, "progress": run.get("progress"),
                     "summary": summary(offer, result, bool(plan and plan["recorded"]),
                                        state["mode"])})
        collections.extend(pickup_rows(offer, safe_run, plan, state["claims"]))
    try:
        coordinator(event, network)
        can_write = True
    except ApiError:
        can_write = state["mode"] == "sandbox"
    return {"mode": state["mode"], "version": state["version"], "network": network,
            "synthetic": True, "offers": rows, "pickups": collections, "records": records,
            "roles": list(pickup.ROLES), "can_write": can_write,
            "provider": "scripted-planner/1.0.0 · real Strands agent loop; no model network call"
            if state["mode"] == "sandbox" else config()["analyst"],
            "expires_at": state.get("expires_at"),
            "authorization_note": "Live changes require an authenticated network coordinator."}


def route(event: dict, method: str, path: str, body: dict) -> dict:
    from .handler import NETWORK, _reply, role

    try:
        if role() != "reader":
            raise ApiError(403, "The coordinator API is served only by the reader identity.")
        store = WorkspaceStore()
        if path == "/api/sessions" and method == "POST":
            handle = secrets.token_urlsafe(32)
            state = initial_state("sandbox")
            state["files"] = json.loads(files("merismos").joinpath("demo_corpus.json").read_text())
            store.save(fingerprint(handle), state, 0)
            return _reply(201, {"session": handle, "expires_at": state["expires_at"]})
        mode = str(body.get("mode", "live"))
        if mode not in ("live", "sandbox"):
            raise ApiError(400, "Unknown workspace mode.")
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        handle = headers.get("x-merismos-session", "")
        if mode == "sandbox":
            if not re.fullmatch(r"[A-Za-z0-9_-]{43}", handle):
                raise ApiError(401, "Start a sandbox session first.")
            identifier = fingerprint(handle)
            state = store.get(identifier)
            if state is None:
                raise ApiError(410, "Sandbox session expired. Start a new session.")
            corpus = SnapshotCorpus(state["files"])
        else:
            identifier = f"live:{NETWORK}"
            state = store.get(identifier) or initial_state("live")
            corpus = corpus_from_env()
        if method == "GET" and path == "/api/workspace":
            return _reply(200, view(state, corpus, NETWORK, event))
        match = re.fullmatch(r"/api/offers/(offer-[0-9]+)(?:/(run|approve|pickup))?", path)
        if not match and path != "/api/offers/new":
            raise ApiError(404, "No such API route.")
        offer_id, action = match.groups() if match else ("new", "add")
        offer = {} if action == "add" else next(
            (o for o in offers(corpus) if o["id"] == offer_id), None)
        if offer is None:
            raise ApiError(404, "No such offer.")
        if method == "GET" and not action:
            return _reply(200, next(o for o in view(state, corpus, NETWORK, event)["offers"]
                                    if o["offer"]["id"] == offer_id))
        if method != "POST" or not action:
            raise ApiError(405, "Use a supported action.")
        principal = "sandbox coordinator" if mode == "sandbox" else coordinator(event, NETWORK)
        request_id = str(body.get("request_id", ""))
        if not re.fullmatch(r"[A-Za-z0-9-]{16,80}", request_id):
            raise ApiError(400, "A request id is required for safe retries.")
        signature = fingerprint({"path": path, "body": {k: v for k, v in body.items()
                                                       if k != "version"}})
        previous = state["operations"].get(request_id)
        if previous:
            if previous["signature"] != signature:
                raise ApiError(409, "This request id belongs to different inputs.")
            if previous["status"] != "complete":
                raise ApiError(409, "Action pending or outcome unknown. Refresh to inspect the "
                               "record before any new request; this request will not run twice.")
            return _reply(200, view(state, corpus, NETWORK, event))
        if body.get("version") != state["version"]:
            raise ApiError(409, "Workspace changed. Refresh and review the current plan.")
        if any(op.get("status") == "pending" for op in state["operations"].values()):
            raise ApiError(409, "An earlier action is pending or its outcome is unknown. "
                           "Refresh the history before making another change.")
        if len(state["operations"]) >= 100:
            raise ApiError(409, "Session action limit reached. Start a new sandbox session.")
        result = mutate(state, corpus, NETWORK, offer, action, body, principal,
                        store, identifier, signature)
        return _reply(200, view(result, corpus, NETWORK, event))
    except (ApiError, Conflict, pickup.NotClaimable, ValueError) as error:
        status = error.status if isinstance(error, ApiError) else 409 if isinstance(
            error, Conflict) else 400
        return _reply(status, {"detail": str(error)})


def mutate(state, corpus, network, offer, action, body, principal, store, identifier, signature):
    mode, offer_id = state["mode"], offer.get("id", "")
    request_id = body["request_id"]
    records = state["records"] if mode == "sandbox" else live_records(offers(corpus), network)
    run = state["runs"].get(offer_id, {})
    if mode == "live" and action != "add":
        run = live_result(offer, run, network)
    plan = plan_for(offer, run, records, network) if offer else None
    if action == "run" and any(c["offer_id"] == offer_id and c.get("confirmed_at") is not None
                               for c in state["claims"]):
        raise ApiError(409, "A collection is already confirmed. "
                       "This offer cannot be allocated again.")
    if action == "add":
        if not isinstance(body.get("form"), dict):
            raise ApiError(400, "Fill in the offer form.")
        offer_id = intake.next_offer_id(offers(corpus))
        offer = intake.offer_from_form(body["form"], offer_id)
        # Allergens are free text too; the existing intake's primary fields are
        # already checked, and this new JSON boundary applies that same check here.
        intake._refuse_a_person(str(body["form"].get("allergens", "")))
        intake._refuse_an_instruction(str(body["form"].get("allergens", "")))
    if action not in ("run", "add"):
        if not plan or body.get("digest") != plan["digest"] or body.get("run_id") != run.get(
            "run_id"
        ):
            raise ApiError(409, "This plan is stale. Refresh and review the allocation again.")
        if run.get("evidence_digest") != evidence_digest(corpus, offer):
            raise ApiError(409, "Evidence changed or predates this API. Run the fleet again.")
        if action == "approve" and mode == "live" and str(
            offer.get("collection_date", "")
        ) < date.today().isoformat():
            raise ApiError(409, "This collection date has passed. The old plan cannot be approved.")
    if action == "approve":
        if body.get("consent") is not True or body.get("key") != plan["key"]:
            raise ApiError(400, "Explicit consent to this exact record and address is required.")
        if plan["recorded"]:
            raise ApiError(409, "This run already has a record. It cannot be published twice.")
        if gate.check_personal_data(gate.Draft(body=plan["body"])):
            raise ApiError(400, "The public-record personal-data check refused this content.")
    if action == "pickup":
        update_pickup(state, offer, run, plan, body)
    # Reserve before any model invocation or writer call. An uncertain outcome
    # remains pending and cannot cause a second external write on retry.
    state["operations"][request_id] = {"signature": signature, "status": "pending"}
    state = store.save(identifier, state, state["version"])
    if action == "add":
        if mode == "sandbox":
            state["files"][f"offers/{offer_id}.json"] = intake.as_document(offer)
            corpus.files = state["files"]
        else:
            from .handler import _ask_the_writer_to_file

            status, detail = _ask_the_writer_to_file(offer_id, body["form"])
            if status != 200:
                raise ApiError(status, detail)
    elif action == "run":
        run_id = new_run_id()
        run = {"run_id": run_id, "evidence_digest": evidence_digest(corpus, offer)}
        state["runs"][offer_id] = run
        if mode == "sandbox":
            ledger = InMemoryLedger()
            thread = Thread(ledger, subject_for_offer(network, offer), run_id, scope="sandbox")
            result = run_chore(corpus, offer, thread, analyst=bedrock.scripted_analyst(),
                               network=network)
            run["result"] = result.as_dict()
            run["entries"] = [e.as_dict() for e in ledger.all()]
            if any(f.check == "model-unreachable" for e in result.envelopes for f in e.findings):
                raise ApiError(503, "The Strands sandbox agent did not run. Try again later.")
        else:
            # Persist the run handle before dispatch, so even a timeout remains discoverable.
            state = store.save(identifier, state, state["version"])
            thread = Thread(ledger_from_env(), subject_for_offer(network, offer), run_id)
            thread.append("run.started", offer_id=offer_id, evidence_digest=run["evidence_digest"])
            try:
                background.start(offer_id, run_id, network)
            except Exception:
                thread.append("run.failed", detail="The runner could not be started. Retry later.")
                raise
    elif action == "approve":
        approval = grant(network, plan["key"], plan["body"], principal, run["run_id"])
        if mode == "sandbox":
            approvals = InMemoryApprovalStore()
            approvals.put(approval)
            authorise(approvals, approval.nonce, network, plan["key"], plan["body"])
            state["records"].append({"key": plan["key"], "content_digest": plan["digest"],
                                     "run_id": run["run_id"], "offer_id": offer_id,
                                     "published_at": time.time(), "mode": "sandbox"})
        else:
            ApprovalStore().put(approval)
            invoke_writer({"nonce": approval.nonce, "key": plan["key"], "body": plan["body"],
                           "api_evidence_digest": run["evidence_digest"], "offer_id": offer_id})
    state["operations"][request_id]["status"] = "complete"
    return store.save(identifier, state, state["version"])


def update_pickup(state, offer, run, plan, body):
    if not plan["recorded"]:
        raise ApiError(409, "Approve the allocation before claiming a collection.")
    org = str(body.get("org", ""))
    existing = next((c for c in state["claims"] if c["offer_id"] == offer["id"] and
                     c["org"] == org and c["plan_digest"] == plan["digest"]), None)
    action = body.get("action")
    if action == "claim":
        # Confirmed shares cannot be claimed again, including after the 14-day window.
        if existing:
            raise ApiError(409, "This organisation already has a claim for this allocation.")
        claim = pickup.claim(offer_id=offer["id"], org=org, role=str(body.get("role", "")),
                             allocations=run["result"]["draft_allocations"],
                             plan_digest=plan["digest"], unit=offer["unit"])
        state["claims"].append(claim.as_dict())
        return
    if not existing:
        raise ApiError(409, "Claim the share before scheduling or confirming it.")
    claim = pickup.Claim(**{k: v for k, v in existing.items() if k != "state"})
    if claim.confirmed_at is not None:
        raise ApiError(409, "Collection already confirmed. It cannot be counted twice.")
    if not pickup.still_valid(claim, plan["digest"]):
        raise ApiError(409, "This commitment expired. Review the allocation with the coordinator.")
    if action == "schedule":
        try:
            when = datetime.fromisoformat(str(body.get("agreed_at", "")))
            if when.tzinfo is None:
                raise ValueError("timezone missing")
            if when.timestamp() <= time.time() or when.timestamp() > time.time() + 14 * 86400:
                raise ValueError("outside the next fourteen days")
        except ValueError as error:
            raise ApiError(400, "Choose a future collection time within 14 days, with timezone.") \
                from error
        claim = replace(claim, agreed_at=when.astimezone(timezone.utc).isoformat())
    elif action == "confirm":
        if body.get("consent") is not True:
            raise ApiError(400, "Confirm that this collection actually happened.")
        claim = pickup.confirm(claim)
    else:
        raise ApiError(400, "Unknown pickup action.")
    state["claims"][state["claims"].index(existing)] = claim.as_dict()


def invoke_writer(payload: dict) -> None:
    import os

    import boto3

    answer = boto3.client("lambda").invoke(
        FunctionName=os.environ["MERISMOS_WRITER_FUNCTION"],
        Payload=json.dumps({"requestContext": {"http": {"method": "POST", "path": "/publish"}},
                            "body": json.dumps(payload)}),
    )
    response = json.loads(answer["Payload"].read())
    if response.get("statusCode") != 200:
        raise ApiError(502, "The writer did not confirm publication. Refresh the history; "
                       "do not issue another approval until the outcome is known.")

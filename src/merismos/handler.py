"""One package, three deployments, three IAM roles.

What fixes a deployment's authority is its **role**, not its code. All three
Lambdas run this same handler; ``MERISMOS_ROLE`` decides which routes it will
serve, and IAM decides what it can reach whatever it decides to try. Those are
two different locks and both are needed: the role check stops the reader serving
``/publish`` at all, and IAM stops it succeeding if the check were ever wrong.

``/identity`` is the endpoint worth reading. It does not report configuration.
It **attempts** two things and reports what AWS said to each: the write that
publishing actually needs, and a Secrets Manager canary that nothing reads. A
flag saying "this role cannot publish" is a claim; an ``AccessDeniedException``
in the response body is evidence.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from . import bedrock
from .approval import (
    ApprovalRefused,
    ApprovalStore,
    Receipt,
    authorise,
    grant,
)
from .corpus import corpus_from_env
from .corpus import offers as read_offers
from .deferral import escalate, scheduler_from_env
from .fleet import catalogue, new_run_id, run_chore, subject_for_offer
from .guard import ROLE_TOOLS, Guard
from .ledger import Thread, ledger_from_env

NETWORK = os.environ.get("MERISMOS_NETWORK", "kypseli-network")


def role() -> str:
    """This process's role, from the environment and never from a request.

    A request that could name its own role would be a request that could name
    its own privileges.
    """
    return os.environ.get("MERISMOS_ROLE", "reader").strip().lower()


def _html(status: int, markup: str) -> dict[str, Any]:
    """An HTML reply. Same Lambda, different content type."""
    return {
        "statusCode": status,
        "headers": {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            # The page loads no script and no external asset, so the policy that
            # says so is cheap and it is the honest description of the page.
            "content-security-policy": (
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
            "referrer-policy": "no-referrer",
            "x-content-type-options": "nosniff",
        },
        "body": markup,
    }


def _redirect(where: str) -> dict[str, Any]:
    return {"statusCode": 303, "headers": {"location": where}, "body": ""}


def _reply(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            # The record and the thread are meant to be readable by a funder or
            # a member with no account, so the read endpoints are open by
            # design. The write path is not reachable from here at all.
            "cache-control": "no-store",
        },
        "body": json.dumps(body, indent=2, sort_keys=True, default=str),
    }


def _route(event: Any) -> tuple[str, str, dict]:
    """Pull method, path and parsed body out of a Function URL or ALB event."""
    context = event.get("requestContext", {}) or {}
    http = context.get("http", {}) or {}
    method = (http.get("method") or event.get("httpMethod") or "GET").upper()
    path = http.get("path") or event.get("rawPath") or event.get("path") or "/"
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    content_type = ""
    for k, v in (event.get("headers") or {}).items():
        if k.lower() == "content-type":
            content_type = str(v).lower()
    if "application/x-www-form-urlencoded" in content_type:
        from urllib.parse import parse_qs

        body = {k: v[0] for k, v in parse_qs(raw).items()}
    else:
        try:
            body = json.loads(raw) if raw.strip() else {}
        except ValueError:
            body = {}
    query = event.get("queryStringParameters") or {}
    if isinstance(body, dict) and isinstance(query, dict):
        body = {**query, **body}
    return method, path.rstrip("/") or "/", body if isinstance(body, dict) else {}


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """The Lambda entry point for all three deployments."""
    # A scheduled wake arrives as a plain payload rather than an HTTP event.
    if isinstance(event, dict) and event.get("source") == "merismos.deferral":
        return _reply(200, _wake(event))

    # So does a background chore, which the reader asked itself to run because
    # it takes longer than a request is allowed to.
    from . import background

    if background.is_background(event):
        return _reply(200, _run_in_background(event))

    method, path, body = _route(event)
    me = role()

    try:
        html_reply = _screens(method, path, body)
        if html_reply is not None:
            return html_reply
        if path == "/identity":
            return _reply(200, identity())
        if path == "/catalog":
            return _reply(200, catalogue())
        if path == "/config":
            return _reply(200, config())
        if path == "/offers":
            return _reply(200, {"offers": [o["id"] for o in read_offers(corpus_from_env())]})
        if path == "/thread" and method == "GET":
            return _reply(200, thread_of(body.get("run_id", "")))
        if path == "/run" and method == "POST":
            return _reply(200, run(body))
        if path == "/publish" and method == "POST":
            return publish(body)
    except ApprovalRefused as refusal:
        return _reply(refusal.status, {"detail": str(refusal)})
    except Exception as error:  # noqa: BLE001 - never leak a stack trace outward
        return _reply(500, {"detail": f"{type(error).__name__}", "role": me})

    return _reply(404, {"detail": f"no route {method} {path} on the {me}"})


def identity() -> dict[str, Any]:
    """Who this process is, and what it is refused. Attempted, not configured.

    **Two probes, and the second one is the one that matters.**

    This endpoint used to report only the Secrets Manager read and the README
    called that "the publish credential". It is not. ``publish()`` never reads
    that secret; it calls ``s3:PutObject``. So the secret is a **canary**: a
    thing all three identities ask for so that a refusal is observable in a
    response body. Useful, and not the authority.

    The authority is the S3 write, so it is now probed too, by attempting a real
    ``PutObject`` under a private ``probes/`` prefix rather than by reading a
    policy and believing it. A reader that were somehow granted the write would
    show up here even if the canary still said denied.
    """
    me = role()
    canary_reached, canary_said = _attempt_publish_credential()
    can_write, write_said = _attempt_publish_authority()
    return {
        "role": me,
        "may_call": sorted(ROLE_TOOLS.get(me, frozenset())),
        "publish_authority": {
            "what_it_is": (
                "s3:PutObject on the records bucket. This is what publishing "
                "a record actually needs"
            ),
            "can_write": can_write,
            "what_aws_said": write_said,
        },
        "boundary_canary": {
            "what_it_is": (
                "a Secrets Manager value the publish path never reads. It exists "
                "so that a refusal is observable, and it is not the authority"
            ),
            "can_read": canary_reached,
            "what_aws_said": canary_said,
        },
        "note": (
            "both lines are the result of actually calling AWS just now, not "
            "flags. The reader and the evaluator are refused by AWS IAM, not by "
            "any code in this repository. can_write is the one that decides "
            "whether this identity could publish a record"
        ),
        "build": os.environ.get("MERISMOS_BUILD_SHA", "unknown"),
        "model": os.environ.get("MERISMOS_MODEL", "none, deterministic only"),
        "critic": os.environ.get("MERISMOS_CRITIC_MODEL", "none"),
    }


def _attempt_publish_authority() -> tuple[bool, str]:
    """Try the write that publishing actually needs, and report what came back.

    Writes a zero byte object under ``probes/``, which the bucket policy does
    **not** open to the public, so a successful probe leaves a private marker
    rather than an empty file in the record space a funder reads.
    """
    bucket = os.environ.get("MERISMOS_RECORDS_BUCKET", "")
    if not bucket:
        return False, "no records bucket is configured in this deployment"
    try:
        import boto3

        boto3.client("s3").put_object(
            Bucket=bucket, Key=f"probes/identity-{role()}", Body=b""
        )
    except Exception as error:  # noqa: BLE001 - the refusal is the answer
        return False, _aws_said(error)
    return True, "granted"


def _aws_said(error: Exception) -> str:
    """AWS's own error code rather than the Python class name.

    botocore raises a bare ClientError for an IAM refusal, and "ClientError" is
    not evidence: a typo in a resource name produces one too.
    """
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(error).__name__


def _attempt_publish_credential() -> tuple[bool, str]:
    """Ask for the credential and report what came back, whatever came back."""
    secret = os.environ.get("MERISMOS_PUBLISH_SECRET", "")
    if not secret:
        return False, "no publish secret is configured in this deployment"
    try:
        import boto3

        boto3.client("secretsmanager").get_secret_value(SecretId=secret)
    except Exception as error:  # noqa: BLE001 - the refusal is the answer
        return False, _aws_said(error)
    return True, "granted"


def config() -> dict[str, Any]:
    """The bounds this fleet publishes about itself, readable with no account."""
    from .tools import DEFAULT_SCOPE, MAX_READ_BYTES, MAX_SEARCH_SCAN, READ_BUDGET

    return {
        "network": NETWORK,
        "read_scope": list(DEFAULT_SCOPE),
        "read_budget_per_specialist": READ_BUDGET,
        "max_bytes_per_read": MAX_READ_BYTES,
        "max_files_per_search": MAX_SEARCH_SCAN,
        "ledger": os.environ.get("MERISMOS_LEDGER", "dynamodb"),
        "deferrals_wake_on_a_schedule": bool(os.environ.get("MERISMOS_WAKE_TARGET_ARN")),
    }


def run(body: dict) -> dict[str, Any]:
    """Apportion one offer and stop at a card. This never publishes.

    An unauthenticated caller can start a run, and that is safe precisely
    because a run cannot end in a write. The furthest it goes is a card, and
    minting an approval needs a named person which this path does not supply.
    """
    corpus = corpus_from_env()
    wanted = str(body.get("offer") or body.get("pr") or "").strip()
    offers = read_offers(corpus)
    offer = next((o for o in offers if str(o["id"]) == wanted), offers[0] if offers else None)
    if offer is None:
        return {"detail": "this network's filing holds no offers"}

    thread = Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(NETWORK, offer),
        run_id=new_run_id(),
    )
    result = run_chore(
        corpus,
        offer,
        thread,
        analyst=bedrock.analyst_from_env(),
        critic=bedrock.critic_from_env(),
        scheduler=scheduler_from_env(),
        network=NETWORK,
        # No approver, deliberately. A trigger must not approve on a person's
        # behalf, which is the one thing the person is there for.
        approver="",
    )
    return result.as_dict()


def publish(body: dict) -> dict[str, Any]:
    """Publish an approved record. The writer's, and nobody else's.

    The role check is the first lock and IAM is the second. Both exist because
    all three deployments carry every route, and only one identity may serve
    this one.
    """
    if role() != "writer":
        return _reply(
            403,
            {
                "detail": (
                    f"the {role()} identity cannot publish a record. Publishing "
                    f"is the writer's, behind a human approval bound to the "
                    f"exact bytes"
                )
            },
        )

    nonce = str(body.get("nonce", ""))
    key = str(body.get("key", ""))
    content = str(body.get("body", ""))
    store = ApprovalStore()

    approval = authorise(store, nonce, NETWORK, key, content)

    import boto3

    bucket = os.environ["MERISMOS_RECORDS_BUCKET"]
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )
    receipt = Receipt(
        nonce=approval.nonce,
        network=approval.network,
        key=approval.key,
        content_digest=approval.content_digest,
        approved_by=approval.approved_by,
        run_id=approval.run_id,
        published_url=f"https://{bucket}.s3.amazonaws.com/{key}",
        published_at=time.time(),
    )
    thread = Thread(
        ledger=ledger_from_env(), subject=NETWORK, run_id=approval.run_id
    )
    thread.append("record.published", **receipt.as_dict())
    return _reply(200, receipt.as_dict())


def approve(body: dict) -> dict[str, Any]:
    """Mint an approval over exact bytes. Named person required.

    Not routed from ``handler`` on purpose: approving is an authenticated action
    and this build has no sign-in, so wiring it to an open endpoint would be the
    shape of the hole this whole design exists to close. It is here so the
    writer path is testable end to end and so the CLI can use it.
    """
    return grant(
        network=NETWORK,
        key=str(body["key"]),
        body=str(body["body"]),
        approved_by=str(body["approved_by"]),
        run_id=str(body.get("run_id", "")),
    ).as_dict()


def thread_of(run_id: str) -> dict[str, Any]:
    """One run, as a chain. Follow it back."""
    ledger = ledger_from_env()
    entries = ledger.thread(run_id) if run_id else []
    return {
        "run_id": run_id,
        "entries": [e.as_dict() for e in entries],
        "note": "each entry names the entry before it in parent_id",
    }


def _wake(event: dict) -> dict[str, Any]:
    """A scheduled deferral firing. It may append an escalation and nothing else.

    ``escalate`` is the only thing called here, and there is no branch in this
    function that reaches the writer, mints an approval or proposes a plan.
    """
    thread = Thread(
        ledger=ledger_from_env(),
        subject=str(event.get("subject", NETWORK)),
        run_id=str(event.get("run_id", new_run_id())),
    )
    return escalate(
        thread,
        deferral_id=str(event.get("deferral_id", "")),
        reason="the deferral reached its date and nobody had come back",
        fired_by="eventbridge-scheduler",
    )


def guard_for_this_process() -> Guard:
    """The guard every agent in this process is constructed with."""
    return Guard(role=role())


# --------------------------------------------------------------------------
# The screens. Same fleet, same gate, rendered rather than serialised.
# --------------------------------------------------------------------------


def _screens(method: str, path: str, body: dict) -> dict[str, Any] | None:
    """Serve an HTML screen, or return None so the JSON routes get their turn.

    Only the reader serves these. The evaluator and the writer carry the code
    because there is one package, and a person opening the writer's URL should
    get the same 403 they get from every other route on it.
    """
    if role() != "reader":
        return None

    from . import background, web

    if path == "/":
        return _html(200, web.inbox(read_offers(corpus_from_env()), NETWORK))

    if path == "/how":
        return _html(200, web.how_it_decides(catalogue(), config()))

    if path.startswith("/offer/"):
        offer_id = path.rsplit("/", 1)[-1]
        offer = _offer(offer_id)
        if offer is None:
            return _html(404, web.page("Not found", "<h1>No such offer</h1>"))

        # POST starts a chore in the background and hands back a run id. It is
        # not awaited: a specialist reading with a model takes about 100 seconds
        # and the gateway gives this request 30.
        if method == "POST":
            run_id = new_run_id()
            thread = Thread(
                ledger=ledger_from_env(),
                subject=subject_for_offer(NETWORK, offer),
                run_id=run_id,
            )
            thread.append("run.started", offer_id=offer_id)
            try:
                background.start(offer_id, run_id, NETWORK)
            except Exception as error:  # noqa: BLE001 - a run that never started must say so
                thread.append("run.failed", detail=_aws_said(error))
            return _redirect(f"/offer/{offer_id}?run={run_id}")

        run_id = str(body.get("run", "")).strip()
        if not run_id:
            return _html(200, web.ready(offer, NETWORK, os.environ.get("MERISMOS_MODEL", "")))

        entries = ledger_from_env().thread(run_id)
        state = background.progress(entries)
        if state["failed"]:
            return _html(
                200,
                web.page(
                    "The run failed",
                    f"<h1>The run failed</h1><div class='note stop'>"
                    f"{background.failure(entries)}</div>"
                    f"<p><a class='btn secondary' href='/offer/{offer_id}'>Try again</a></p>",
                ),
            )
        if not state["done"]:
            return _html(
                200,
                web.waiting(
                    offer, run_id, state, os.environ.get("MERISMOS_MODEL", "the model")
                ),
            )
        return _html(200, web.decision_from_record(
            background.completed_result(entries) or {}, offer, NETWORK
        ))

    if path.startswith("/approve/"):
        offer_id = path.rsplit("/", 1)[-1]
        offer, result = _decide(offer_id)
        if offer is None:
            return _html(404, web.page("Not found", "<h1>No such offer</h1>"))
        key = f"records/{offer_id}.md"

        if method == "GET":
            if result.draft is None:
                return _html(200, web.decision(result, offer, NETWORK))
            return _html(200, web.approval_card(result, offer, NETWORK, key))

        # POST. A person named themselves, so an approval may now be minted.
        approver = str(body.get("approved_by", "")).strip()
        if not approver or result.draft is None:
            return _html(400, web.page("Name required", "<h1>An approval names a person</h1>"))
        return _publish_approved(result, offer_id, key, approver)

    if path == "/records":
        return _html(200, web.page("Published", _published_index()))

    if path.startswith("/chain/"):
        offer_id = path.rsplit("/", 1)[-1]
        offer = _offer(offer_id)
        if offer is None:
            return _html(404, web.page("Not found", "<h1>No such offer</h1>"))
        from . import custody

        entries = ledger_from_env().recall(
            subject_for_offer(NETWORK, offer), "record.published", limit=1
        )
        run = entries[0].run_id if entries else str(body.get("run", ""))
        thread = ledger_from_env().thread(run) if run else []
        return _html(200, web.custody_chain(offer, custody.summary(offer_id, thread)))

    return None


def _decide(offer_id: str):
    """Run the chore for one offer and hand back the offer and the result."""
    corpus = corpus_from_env()
    offers = read_offers(corpus)
    offer = next((o for o in offers if str(o.get("id")) == offer_id), None)
    if offer is None:
        return None, None
    thread = Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(NETWORK, offer),
        run_id=new_run_id(),
    )
    result = run_chore(
        corpus,
        offer,
        thread,
        analyst=bedrock.analyst_from_env(),
        critic=bedrock.critic_from_env(),
        scheduler=scheduler_from_env(),
        network=NETWORK,
        approver="",
    )
    return offer, result


def _publish_approved(result, offer_id: str, key: str, approver: str) -> dict[str, Any]:
    """Mint the approval, then ask the writer. The reader cannot publish.

    This is the whole architecture in one function: the identity a person is
    talking to holds no authority to write, so it mints an approval bound to the
    exact bytes and asks a different identity, which re-checks the digest.
    """
    from . import web

    content = result.draft.body
    approval = grant(
        network=NETWORK,
        key=key,
        body=content,
        approved_by=approver,
        run_id=result.run_id,
    )
    ApprovalStore().put(approval)

    import boto3

    payload = json.dumps(
        {
            "requestContext": {"http": {"method": "POST", "path": "/publish"}},
            "body": json.dumps(
                {"nonce": approval.nonce, "key": key, "body": content}
            ),
        }
    )
    answer = boto3.client("lambda").invoke(
        FunctionName=os.environ["MERISMOS_WRITER_FUNCTION"], Payload=payload
    )
    written = json.loads(answer["Payload"].read())
    if written.get("statusCode") != 200:
        detail = json.loads(written.get("body", "{}")).get("detail", "the writer refused")
        return _html(
            502,
            web.page(
                "Not published",
                f"<h1>The writer refused</h1><div class='note stop'>{detail}</div>"
                f"<p><a class='btn secondary' href='/offer/{offer_id}'>Back</a></p>",
            ),
        )
    receipt = json.loads(written["body"])
    return _html(200, web.published(receipt, content))


def _published_index() -> str:
    """Every record published so far, from the thread rather than from S3."""
    bucket = os.environ.get("MERISMOS_RECORDS_BUCKET", "")
    base = f"https://{bucket}.s3.amazonaws.com/" if bucket else ""
    rows = ""
    try:
        entries = ledger_from_env().recall(NETWORK, "record.published", limit=50)
        for e in entries:
            url = e.body.get("published_url") or (base + str(e.body.get("key", "")))
            rows += (
                f"<tr><td><a href='{url}'>{e.body.get('key','')}</a></td>"
                f"<td>{e.body.get('approved_by','')}</td></tr>"
            )
    except Exception:  # noqa: BLE001 - an empty list is the honest empty state
        rows = ""
    if not rows:
        return (
            "<h1>Published records</h1>"
            "<div class='note'>Nothing published yet. A record appears here once somebody has "
            "read a card and approved it.</div>"
            "<p><a class='btn secondary' href='/'>Back to offers</a></p>"
        )
    return (
        "<h1>Published records</h1>"
        "<p class='lede'>Readable by anyone with no account.</p>"
        f"<div class='scroll'><table><thead><tr><th>Record</th><th>Approved by</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
    )


def _offer(offer_id: str):
    """One offer from the network's filing, or None."""
    offers = read_offers(corpus_from_env())
    return next((o for o in offers if str(o.get("id")) == offer_id), None)


def _run_in_background(event: dict) -> dict[str, Any]:
    """Run one chore to completion and record the result in the thread.

    This is the reader invoking itself with InvocationType Event, so it has the
    function's own 900 second budget rather than the gateway's 30. The chore is
    unchanged: same specialists, same guard, same gate. What is different is
    that a model can actually be used, which is the whole point of doing it this
    way.
    """
    offer_id = str(event.get("offer_id", ""))
    run_id = str(event.get("run_id", ""))
    network = str(event.get("network", NETWORK))

    thread = Thread(ledger=ledger_from_env(), subject="", run_id=run_id)
    try:
        corpus = corpus_from_env()
        offer = _offer(offer_id)
        if offer is None:
            thread.subject = network
            thread.append("run.failed", detail=f"no offer {offer_id!r} in the filing")
            return {"ok": False}

        thread.subject = subject_for_offer(network, offer)
        result = run_chore(
            corpus,
            offer,
            thread,
            analyst=bedrock.analyst_from_env(),
            critic=bedrock.critic_from_env(),
            scheduler=scheduler_from_env(),
            network=network,
            approver="",
        )
        thread.append("run.completed", **result.as_dict())
        return {"ok": True, "outcome": result.outcome}
    except Exception as error:  # noqa: BLE001 - a failed run must say so on the page
        thread.subject = thread.subject or network
        thread.append("run.failed", detail=type(error).__name__)
        return {"ok": False, "detail": type(error).__name__}

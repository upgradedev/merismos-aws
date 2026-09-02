"""One package, three deployments, three IAM roles.

What fixes a deployment's authority is its **role**, not its code. All three
Lambdas run this same handler; ``MERISMOS_ROLE`` decides which routes it will
serve, and IAM decides what it can reach whatever it decides to try. Those are
two different locks and both are needed: the role check stops the reader serving
``/publish`` at all, and IAM stops it succeeding if the check were ever wrong.

``/identity`` is the endpoint worth reading. It does not report configuration.
It **attempts** to read the publish credential and reports what came back, so
the privilege boundary is demonstrated by AWS refusing rather than asserted by
us. A flag saying "this role cannot publish" is a claim; an
``AccessDeniedException`` in the response body is evidence.
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
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        body = {}
    return method, path.rstrip("/") or "/", body if isinstance(body, dict) else {}


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """The Lambda entry point for all three deployments."""
    # A scheduled wake arrives as a plain payload rather than an HTTP event.
    if isinstance(event, dict) and event.get("source") == "merismos.deferral":
        return _reply(200, _wake(event))

    method, path, body = _route(event)
    me = role()

    try:
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
    """Who this process is, and what it is refused. Attempted, not configured."""
    me = role()
    reached, detail = _attempt_publish_credential()
    return {
        "role": me,
        "may_call": sorted(ROLE_TOOLS.get(me, frozenset())),
        "may_publish": me == "writer",
        "reaches_publish_credential": reached,
        "what_aws_said": detail,
        "note": (
            "reaches_publish_credential is the result of actually calling "
            "GetSecretValue just now, not a flag. The reader and the evaluator "
            "are refused by AWS IAM, not by any code in this repository"
        ),
        "build": os.environ.get("MERISMOS_BUILD_SHA", "unknown"),
        "model": os.environ.get("MERISMOS_MODEL", "none, deterministic only"),
        "critic": os.environ.get("MERISMOS_CRITIC_MODEL", "none"),
    }


def _attempt_publish_credential() -> tuple[bool, str]:
    """Ask for the credential and report what came back, whatever came back."""
    secret = os.environ.get("MERISMOS_PUBLISH_SECRET", "")
    if not secret:
        return False, "no publish secret is configured in this deployment"
    try:
        import boto3

        boto3.client("secretsmanager").get_secret_value(SecretId=secret)
    except Exception as error:  # noqa: BLE001 - the refusal is the answer
        return False, type(error).__name__
    return True, "granted"


def config() -> dict[str, Any]:
    """The bounds this fleet publishes about itself, readable with no account."""
    from .tools import DEFAULT_SCOPE, MAX_READ_BYTES, MAX_SEARCH_SCAN, READ_BUDGET

    return {
        "network": NETWORK,
        "read_scope": list(DEFAULT_SCOPE),
        "read_budget_per_run": READ_BUDGET,
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

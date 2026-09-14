"""One package, four deployments, three IAM roles.

What fixes a deployment's authority is its **role**, not its code. Every Lambda
runs this same handler; ``MERISMOS_ROLE`` decides which routes it will serve, and
IAM decides what it can reach whatever it decides to try. Those are two different
locks and both are needed: the role check stops the reader serving ``/publish`` at
all, and IAM stops it succeeding if the check were ever wrong.

There are four deployments and three identities, because ``runner`` is the reader
under a second function name and the reader's own IAM role. It exists for one
reason and it is not a permissions reason: a chore takes about nine minutes and a
page has to answer in under a second, and while they shared one reserved
concurrency they competed. Three chores in flight took the deployed site down.

``/identity`` is the endpoint worth reading. It does not report configuration.
It **attempts** two things and reports what AWS said to each: the write that
publishing actually needs, and a Secrets Manager canary that nothing reads. A
flag saying "this role cannot publish" is a claim; an ``AccessDeniedException``
in the response body is evidence.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from . import bedrock
from .approval import (
    ApprovalRefused,
    ApprovalStore,
    Receipt,
    authorise,
    digest,
    grant,
    published_history,
)
from .corpus import corpus_from_env
from .corpus import offers as read_offers
from .deferral import escalate, scheduler_from_env
from .fleet import (
    catalogue,
    new_run_id,
    record_key,
    run_chore,
    subject_for_offer,
    superseded_by_this_run,
)
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


class MalformedBody(ValueError):
    """The request body could not be read as the object every route expects.

    It used to become ``{}`` and the route ran with defaults, so a typo in a
    client's JSON started a run against whatever the defaults named. Nothing
    should run on a request nobody managed to phrase.
    """

    status = 400


class BodyTooLarge(MalformedBody):
    """A body larger than any screen or client of this API ever sends."""

    status = 413


# The largest honest body is a donor CSV (csv_intake.MAX_BYTES, 64 KiB) inside a
# JSON string, where escaping at most sextuples it. A mebibyte is well above that
# and well below what a Lambda accepts, so nothing honest is refused and nothing
# enormous is parsed.
MAX_BODY_BYTES = 1_048_576
# Every route reads a flat object with, at most, a list or an object inside it.
MAX_BODY_DEPTH = 16


def _refuse_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # Parsers disagree on which of two same-named fields wins, so a proxy and
    # this handler could each read a different request out of the same bytes.
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise MalformedBody(f"The request body names the field {key[:40]!r} twice.")
        seen[key] = value
    return seen


def _refuse_constant(name: str) -> Any:
    # Python's parser accepts NaN and Infinity; no JSON client emits them, and a
    # NaN compares false with every bound a route checks.
    raise MalformedBody(f"The request body contains {name}, which is not a JSON number.")


def _too_deep(value: Any, limit: int) -> bool:
    stack = [(value, 1)]
    while stack:
        item, level = stack.pop()
        if isinstance(item, dict):
            children = list(item.values())
        else:
            children = item if isinstance(item, list) else []
        for child in children:
            if isinstance(child, (dict, list)):
                if level + 1 > limit:
                    return True
                stack.append((child, level + 1))
    return False


def _route(event: Any) -> tuple[str, str, dict]:
    """Pull method, path and parsed body out of a Function URL or ALB event."""
    context = event.get("requestContext", {}) or {}
    http = context.get("http", {}) or {}
    method = (http.get("method") or event.get("httpMethod") or "GET").upper()
    path = http.get("path") or event.get("rawPath") or event.get("path") or "/"
    raw = event.get("body") or "{}"
    too_large = f"The request body is larger than {MAX_BODY_BYTES:,} bytes."
    if event.get("isBase64Encoded"):
        import base64

        if len(raw) > MAX_BODY_BYTES * 4 // 3 + 4:
            raise BodyTooLarge(too_large)
        try:
            raw = base64.b64decode(raw, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as why:
            raise MalformedBody("The request body could not be decoded as UTF-8 text.") from why
    if len(raw) > MAX_BODY_BYTES or len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        raise BodyTooLarge(too_large)
    content_type = ""
    for k, v in (event.get("headers") or {}).items():
        if k.lower() == "content-type":
            content_type = str(v).lower()
    if "application/x-www-form-urlencoded" in content_type:
        from urllib.parse import parse_qs

        body = {k: v[0] for k, v in parse_qs(raw).items()}
    else:
        deeper = f"The request body nests deeper than {MAX_BODY_DEPTH} levels."
        try:
            body = json.loads(raw, object_pairs_hook=_refuse_duplicate_keys,
                              parse_constant=_refuse_constant) if raw.strip() else {}
        except MalformedBody:
            raise
        except RecursionError as why:
            raise MalformedBody(deeper) from why
        except ValueError as why:
            raise MalformedBody("The request body is not valid JSON.") from why
        if not isinstance(body, dict):
            raise MalformedBody("The request body must be a JSON object.")
        if _too_deep(body, MAX_BODY_DEPTH):
            raise MalformedBody(deeper)
    query = event.get("queryStringParameters") or {}
    if isinstance(query, dict):
        body = {**query, **body}
    return method, path.rstrip("/") or "/", body


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """The Lambda entry point for every deployment."""
    from .correlation import attach

    return attach(event, context, _dispatch(event, context))


def _dispatch(event: Any, context: Any = None) -> dict[str, Any]:
    """Existing routes and guards; correlation metadata cannot change their inputs."""
    # A scheduled wake arrives as a plain payload rather than an HTTP event.
    if isinstance(event, dict) and event.get("source") == "merismos.deferral":
        return _reply(200, _wake(event))

    # So does a background chore, which the reader asked the runner to run because
    # it takes longer than a request is allowed to.
    from . import background

    if background.is_background(event):
        return _reply(200, _run_in_background(event))

    try:
        method, path, body = _route(event)
    except MalformedBody as why:
        return _reply(why.status, {"detail": str(why)})
    me = role()

    try:
        if path in {"/version", "/api/version"}:
            from .version import build_version

            if method != "GET":
                return _reply(405, {"detail": "Use GET for build identity."})
            return _reply(200, build_version())
        if path.startswith("/api/"):
            from .api import route as api_route

            return api_route(event, method, path, body)
        if method == "POST" and (path.startswith("/approve/") or path == "/offers/new"):
            from .api import route as api_route

            # Legacy aliases use the very same identity, fresh plan, consent,
            # revision and idempotency boundary. A typed name confers no authority.
            target = "/api/offers/new" if path == "/offers/new" else (
                f"/api/offers/{path.rsplit('/', 1)[-1]}/approve")
            return api_route(event, method, target, {**body, "mode": "live"})
        if method == "POST" and (path == "/run" or path.startswith("/offer/")):
            from .api import ApiError, coordinator

            try:
                coordinator(event, NETWORK)
            except ApiError as error:
                return _reply(error.status, {"detail": str(error)})
        html_reply = _screens(method, path, body)
        if html_reply is not None:
            return html_reply
        if path == "/identity":
            return _reply(
                200,
                identity(str(body.get("all", "")).strip().lower() in ("1", "yes", "true")),
            )
        if path == "/catalog":
            return _reply(200, catalogue())
        if path == "/config":
            return _reply(200, config())
        if path == "/offers":
            return _reply(200, {"offers": [o["id"] for o in read_offers(corpus_from_env())]})
        if path == "/thread" and method == "GET":
            return _reply(200, thread_of(body.get("run_id") or body.get("run") or ""))
        if path == "/run" and method == "POST":
            return _reply(200, run(body))
        if path == "/publish" and method == "POST":
            return publish(body)
        if path == "/publication-status" and method == "POST":
            return publication_status(body)
        if path == "/publication-capabilities" and method == "GET":
            return publication_capabilities()
        if path == "/intake" and method == "POST":
            return take_offer(body)
    except ApprovalRefused as refusal:
        return _reply(refusal.status, {"detail": str(refusal)})
    except Exception as error:  # noqa: BLE001 - never leak a stack trace outward
        return _reply(500, {"detail": f"{type(error).__name__}", "role": me})

    return _reply(404, {"detail": f"no route {method} {path} on the {me}"})


def identity(ask_the_others: bool = False) -> dict[str, Any]:
    """Who this process is, and what it is refused. Attempted, not configured.

    **Two probes, and the second one is the one that matters.**

    This endpoint used to report only the Secrets Manager read and the README
    called that "the publish credential". It is not. ``publish()`` never reads
    that secret; it calls ``s3:PutObject``. So the secret is a **canary**: a
    thing all three identities ask for so that a refusal is observable in a
    response body. Useful, and not the authority.

    The authority is the S3 write, so it is now probed too, by conditionally
    creating one fixed marker under a private ``probes/`` prefix rather than by
    reading a policy and believing it. A reader that were somehow granted the
    write would show up here even if the canary still said denied. Repeated
    probes exercise the permission without creating more object versions.
    """
    me = role()
    canary_reached, canary_said = _attempt_publish_credential()
    can_write, write_said = _attempt_publish_authority()
    answered: dict[str, Any] = {
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
    if not ask_the_others:
        # Named so a reader finds it without reading the source. The claim this
        # endpoint supports is about three identities and only one of them
        # answers here.
        answered["the_other_two"] = (
            "add ?all=1 to ask the evaluator and the writer the same two "
            "questions. They sit behind AWS_IAM Function URLs, so this is the "
            "only way to check them without credentials of your own"
        )
        return answered
    answered["others"] = _ask_the_other_identities()
    return answered


def _attempt_publish_authority() -> tuple[bool, str]:
    """Try the write that publishing actually needs, and report what came back.

    Conditionally creates one zero byte object under ``probes/``, which the
    bucket policy does **not** open to the public. ``IfNoneMatch`` means a
    repeated probe cannot overwrite the marker or create another version. S3
    checks authority before returning the expected precondition response, so
    an existing marker still proves the writer can attempt the real operation.
    """
    bucket = os.environ.get("MERISMOS_RECORDS_BUCKET", "")
    if not bucket:
        return False, "no records bucket is configured in this deployment"
    try:
        import boto3

        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=f"probes/identity-{role()}",
            Body=b"",
            IfNoneMatch="*",
        )
    except Exception as error:  # noqa: BLE001 - the refusal is the answer
        if _already_there(error):
            return True, _aws_said(error)
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


def _ask_the_other_identities() -> dict[str, Any]:
    """Ask the evaluator and the writer what AWS tells each of them.

    The reader holds ``lambda:InvokeFunction`` on both already: on the writer for
    publishing and filing offers, and on the evaluator for this probe alone, since
    the draft gate runs in-process in ``fleet.run_chore``. This spends that grant
    on the one thing a stranger cannot do for themselves: the other two sit behind
    Function URLs requiring AWS credentials, so their refusals, which are the ones
    carrying the argument, were unverifiable by anybody being asked to believe them.

    An identity that does not answer is reported as not having answered.
    Fabricating a denial for a role that never replied would be inventing the
    evidence this endpoint exists to gather.
    """
    import json as _json

    out: dict[str, Any] = {}
    for name in ("evaluator", "writer"):
        function = f"{os.environ.get('MERISMOS_PROJECT', 'merismos')}-{name}"
        try:
            import boto3

            answer = boto3.client("lambda").invoke(
                FunctionName=function,
                Payload=_json.dumps(
                    {
                        "requestContext": {"http": {"method": "GET", "path": "/identity"}},
                        "headers": {"content-type": "application/json"},
                        "body": "{}",
                    }
                ).encode("utf-8"),
            )
            reply = _json.loads(answer["Payload"].read())
            out[name] = _json.loads(reply.get("body", "{}"))
        except Exception as error:  # noqa: BLE001 - reported, never invented
            out[name] = {
                "reached": False,
                "what_happened": type(error).__name__,
                "note": (
                    f"{function} did not answer, so nothing is claimed about what "
                    f"AWS would tell it. An unreached identity is not a denied one"
                ),
            }
    return out


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
        "max_request_body_bytes": MAX_BODY_BYTES,
        "max_request_body_depth": MAX_BODY_DEPTH,
        "ledger": os.environ.get("MERISMOS_LEDGER", "dynamodb"),
        "deferrals_wake_on_a_schedule": bool(os.environ.get("MERISMOS_WAKE_TARGET_ARN")),
        # **The model, said out loud.** This endpoint existed to stop things
        # being implicit and left implicit the one thing a reader of an agent
        # entry most wants to establish. Three defects this week would have been
        # one line here: a model configured on the function that does not run
        # the chore, an offline path that constructed no agent at all, and a
        # screen that looked the same whether a model answered or failed.
        "role": role(),
        "analyst": _analyst_description(),
        "critic": os.environ.get("MERISMOS_CRITIC_MODEL", "").strip() or "none",
    }


def _analyst_description() -> str:
    """Which of the three paths this deployment is on, in one string.

    Not a boolean. "A model is configured" cannot distinguish a Bedrock
    inference profile from the scripted planner that drives the same agent loop
    with no network, and those are different claims about what a run means.
    """
    configured = os.environ.get("MERISMOS_MODEL", "").strip()
    if configured.lower() in ("scripted", "offline"):
        from .scripted import MODEL_ID

        return f"{MODEL_ID}, a scripted model driving the real agent loop with no network"
    if configured.lower() in ("none", "off", "stub"):
        return "none. The deterministic rules alone, and no agent is constructed"
    return configured or "none. MERISMOS_MODEL is unset, so no agent is constructed"


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
    every deployment carries every route, and only one identity may serve
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
    store = ApprovalStore()
    candidate = store.get(nonce)
    if candidate is None:
        return _reply(403, {"detail": "No approval on file."})
    if not re.fullmatch(r"records/offer-[0-9]+(?:-c[2-9][0-9]*|-c1[0-9]+)?\.md", key):
        return _reply(400, {"detail": "An approval must name an immutable record address.",
                            "write_state": "not_written"})
    if not store.acquire_lane(candidate):
        return _reply(409, {"detail": "Another same-category publication is pending or unknown.",
                            "write_state": "not_written"})
    attempt = {"write_attempted": False}
    try:
        response = _publish_locked(body, store, candidate, attempt)
    except Exception as error:
        if not attempt["write_attempted"]:
            store.release_lane(candidate)
            return _reply(503, {"detail": f"Prepublication failure: {type(error).__name__}.",
                                "write_state": "not_written"})
        raise
    if response["statusCode"] == 200 or json.loads(response["body"]).get(
        "write_state"
    ) == "not_written":
        store.release_lane(candidate)
    return response


def _publish_locked(body, store, candidate, attempt):
    from .api import evidence_digest, fairness_history
    from .background import completed_result

    nonce, key = str(body.get("nonce", "")), str(body.get("key", ""))
    content = str(body.get("body", ""))
    corpus = corpus_from_env()
    offer = _offer(candidate.offer_id) if candidate.offer_id else None
    result = completed_result(ledger_from_env().thread(candidate.run_id)) or {}
    if (not offer or not candidate.evidence_digest
            or result.get("outcome") not in ("awaiting_approval", "approved")
            or (result.get("verdict") or {}).get("passed") is not True
            or result.get("offer_id") != candidate.offer_id
            or result.get("draft_body") != content
            or candidate.category != offer.get("category")
            or candidate.evidence_digest != evidence_digest(
                corpus, offer, fairness_history({"mode": "live"}, NETWORK, offer))):
        return _reply(409, {"detail": "A fresh passing plan and exact approval are required.",
                            "write_state": "not_written"})
    from datetime import date

    if str(offer.get("collection_date", "")) < date.today().isoformat():
        return _reply(409, {"detail": "This collection date has passed.",
                            "write_state": "not_written"})
    approval = authorise(store, nonce, NETWORK, key, content)

    import boto3

    bucket = os.environ["MERISMOS_RECORDS_BUCKET"]
    try:
        attempt["write_attempted"] = True
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8", IfNoneMatch="*",
            Metadata={"approval-nonce": approval.nonce, "run-id": approval.run_id,
                      "content-digest": approval.content_digest},
        )
    except Exception as error:
        code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
        if code in ("AccessDenied", "AccessDeniedException", "PreconditionFailed",
                    "ConditionalRequestConflict"):
            return _reply(409 if _already_there(error) else 503,
                          {"detail": "Storage refused this publication. Review before retrying.",
                           "write_state": "not_written"})
        raise
    receipt = _publication_receipt(approval, bucket, time.time())
    _append_receipt(receipt)
    return _reply(200, receipt.as_dict())


def _publication_receipt(approval, bucket, published_at):
    return Receipt(
        nonce=approval.nonce,
        network=approval.network,
        key=approval.key,
        content_digest=approval.content_digest,
        approved_by=approval.approved_by,
        run_id=approval.run_id,
        published_url=f"https://{bucket}.s3.amazonaws.com/{approval.key}",
        published_at=published_at,
        offer_id=approval.offer_id, category=approval.category, orgs=approval.orgs,
    )


def _append_receipt(receipt):
    from .ledger import Entry

    # A recovered writer completion names the same event. Storage rejects a
    # duplicate event instead of appending another publication to the history.
    ledger_from_env().append_linked(Entry(
        kind="record.published", subject=NETWORK, run_id=receipt.run_id,
        entry_id=f"receipt-{receipt.nonce}", body=receipt.as_dict()))


def publication_status(body):
    """Recover only a new approval's proven object; never rewrite record bytes."""
    if role() != "writer":
        return _reply(403, {"detail": "Publication recovery belongs to the writer."})
    approval = ApprovalStore().get(str(body.get("nonce", "")))
    if not approval or not approval.evidence_digest:
        return _reply(409, {"detail": "This approval cannot be reconciled automatically."})
    import boto3

    bucket = os.environ["MERISMOS_RECORDS_BUCKET"]
    try:
        saved = boto3.client("s3").get_object(Bucket=bucket, Key=approval.key)
    except Exception:
        return _reply(200, {"state": "unknown", "detail": "The saved object is not confirmed."})
    content = saved["Body"].read().decode("utf-8")
    if (saved.get("Metadata", {}).get("approval-nonce") != approval.nonce
            or digest(NETWORK, approval.key, content) != approval.content_digest):
        return _reply(200, {"state": "unknown",
                            "detail": "The object does not match this approval."})
    receipt = _publication_receipt(approval, bucket, saved["LastModified"].timestamp())
    _append_receipt(receipt)
    ApprovalStore().release_lane(approval)
    return _reply(200, {"state": "recorded", "receipt": receipt.as_dict()})


def take_offer(body: dict) -> dict[str, Any]:
    """File one offer a person typed. The writer's, and nobody else's.

    Everything a coordinator submits is untrusted, and this is the one place
    untrusted text enters the corpus by design. So the writer does not accept an
    offer: it accepts **the form**, and builds the offer itself with the same
    intake rules the reader showed the person. A reader that had been talked
    into assembling something the rules refuse cannot get it filed here.

    Two bounds that are worth stating plainly, because they are what make an
    open intake safe to hold behind the identity that can also publish records:

    * the key is **constructed**, never taken from the caller, so this route
      cannot be used to write over a published record or a member's entry;
    * the id must be this network's own sequence, so ``../`` and every other
      shape of traversal fails before anything is built.
    """
    if role() != "writer":
        return _reply(
            403,
            {
                "detail": (
                    f"the {role()} identity cannot file an offer. Writing is the "
                    f"writer's, and an offer is written where the fleet reads"
                )
            },
        )

    from . import intake

    offer_id = str(body.get("offer_id", "")).strip()
    if not re.fullmatch(r"offer-\d{1,9}", offer_id):
        return _reply(400, {"detail": f"{offer_id!r} is not an offer id in this network"})

    form = body.get("form")
    if not isinstance(form, dict):
        return _reply(400, {"detail": "an intake needs the form that was filled in"})

    try:
        offer = intake.offer_from_form(form, offer_id)
    except intake.Rejected as refusal:
        return _reply(400, {"detail": str(refusal)})

    import boto3

    bucket = os.environ.get("MERISMOS_CORPUS_BUCKET", "")
    if not bucket:
        return _reply(500, {"detail": "no corpus is configured, so an offer cannot be filed"})
    prefix = os.environ.get("MERISMOS_CORPUS_PREFIX", "").strip("/")
    key = f"offers/{offer_id}.json"
    try:
        # IfNoneMatch is what makes this an **add** rather than a write. S3
        # refuses the request outright if that key already exists, so an intake
        # cannot replace an offer the fleet has already read or decided about,
        # and that is a property of the storage rather than of this function.
        # Same reason the approval is spent with a condition expression.
        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=f"{prefix}/{key}" if prefix else key,
            Body=intake.as_document(offer).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
            IfNoneMatch="*",
        )
    except Exception as error:  # noqa: BLE001 - one of these is not a failure
        if _already_there(error):
            return _reply(
                409,
                {
                    "detail": (
                        f"{offer_id} was taken while you were typing, which happens when "
                        f"two people file at once. Nothing was overwritten. Send it again "
                        f"and it will get the next id."
                    )
                },
            )
        raise

    # Recorded on the network's own thread, so an offer that arrives from a
    # person is as traceable as one that arrived in the fixture.
    thread = Thread(ledger=ledger_from_env(), subject=NETWORK, run_id=new_run_id())
    thread.append("offer.filed", offer_id=offer_id, title=offer["title"], donor=offer["donor"])
    return _reply(200, {"offer_id": offer_id, "key": key, "filed": True})


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


def publication_capabilities() -> dict[str, Any]:
    """Read-only permission checks under the actual writer's AWS identity.

    This does not mint consent, spend a nonce, append history or put an object.
    A missing head still exercises GetItem authorization, not custody continuity.
    """
    if role() != "writer":
        return _reply(403, {"detail": "Only the private writer serves this capability probe."})
    from .api import evidence_digest
    from .ledger import DynamoDbLedger

    checks = {}
    try:
        corpus = corpus_from_env()
        available = read_offers(corpus)
        if not available:
            raise ValueError("No offer available for the evidence read")
        evidence_digest(corpus, available[0])
        checks["corpus_freshness_read"] = {
            "allowed": True, "backend": getattr(corpus, "backend", "unknown")}
    except Exception as error:
        checks["corpus_freshness_read"] = {"allowed": False, "detail": _aws_said(error)}
    try:
        ledger = DynamoDbLedger()
        ledger.client.get_item(TableName=ledger.table_name, ConsistentRead=True,
                               Key={"subject": {"S": "custody:capability-probe"},
                                    "entry_id": {"S": "head"}})
        checks["custody_head_read"] = {"allowed": True}
    except Exception as error:
        checks["custody_head_read"] = {"allowed": False, "detail": _aws_said(error)}
    return _reply(200, {"role": "writer", "read_only": True, "checks": checks,
                        "limits": "Permission evidence only; not publication or chain proof."})


def thread_of(run_id: str) -> dict[str, Any]:
    """One run, as a chain. Follow it back.

    **Both spellings are accepted, and a missing one is said rather than
    implied.** This read ``run_id`` while every URL the site produces carries
    ``?run=``, so copying a run id out of the address bar onto this endpoint,
    which is the obvious thing to do with an endpoint called thread, returned an
    empty list. An empty list is also what a real run with no entries returns, so
    the answer to "you did not name a run" was indistinguishable from the answer
    to "that run recorded nothing". Silence read as data, in the endpoint whose
    entire purpose is evidence.
    """
    if not run_id:
        return {
            "run_id": "",
            "entries": [],
            "detail": (
                "name a run: /thread?run=run-xxxxxxxx. The run id is in the "
                "address of any decision page. This is not an empty run, it is "
                "no run at all, and the difference matters here"
            ),
            "note": "each entry names the entry before it in parent_id",
        }
    entries = ledger_from_env().thread(run_id)
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
    # The reason recorded when the decision was parked, which says why it is
    # worth asking again rather than why it was refused. The fallback is for a
    # schedule created before payloads carried it, which will still be in flight
    # when this ships.
    why = str(event.get("reason", "")).strip()
    return escalate(
        thread,
        deferral_id=str(event.get("deferral_id", "")),
        reason=why or "the deferral reached its date and nobody had come back",
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
        offer, result = _the_run_they_read(offer_id, str(body.get("run", "")).strip())
        if offer is None:
            return _html(404, web.page("Not found", "<h1>No such offer</h1>"))
        if result is None:
            return _html(
                404,
                web.page(
                    "Nothing to approve",
                    "<h1>There is no decision here to approve</h1>"
                    "<div class='note'>An approval covers the bytes <strong>one "
                    "particular run</strong> produced, and this address names no run that "
                    "finished. That happens with an old link, or after a run has aged out "
                    "of the thread.</div>"
                    "<div class='note'>Merismos will not decide again on your behalf to "
                    "fill the gap. A card assembled from a run nobody read is a card that "
                    "can say something different from the screen somebody thought they "
                    "were approving.</div>"
                    f"<p><a class='btn' href='/offer/{offer_id}'>Ask the fleet</a>"
                    f"   <a class='btn secondary' href='/'>Back to offers</a></p>",
                ),
            )
        # Never on top of a record somebody may already have acted on. The
        # helper returns the base key until one has been published and the next
        # in the series after that.
        #
        # **Fails closed, and the choice is not obvious.** This was an
        # unguarded call until it was noticed: `key` used to be a string
        # interpolation that could not fail, and turning it into a ledger read
        # put a transient DynamoDB error on the one route where a person is in
        # the loop. If the recall fails we do not know whether a record for this
        # offer already exists. Falling back to the base key is the choice that
        # looks reasonable and it publishes on top of a record somebody may have
        # acted on, which is what this feature exists to prevent. So the card is
        # not assembled, and the page says which of the two it is.
        try:
            published = [e.body for e in published_history(ledger_from_env(), NETWORK, [offer])]
        except Exception as error:  # noqa: BLE001 - reported, never guessed past
            return _html(
                503,
                web.page(
                    "Cannot assemble the card",
                    "<h1>The card cannot be assembled right now</h1>"
                    "<div class='note stop'><strong>The thread could not be read, so "
                    "whether a record for this offer has already been published is "
                    f"unknown.</strong> ({web._e(type(error).__name__)})</div>"
                    "<div class='note'>Merismos will not publish on a guess. If a "
                    "record exists, writing to the same address would replace "
                    "something somebody may already have acted on, and a correction "
                    "takes the next address in the series rather than the one in "
                    "use. Nothing has been decided again and nothing has been lost: "
                    "try once the thread is readable.</div>"
                    f"<p><a class='btn' href='/offer/{offer_id}'>Back to the decision</a>"
                    "   <a class='btn secondary' href='/'>Back to offers</a></p>",
                ),
            )
        key = record_key(offer_id, published)

        if method == "GET":
            if result.draft is None:
                return _html(200, web.decision(result, offer, NETWORK))
            return _html(200, web.approval_card(result, offer, NETWORK, key))

        return _reply(405, {"detail": "Use the authenticated coordinator API with exact consent."})

    if path == "/offers/new":
        from . import intake

        if method == "GET":
            return _html(200, web.new_offer_form())

        # Validated here so a coordinator is told immediately, while the message
        # they typed is still on the screen. Validated again by the writer,
        # because this identity cannot write and is not trusted to have checked.
        try:
            offer_id = intake.next_offer_id(read_offers(corpus_from_env()))
            intake.offer_from_form(body, offer_id)
        except intake.Rejected as refusal:
            return _html(400, web.new_offer_form(str(refusal), body))

        status, detail = _ask_the_writer_to_file(offer_id, body)
        if status != 200:
            return _html(status, web.new_offer_form(detail, body))
        return _redirect(f"/offer/{offer_id}")

    if path.startswith("/record/"):
        return _one_record(path.rsplit("/", 1)[-1])

    if path == "/records":
        return _html(200, web.page("Published", _published_index()))

    if path.startswith("/chain/"):
        offer_id = path.rsplit("/", 1)[-1]
        offer = _offer(offer_id)
        if offer is None:
            return _html(404, web.page("Not found", "<h1>No such offer</h1>"))
        from . import custody

        entries = [e for e in published_history(ledger_from_env(), NETWORK, [offer])
                   if e.body.get("key", "").startswith(f"records/{offer_id}.")
                   or e.body.get("key", "").startswith(f"records/{offer_id}-c")]
        run = entries[0].run_id if entries else str(body.get("run", ""))
        thread = ledger_from_env().thread(run) if run else []
        return _html(200, web.custody_chain(offer, custody.summary(offer_id, thread)))

    return None


def _the_run_they_read(offer_id: str, run_id: str):
    """The finished run this approval is about, rebuilt from the thread.

    A card that re-decides is a card that can disagree with the screen the person
    read on the way to it. The digest binds the card to the publish, which covers
    tampering; this is what binds the card to the decision, which covers honesty,
    and with a model in the fleet the two runs genuinely can differ.

    It also has to be this way for the deployed path to work at all. A chore takes
    minutes and a gateway integration gets thirty seconds, so a route that ran one
    inside the request was a route that timed out.

    **There is no fallback.** A run id that names nothing gives back no result,
    and the route sends the person to ask the fleet rather than quietly deciding
    for them. Deciding again is the very thing that made the card untrustworthy.
    """
    offer = _offer(offer_id)
    if offer is None:
        return None, None
    if not run_id:
        return offer, None

    from . import background, web

    record = background.completed_result(ledger_from_env().thread(run_id))
    if not record or str(record.get("offer_id", offer_id)) != offer_id:
        return offer, None
    return offer, web.recorded(record)


def _slug(key: str) -> str:
    """``records/offer-4471-c2.md`` to ``offer-4471-c2``, for the record route."""
    return key.removeprefix("records/").removesuffix(".md")


def _mark_superseded(published: list[dict]) -> list[dict]:
    """Say which published records a later one replaced.

    ``record_key`` never overwrites: a correction takes the next key in the
    series and the original stays exactly where it is. That is the right
    behaviour and on its own it leaves a reader with two records for the same
    offer, disagreeing, and nothing to say which one the network stands behind.

    The marking lives here rather than in the old object because editing a
    published record is the thing being avoided. The list is the place to say it.
    """
    def parts(key: str) -> tuple[str, int]:
        """The offer this record is for, and which version of it this is.

        Read from the key rather than from the order the ledger returned, which
        is not guaranteed and would silently mark the wrong record superseded if
        it ever changed.
        """
        stem = key.removeprefix("records/").removesuffix(".md")
        offer_id, _, version = stem.partition("-c")
        return offer_id, int(version) if version.isdigit() else 1

    latest: dict[str, tuple[int, str]] = {}
    for row in published:
        offer_id, version = parts(row["key"])
        if version >= latest.get(offer_id, (0, ""))[0]:
            latest[offer_id] = (version, row["key"])

    for row in published:
        offer_id, _ = parts(row["key"])
        current = latest.get(offer_id, (0, row["key"]))[1]
        row["superseded_by"] = current if current != row["key"] else ""
    return published


def _one_record(slug: str) -> dict[str, Any]:
    """Serve one published record, current or superseded, from the thread.

    Read from the provenance thread rather than from S3, the same as every other
    live screen: the thread was always the memory, and a record rebuilt from it
    is a record a judge can also read back.

    ``slug`` is ``offer-4471`` or ``offer-4471-c2``. The first names the base
    record and the second names a correction, and both are served, because
    somebody was sent the superseded address and may have acted on it.
    """
    from . import background, web

    key = f"records/{slug}.md"
    offer_id = slug.split("-c")[0]
    offer = _offer(offer_id)
    if offer is None:
        return _html(404, web.page("Not found", "<h1>No such offer</h1>"))

    try:
        entries = published_history(ledger_from_env(), NETWORK, [offer])
    except Exception:  # noqa: BLE001 - an unreadable thread is not a missing record
        return _html(
            503,
            web.page(
                "Cannot read the record",
                "<h1>The record could not be read</h1>"
                "<div class='note stop'>The thread is not readable right now. The "
                "record itself is published and unaffected; this screen is what "
                "cannot be assembled.</div>",
            ),
        )

    published = [e.body for e in entries]
    mine = next((r for r in published if str(r.get("key", "")) == key), None)
    if mine is None:
        return _html(
            404,
            web.page(
                "Not published",
                f"<h1>Nothing published at {web._e(key)}</h1>"
                "<div class='note'>A record appears here once somebody has approved "
                "one. Merismos does not publish without a person.</div>"
                f"<p><a class='btn' href='/offer/{web._e(offer_id)}'>Ask the fleet</a></p>",
            ),
        )

    # ``superseded_by_this_run`` names the address currently in use. If it is not
    # this one, this one has been replaced.
    latest = superseded_by_this_run(offer_id, published)
    superseded_by = latest if latest and latest != key else ""

    thread = ledger_from_env().thread(str(mine.get("run_id", "")))
    record = background.completed_result(thread) or {}
    body_text = str(record.get("draft_body") or "")
    if not body_text:
        body_text = (
            "The record was published and the run that produced it is no longer "
            "in the thread, so the bytes cannot be shown here. The published "
            f"address is {mine.get('published_url') or key}."
        )
    return _html(200, web.one_record(key, body_text, mine, superseded_by))


def _published_index() -> str:
    """Every record published so far, from the thread rather than from S3."""
    bucket = os.environ.get("MERISMOS_RECORDS_BUCKET", "")
    base = f"https://{bucket}.s3.amazonaws.com/" if bucket else ""
    rows = ""
    try:
        entries = published_history(ledger_from_env(), NETWORK, read_offers(corpus_from_env()))
        published = [
            {
                "key": str(e.body.get("key", "")),
                "url": e.body.get("published_url") or (base + str(e.body.get("key", ""))),
                "approved_by": str(e.body.get("approved_by", "")),
            }
            for e in entries
        ]
        for row in _mark_superseded(published):
            note = (
                "<br><span class='why'>Superseded by "
                f"<a href='/record/{_slug(row['superseded_by'])}'>{row['superseded_by']}</a>. "
                "Kept because somebody may have acted on it.</span>"
                if row.get("superseded_by")
                else ""
            )
            rows += (
                f"<tr><td><a id='{row['key']}' href='/record/{_slug(row['key'])}'>"
                f"{row['key']}</a>{note}</td>"
                f"<td>{row['approved_by']}</td></tr>"
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

    This runs in the runner, invoked with InvocationType Event (see
    ``background.start``). The runner carries the reader's role in its own
    concurrency pool and has a 900 second budget, rather than the gateway's 30 or
    the reader's 60. The chore is
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


def _ask_the_writer_to_file(offer_id: str, form: dict) -> tuple[int, str]:
    """Hand the coordinator's form to the one identity that may write.

    The reader gains **no** authority from this feature. It already holds
    ``lambda:InvokeFunction`` on the writer, because that is how an approved
    record gets published, and filing an offer travels the same road. What the
    writer receives is the form as typed, not an offer this side assembled, so
    the writer validates it itself rather than trusting a caller's parse. That
    is the same reason the writer recomputes the digest at publish time.
    """
    import boto3

    function = os.environ.get("MERISMOS_WRITER_FUNCTION", "")
    if not function:
        return 502, "No writer is configured, so an offer cannot be filed."

    payload = json.dumps(
        {
            "requestContext": {"http": {"method": "POST", "path": "/intake"}},
            "body": json.dumps({"offer_id": offer_id, "form": dict(form)}),
        }
    )
    try:
        answer = boto3.client("lambda").invoke(FunctionName=function, Payload=payload)
        written = json.loads(answer["Payload"].read())
    except Exception as error:  # noqa: BLE001 - the coordinator must be told
        return 502, f"That could not be filed: {_aws_said(error)}"

    status = int(written.get("statusCode", 502))
    if status != 200:
        detail = json.loads(written.get("body", "{}")).get("detail", "the writer refused")
        # The writer's own status is passed through rather than flattened to a
        # bad gateway. A clash of ids is the person's to resolve and a refused
        # field is theirs to correct; neither is an outage and neither should
        # read like one.
        return (status if status in (400, 409) else 502), detail
    return 200, ""


def _already_there(error: Exception) -> bool:
    """Did S3 refuse this write because the object already existed?

    ``PreconditionFailed`` is what a conditional create returns when the key is
    taken. It is the control working, so it is reported as a full inbox rather
    than as a fault.
    """
    response = getattr(error, "response", None) or {}
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in ("PreconditionFailed", "ConditionalRequestConflict") or status == 412

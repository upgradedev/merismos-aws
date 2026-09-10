"""Evaluation-only one-shot Converse collector, not the Strands tool loop.

Export/recovery/smoke are offline. Collection requires a parent-configured exact
grant and manual CI context. No retry, repair, fallback, tools or CountTokens.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from merismos.bedrock import INSTRUCTIONS, SPECIALIST_BRIEF

ROOT = Path(__file__).resolve().parents[1]
BASE = "6d401f79dea8d9e5568021df42f56c082d385c4e"
MODEL = "eu.anthropic.claude-opus-5"
REGION = "eu-west-1"
MAX_OUTPUT = 768
TEMPLATE_OVERHEAD = 4096
MAX_INPUT = 16384
REPOSITORY = "upgradedev/merismos-aws"
REFERENCE_RATES = {"input": "5.50", "output": "27.50"}  # Not a grant or measured bill.
FROZEN_CODE = {
    "scripts/evaluate_interpretation.py":
        "de90549249e8227984141ac84fadfc0e0ecf648895a092d4831544ca91e56f09",
    "src/merismos/bedrock.py":
        "4c7781ab44ac12ba1bc796abf3c3106a6a51fa736acfdade9be6e80a233e4532",
}
SPEC = importlib.util.spec_from_file_location(
    "frozen_interpretation", ROOT / "scripts/evaluate_interpretation.py"
)
ev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ev)


def export(source):
    """No gold read or model construction. Preserve the application's prompt."""
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("exact source SHA required")
    for path, digest in FROZEN_CODE.items():
        # Git LF content identity; a Windows checkout may have CRLF line endings.
        if ev.sha((ROOT / path).read_bytes().replace(b"\r\n", b"\n")) != digest:
            raise ValueError(f"frozen code changed: {path}")
    ev.frozen("protocol")
    rows = []
    for case in ev.inputs():
        offer = case["adapter_input"]["offer"]
        question = (
            f"Offer {offer.get('id')}: {offer.get('title')!r} from "
            f"{offer.get('donor')}. {offer.get('quantity')} {offer.get('unit')}, "
            f"category {offer.get('category')}. The donor's note says: "
            f"{offer.get('note')!r}\n\n"
            f"Decide whether this offer can be apportioned as it stands."
        )
        request = {
            "modelId": MODEL,
            "system": [{"text": f"{SPECIALIST_BRIEF['premises']}\n{INSTRUCTIONS}"}],
            "messages": [{"role": "user", "content": [
                {"text": question},
                {"text": "Pre-opened source snapshot (tools unavailable in this one-shot "
                         "transport):\n" + ev.canonical(case["adapter_input"])}]}],
            "inferenceConfig": {"maxTokens": MAX_OUTPUT},
            "additionalModelRequestFields": {"thinking": {"type": "disabled"}},
        }
        # Entire JSON, not only visible prose, plus a deliberately large framing
        # allowance. This is a reviewed byte-token upper-bound assumption, not a
        # measured tokenizer count or a claim valid for arbitrary future models.
        wire = ev.canonical(request).encode("utf-8")
        bound = len(wire) + TEMPLATE_OVERHEAD
        if bound > MAX_INPUT:
            raise ValueError("finite input ceiling exceeded")
        rows.append({"case_id": case["case_id"], "input_sha256": case["input_sha256"],
                     "source_hashes": {p: s["sha256"] for p, s in
                                       case["adapter_input"]["sources"].items()},
                     "request": request, "request_sha256": ev.sha(wire),
                     "request_utf8_bytes": len(wire), "input_token_bound": bound,
                     "supplied_source_provenance": ev.citations(case["adapter_input"])})
    return {"source_commit": source, "frozen_base": BASE, "hashes": ev.PINS,
            "model_id": MODEL, "region": REGION, "max_output_tokens": MAX_OUTPUT,
            "template_overhead_tokens": TEMPLATE_OVERHEAD,
            "adapter": "ONE_SHOT_CONVERSE_PREOPENED_NOT_STRANDS",
            "citation_semantics": "mechanical supplied-source provenance, NOT model-selected "
                                  "citations or semantic entailment",
            "candidate_citation_policy": "Only actual model-returned citations or []; never "
                                         "copy supplied_source_provenance into evaluator citations",
            "input_bound_assumption": "one token per serialized UTF8 byte plus4096 framing; "
                                      "requires parent approval for this exact model",
            "requests": rows, "request_set_sha256": ev.sha(ev.canonical(rows)),
            "max_request_utf8_bytes": max(r["request_utf8_bytes"] for r in rows),
            "sum_request_utf8_bytes": sum(r["request_utf8_bytes"] for r in rows),
            "sum_input_token_bound": sum(r["input_token_bound"] for r in rows)}


def create_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def money(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,4}(?:\.\d{1,8})?", value):
        raise ValueError("price/budget must be a finite positive decimal string")
    amount = Decimal(value)
    if not amount.is_finite() or not 0 < amount <= 1000:
        raise ValueError("price/budget outside finite bounds")
    return amount


def token_cost(input_tokens, output_tokens, rates):
    return ((Decimal(input_tokens) * money(rates["input"])
             + Decimal(output_tokens) * money(rates["output"])) / Decimal(1000000)).quantize(
                 Decimal("0.00000001"), rounding=ROUND_CEILING)


def budget_plan(plan, rates):
    costs = [token_cost(row["input_token_bound"], MAX_OUTPUT, rates)
             for row in plan["requests"]]
    return {"rates_usd_per_million": rates, "per_case_reserved_usd": list(map(str, costs)),
            "total_reserved_usd": str(sum(costs, Decimal(0))), "calls": len(costs),
            "refund_policy": "NONE: errors/unknown outcomes consume full reservation"}


def binding(plan):
    keys = ("source_commit", "frozen_base", "hashes", "request_set_sha256", "model_id",
            "region", "max_output_tokens", "template_overhead_tokens", "adapter")
    return {**{key: plan[key] for key in keys}, "max_input_tokens": MAX_INPUT, "calls": 14}


def ci_context():
    return {key: os.environ.get(env, "") for key, env in {
        "repository": "GITHUB_REPOSITORY", "workflow_ref": "GITHUB_WORKFLOW_REF",
        "run_number": "GITHUB_RUN_NUMBER", "run_attempt": "GITHUB_RUN_ATTEMPT",
        "run_id": "GITHUB_RUN_ID", "event": "GITHUB_EVENT_NAME", "source": "GITHUB_SHA",
    }.items()}


def validate_grant(grant, configured_digest, plan, context, now, *, synthetic=False):
    if not configured_digest or ev.sha(ev.canonical(grant)) != configured_digest:
        raise ValueError("parent-configured grant digest mismatch")
    if plan != export(plan["source_commit"]) or grant.get("binding") != binding(plan):
        raise ValueError("source/model/config/protocol/request manifest binding mismatch")
    required = {"schema", "grant_id", "authority", "binding", "run", "expires_at",
                "rates", "budget_usd", "byte_bound_approved", "standard_no_extra_charges"}
    authority = "SYNTHETIC_NO_AUTHORITY" if synthetic else "PARENT_CONFIGURED_SINGLE_RUN"
    if (set(grant) != required or type(grant["schema"]) is not int or grant["schema"] != 1
            or grant["authority"] != authority):
        raise ValueError("grant schema/authority mismatch")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", grant["grant_id"]):
        raise ValueError("invalid grant ID")
    if (context["event"] != "workflow_dispatch" or context["repository"] != REPOSITORY
            or context["source"] != plan["source_commit"] or context["run_attempt"] != "1"
            or not re.fullmatch(r"[1-9][0-9]*", context["run_number"])
            or not re.fullmatch(r"[1-9][0-9]*", context["run_id"])
            or not context["workflow_ref"].startswith(REPOSITORY + "/.github/workflows/ci.yml@")):
        raise ValueError("manual exact-source first-attempt CI context required")
    if grant["run"] != {key: context[key] for key in
                        ("repository", "workflow_ref", "run_number", "run_attempt")}:
        raise ValueError("one-shot workflow run binding mismatch")
    expires = datetime.fromisoformat(grant["expires_at"])
    if expires.tzinfo is None or not now < expires <= now + timedelta(hours=2):
        raise ValueError("grant expired or expiry exceeds two-hour window")
    if grant["byte_bound_approved"] is not True or grant["standard_no_extra_charges"] is not True:
        raise ValueError("parent must approve byte bound and standard no-extra-charge assumptions")
    if set(grant["rates"]) != {"input", "output"} or any(
        money(grant["rates"][key]) < money(REFERENCE_RATES[key]) for key in REFERENCE_RATES
    ):
        raise ValueError("conservative finite rates required")
    cost = budget_plan(plan, grant["rates"])
    if money(grant["budget_usd"]) > 5 or Decimal(cost["total_reserved_usd"]) > money(
        grant["budget_usd"]
    ):
        raise ValueError("finite allocated budget denies full fixed cohort")
    return cost


class Journal:
    """Create-only hash-chained events, fsync plus flushed full stdout backup."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.events = []

    def record(self, kind, **body):
        previous = ev.sha(ev.canonical(self.events[-1])) if self.events else None
        event = {"sequence": len(self.events), "previous_sha256": previous,
                 "kind": kind, **body}
        # Print before file write so a disk error still leaves the full response
        # in CI stdout. No request proceeds until the file fsync also succeeds.
        print("MERISMOS_JOURNAL " + ev.canonical(event), flush=True)
        create_json(self.directory / f"{len(self.events):04d}.json", event)
        self.events.append(event)


def load_events(directory):
    events = []
    for path in sorted(Path(directory).glob("*.json")):
        event = ev.strict_json(path.read_bytes())
        previous = ev.sha(ev.canonical(events[-1])) if events else None
        if (path.name != f"{len(events):04d}.json" or event["sequence"] != len(events)
                or event["previous_sha256"] != previous):
            raise ValueError("journal gap/order/hash mismatch; never silently omit events")
        events.append(event)
    if not events or events[0]["kind"] != "planned":
        raise ValueError("journal has no complete initial panel")
    return events


def reconstruct(events):
    header = events[0]
    plan = header["plan"]
    rows = deepcopy(header["slots"])
    reserved = Decimal(0)
    for event in events[1:]:
        if "ordinal" not in event:
            continue
        row = rows[event["ordinal"]]
        if event["kind"] == "reserved":
            row.update(status="unknown", reserved_usd=event["reserved_usd"])
            reserved += Decimal(event["reserved_usd"])
        elif event["kind"] == "response":
            row.update(aws_response=event["response"],
                       aws_response_sha256=ev.sha(ev.canonical(event["response"])))
        elif event["kind"] == "completed":
            row.update(status="completed", usage=event["usage"], request_id=event["request_id"],
                       priced_usage_usd=event["priced_usage_usd"])
        elif event["kind"] == "error":
            row.update(status="error", error=event["error"])
    for row in rows:
        if row["status"] != "completed":
            continue
        response = row["aws_response"]
        try:
            blocks = response["output"]["message"]["content"]
            if (response.get("stopReason") != "end_turn" or len(blocks) != 1
                    or set(blocks[0]) != {"text"} or not isinstance(blocks[0]["text"], str)):
                raise ValueError("expected one final text response; no repair or continuation")
            raw = blocks[0]["text"]
            # Original prompt asks for status/reason, not a citation sidecar.
            # Never fabricate model proof from mechanically preloaded sources.
            row.update(result={"raw_response": raw, "citations": []}, raw_sha256=ev.sha(raw))
        except (KeyError, TypeError, ValueError) as error:
            row.update(status="error", error=str(error))
    return {"hashes": plan["hashes"], "attempts": rows, "mode": header["mode"],
            "source_commit": plan["source_commit"], "context": header["context"],
            "grant": header["grant"], "reserved_usd_no_refunds": str(reserved),
            "supplied_source_provenance_is_not_model_citations": True,
            "model": {"id": MODEL, "config": plan["requests"][0]["request"]["inferenceConfig"],
                      "usage": "PER_ATTEMPT_OR_UNKNOWN", "cost": "NOT_A_BILL",
                      "producer_run": header["context"]["run_id"],
                      "producer_source_commit": plan["source_commit"]},
            "requested_model_id": MODEL, "returned_model_id": "UNKNOWN"}


def finish(directory, events):
    bundle = reconstruct(events)
    create_json(Path(directory) / "receipts.json", bundle)
    return ev.evaluate(ev.saved_adapter(bundle), Path(directory) / "replay",
                       bundle["source_commit"], "SAVED_RESPONSE_REPLAY",
                       bundle["context"]["run_id"], bundle["model"], saved_receipts=bundle)


def check_usage(response, row, rates):
    usage, meta = response["usage"], response["ResponseMetadata"]
    if (any(type(usage.get(key)) is not int or usage[key] < 0
            for key in ("inputTokens", "outputTokens", "totalTokens"))
            or usage["inputTokens"] > row["input_token_bound"]
            or usage["outputTokens"] > MAX_OUTPUT
            or usage["totalTokens"] != usage["inputTokens"] + usage["outputTokens"]
            or usage.get("cacheWriteInputTokens", 0) != 0
            or usage.get("cacheReadInputTokens", 0) != 0
            or meta.get("HTTPStatusCode") != 200 or meta.get("RetryAttempts") != 0
            or not isinstance(meta.get("RequestId"), str) or not meta["RequestId"]):
        raise ValueError("unknown or excessive usage/request identity; retain reservation and stop")
    if response.get("serviceTier", {"type": "default"}) != {"type": "default"}:
        raise ValueError("nonstandard service tier")
    return usage, meta["RequestId"], str(token_cost(
        usage["inputTokens"], usage["outputTokens"], rates))


def sdk_client():
    import boto3
    from botocore.config import Config

    return boto3.client("bedrock-runtime", region_name=REGION,
                        endpoint_url=f"https://bedrock-runtime.{REGION}.amazonaws.com",
                        config=Config(connect_timeout=5, read_timeout=30,
                                      retries={"total_max_attempts": 1, "mode": "standard"}))


def collect(plan, grant, digest, context, directory, factory=sdk_client,
            clock=lambda: datetime.now(timezone.utc), *, synthetic=False):
    journal = Journal(Path(directory) / "journal")
    slots = [{"case_id": r["case_id"], "input_sha256": r["input_sha256"],
              "source_hashes": r["source_hashes"], "status": "not_run"}
             for r in plan["requests"]]
    journal.record("planned", plan=plan, grant=grant, context=context, slots=slots,
                   mode="SOURCE_FAKE" if synthetic else "BEDROCK_CONVERSE_EVALUATION_ONLY")
    try:
        cost = validate_grant(grant, digest, plan, context, clock(), synthetic=synthetic)
    except (ValueError, TypeError, KeyError) as error:
        journal.record("denied", error=str(error))
        finish(directory, journal.events)
        raise
    client = None
    for ordinal, row in enumerate(plan["requests"]):
        # Recheck expiry before EACH reservation; never reuse a consumed slot.
        try:
            validate_grant(grant, digest, plan, context, clock(), synthetic=synthetic)
        except (ValueError, TypeError, KeyError) as error:
            journal.record("stopped", error=str(error))
            break
        journal.record("reserved", ordinal=ordinal, request=row["request"],
                       request_sha256=row["request_sha256"],
                       reserved_usd=cost["per_case_reserved_usd"][ordinal])
        try:
            if client is None:
                client = factory()
            response = client.converse(**deepcopy(row["request"]))
        except Exception as error:
            journal.record("error", ordinal=ordinal, error=f"{type(error).__name__}: {error}")
            break  # Unknown outcome: no retry, no refund, remaining slots NOT_RUN.
        journal.record("response", ordinal=ordinal, response=response)  # Before ANY parsing.
        try:
            usage, request_id, priced = check_usage(response, row, grant["rates"])
        except (ValueError, KeyError, TypeError) as error:
            journal.record("error", ordinal=ordinal, error=str(error))
            break
        journal.record("completed", ordinal=ordinal, usage=usage, request_id=request_id,
                       priced_usage_usd=priced)
    return finish(directory, journal.events)


def fake_grant(plan, context, now):
    return {"schema": 1, "grant_id": "SOURCE_FAKE_NOT_AUTHORIZED",
            "authority": "SYNTHETIC_NO_AUTHORITY", "binding": binding(plan),
            "run": {key: context[key] for key in
                    ("repository", "workflow_ref", "run_number", "run_attempt")},
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "rates": dict(REFERENCE_RATES), "budget_usd": "2.00", "byte_bound_approved": True,
            "standard_no_extra_charges": True}


class FakeClient:
    """Offline plumbing control. The request ID and usage below are NOT AWS evidence."""

    def converse(self, **_request):
        return {"output": {"message": {"content": [{"text": ev.canonical({
            "status": "needs_changes", "reason": "Synthetic plumbing control; human review."})}]}},
                "stopReason": "end_turn", "usage": {
                    "inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
                "ResponseMetadata": {"HTTPStatusCode": 200, "RetryAttempts": 0,
                                     "RequestId": "SYNTHETIC_NOT_AWS"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("export", "source-smoke", "preflight", "collect",
                                        "recover"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--journal", type=Path)
    args = parser.parse_args()
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    plan = export(source)
    if args.mode == "recover":
        if args.journal is None:
            parser.error("recover requires --journal; it never resumes collection")
        report = finish(args.output, load_events(args.journal))
        return 0 if report["input_aligned_complete"] else 1
    if args.mode in ("export", "source-smoke"):
        create_json(args.output / "requests.json", plan)
        create_json(args.output / "reference-cost-NOT-A-GRANT.json", {
            "authority": "NONE", **budget_plan(plan, REFERENCE_RATES)})
        if args.mode == "export":
            return 0
        context = {"repository": REPOSITORY, "workflow_ref": REPOSITORY
                   + "/.github/workflows/ci.yml@refs/heads/SYNTHETIC",
                   "source": source, "event": "workflow_dispatch", "run_number": "1",
                   "run_attempt": "1", "run_id": "1"}
        grant = fake_grant(plan, context, datetime.now(timezone.utc))
        report = collect(plan, grant, ev.sha(ev.canonical(grant)), context, args.output / "fake",
                         factory=FakeClient, synthetic=True)
        return 0 if report["input_aligned_complete"] else 1
    # Only these two modes read authorization. Neither a CLI flag nor the
    # reference-price artifact can supply or activate the parent-configured grant.
    context = ci_context()
    grant = ev.strict_json(os.environ.get("MERISMOS_EVAL_GRANT_JSON", "{}"))
    digest = os.environ.get("MERISMOS_EVAL_GRANT_SHA256", "")
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, source], cwd=ROOT, check=True)
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=ROOT, text=True).strip():
        raise ValueError("dirty tracked source is not the authorized commit")
    if args.mode == "preflight":
        create_json(args.output / "preflight-input.json", {"plan": plan, "grant": grant})
        try:
            cost = validate_grant(grant, digest, plan, context, datetime.now(timezone.utc))
        except (ValueError, KeyError, TypeError) as error:
            create_json(args.output / "preflight-refused.json", {"error": str(error),
                        "all_14_slots": "NOT_RUN", "model_constructed": False})
            raise
        create_json(args.output / "preflight.json", {"plan": plan, "grant": grant, "cost": cost})
        return 0
    report = collect(plan, grant, digest, context, args.output)
    return 0 if report["input_aligned_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

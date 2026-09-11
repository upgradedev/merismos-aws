"""Offline Merismos response -> structured correlation log -> text Lambda REPORT.

Adapted from the portfolio Archon telemetry/correlate.py design. Standard library
only; no AWS, network, inference, price lookup or runtime instrumentation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

SCHEMA = "merismos-x1-report-input-v1"
ID = r"[A-Za-z0-9-]{16,80}"
UUID = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
HEADERS = {"x-merismos-request-id": "request_id",
           "x-merismos-lambda-request-id": "lambda_request_id",
           "x-merismos-correlation-mode": "mode"}
NUMBER = r"[0-9]{1,8}(?:\.[0-9]{1,6})?"
REPORT = re.compile(
    rf"REPORT RequestId: (?P<lambda_request_id>{ID})\s+"
    rf"Duration: (?P<duration_ms>{NUMBER}) ms\s+"
    r"Billed Duration: (?P<billed_duration_ms>[0-9]{1,8}) ms\s+"
    r"Memory Size: (?P<memory_mb>[0-9]{1,5}) MB\s+"
    r"Max Memory Used: (?P<max_memory_used_mb>[0-9]{1,5}) MB"
    rf"(?:\s+Init Duration: (?P<init_duration_ms>{NUMBER}) ms)?"
    r"(?:\s+Status: (?P<runtime_status>success|error|timeout))?"
    r"(?:\s+Error Type: (?P<error_type>[A-Za-z0-9_.-]{1,100}))?\s*"
)
MAX_BYTES = 10 * 1024 * 1024


def valid_id(value, pattern=ID):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def strict_json(raw):
    def nonfinite(_value):
        raise ValueError("nonfinite JSON")
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=nonfinite)


def capture_response(ordinal, status, header_pairs):
    """Pass RESPONSE header pairs, retaining duplicate denial but never cookies/tokens."""
    selected = []
    for name, value in header_pairs:
        if isinstance(name, str) and name.lower() in HEADERS:
            field = HEADERS[name.lower()]
            valid = value in ("lambda-context", "no-lambda-context") if field == "mode" else (
                valid_id(value, UUID if field == "request_id" else ID))
            selected.append([name.lower(), value if valid else None])
    return {"ordinal": ordinal, "status": status, "response_headers": selected}


def response_identity(request):
    if not isinstance(request, dict):
        return None
    pairs = request.get("response_headers")
    if not isinstance(pairs, list) or len(pairs) != 3:
        return None
    found = {}
    for pair in pairs:
        if (not isinstance(pair, list) or len(pair) != 2
                or not isinstance(pair[0], str) or pair[0].lower() not in HEADERS):
            return None
        field = HEADERS[pair[0].lower()]
        if field in found:
            return None
        found[field] = pair[1]
    if (found.get("mode") != "lambda-context"
            or not valid_id(found.get("request_id"), UUID)
            or not valid_id(found.get("lambda_request_id"))):
        return None
    return found


def resource_identity(expected):
    """Merismos logs lack resource identity: require exported group ARN and stream version."""
    if not isinstance(expected, dict) or set(expected) != {
        "function_arn", "function_version", "log_group_arn"
    }:
        return None
    arn, version = expected["function_arn"], expected["function_version"]
    if not isinstance(arn, str) or not isinstance(version, str):
        return None
    match = re.fullmatch(r"arn:aws:lambda:([a-z0-9-]{3,32}):([0-9]{12}):function:"
                         r"([A-Za-z0-9_-]{1,64})", arn)
    if not match or not re.fullmatch(r"\$LATEST|[1-9][0-9]{0,11}", version):
        return None
    region, account, function = match.groups()
    group = f"/aws/lambda/{function}"
    group_arn = f"arn:aws:logs:{region}:{account}:log-group:{group}"
    if expected["log_group_arn"] != group_arn:
        return None
    return {**expected, "log_group": group, "region": region, "account_id": account}


def event_resource(event, resource):
    stream = event.get("logStreamName")
    match = re.fullmatch(r"[0-9]{4}/[0-9]{2}/[0-9]{2}/\[([^\]]+)\][a-f0-9]{16,64}",
                         stream) if isinstance(stream, str) else None
    return (event.get("logGroupArn") == resource["log_group_arn"]
            and event.get("logGroupName") == resource["log_group"]
            and match is not None and match[1] == resource["function_version"])


def report_fields(message):
    match = REPORT.fullmatch(message)
    if not match:
        return None
    result = match.groupdict()
    if any(result[key] is not None and Decimal(result[key]) > 3600000 for key in
           ("duration_ms", "billed_duration_ms", "init_duration_ms")):
        return None
    if not 1 <= int(result["memory_mb"]) <= 10240 or (
        int(result["max_memory_used_mb"]) > int(result["memory_mb"])
    ):
        return None
    return result  # Exact decimal strings and units, not prices or inferred dollars.


def index_events(events):
    receipts, reports = defaultdict(list), defaultdict(list)
    issues = []
    for index, event in enumerate(events):
        message = event.get("message") if isinstance(event, dict) else None
        if not isinstance(message, str) or len(message.encode()) > 4096:
            issues.append({"event": index, "reason": "unsupported_event"})
            continue
        text = message.strip()
        if text.startswith("REPORT "):
            report = report_fields(text)
            if report is None:
                issues.append({"event": index, "reason": "unsupported_report"})
            else:
                reports[report["lambda_request_id"]].append((index, event, report))
        elif text.startswith("{"):
            try:
                receipt = strict_json(text)
            except ValueError:
                issues.append({"event": index, "reason": "malformed_json_log"})
                continue
            if receipt.get("event") == "merismos.http.correlation":
                if (set(receipt) != {"event", "request_id", "lambda_request_id", "mode", "status"}
                        or not valid_id(receipt.get("request_id"), UUID)):
                    issues.append({"event": index, "reason": "malformed_correlation"})
                else:
                    receipts[receipt["request_id"]].append((index, event, receipt))
            elif receipt.get("type") == "platform.report":
                issues.append({"event": index, "reason": "json_report_not_supported"})
        elif "merismos.http.correlation" in text or "platform.report" in text:
            issues.append({"event": index, "reason": "unsupported_log_wrapper"})
    return receipts, reports, issues


def correlate(bundle):
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
        raise ValueError("unsupported input schema")
    requests, events = bundle.get("requests"), bundle.get("events")
    planned = bundle.get("planned_requests")
    if type(planned) is not int or not 1 <= planned <= 1000:
        raise ValueError("expected independently retained planned_requests in1..1000")
    if not isinstance(requests, list) or len(requests) > 1000:
        raise ValueError("expected at most1000 retained request slots, including failures")
    if not isinstance(events, list) or len(events) > 10000:
        raise ValueError("expected at most10000 exported events")
    resource = resource_identity(bundle.get("expected_resource"))
    receipts, reports, event_issues = index_events(events)
    issues = [] if len(requests) == planned else ["planned_supplied_count_mismatch"]
    retained = requests + [None] * max(0, planned - len(requests))
    identities = [response_identity(request) for request in retained]
    counts = {field: Counter(value[field] for value in identities if value)
              for field in ("request_id", "lambda_request_id")}
    # A second correlation log mapping another response to the same invocation
    # makes the attribution ambiguous even if that response slot was omitted.
    log_ids = Counter(row[2].get("lambda_request_id") for group in receipts.values()
                      for row in group if valid_id(row[2].get("lambda_request_id")))
    rows = []
    for ordinal, (request, observed) in enumerate(zip(retained, identities, strict=True), 1):
        errors = list(issues)
        row = {"ordinal": ordinal, "request_id": observed["request_id"] if observed else None,
               "lambda_request_id": observed["lambda_request_id"] if observed else None,
               "matched": False, "resource": None, "report": None, "errors": errors,
               "aws_infrastructure_usd": None, "model_usd": None}
        rows.append(row)
        if (not isinstance(request, dict) or type(request.get("ordinal")) is not int
                or request["ordinal"] != ordinal):
            errors.append("invalid_or_missing_slot_ordinal")
        if resource is None:
            errors.append("unknown_or_inconsistent_expected_resource")
        if observed is None:
            errors.append("missing_duplicate_or_invalid_response_identity")
            continue
        for field in counts:
            if counts[field][observed[field]] != 1:
                errors.append(f"duplicate_api_{field}")
        found, billed = receipts[observed["request_id"]], reports[observed["lambda_request_id"]]
        if len(found) != 1:
            errors.append("missing_correlation_log" if not found else "duplicate_correlation_log")
        if len(billed) != 1:
            errors.append("missing_report" if not billed else "duplicate_report")
        if log_ids[observed["lambda_request_id"]] > 1:
            errors.append("ambiguous_invocation_mapping")
        if len(found) != 1 or len(billed) != 1 or resource is None:
            continue
        log_index, log, receipt = found[0]
        report_index, report_log, report = billed[0]
        if any(receipt.get(key) != value for key, value in observed.items()):
            errors.append("correlation_identity_mismatch")
        if (not event_resource(log, resource) or not event_resource(report_log, resource)
                or log.get("logStreamName") != report_log.get("logStreamName")):
            errors.append("resource_or_stream_mismatch")
        status = request.get("status")
        if (type(status) is not int or not 100 <= status <= 599
                or type(receipt.get("status")) is not int or receipt["status"] != status):
            errors.append("response_status_mismatch")
        if not errors:
            row.update(matched=True, report=report,
                       resource={**resource, "log_stream": log["logStreamName"]},
                       correlation_event_index=log_index, report_event_index=report_index)
    matched = [row for row in rows if row["matched"]]
    return {"schema": "merismos-x1-report-result-v1", "planned_requests": planned,
            "supplied_requests": len(requests), "retained_slots": len(rows),
            "matched_requests": len(matched), "unmatched_slots": len(rows) - len(matched),
            "complete": len(matched) == planned and not issues and not event_issues,
            "complete_means": "exact supplied correlation coverage, not API success or full cost",
            "rows": rows, "input_issues": issues, "event_issues": event_issues,
            "matched_report_billed_duration_ms": str(sum(
                (Decimal(row["report"]["billed_duration_ms"]) for row in matched), Decimal(0))),
            "aws_infrastructure_usd": None, "model_usd": None,
            "cost_status": "UNKNOWN_NOT_DERIVED_FROM_DURATION",
            "limitations": "Supplied bytes, not authenticated AWS origin. Merismos response/log "
            "does not attest source SHA/function ARN/version; resource attribution requires "
            "separately exported exact group ARN and standard stream version. No custom groups, "
            "JSON platform reports, async fleet, other services, billed USD, model latency or SLA. "
            "Absence of a retained planned request cannot be recovered from logs alone."}


def write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def export(source, output):
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("input exceeds10MiB bound")
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "input.json", raw)  # Durable original bytes BEFORE any parse.
    try:
        result = correlate(strict_json(raw))
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        result = {"schema": "merismos-x1-report-result-v1", "complete": False,
                  "status": "INPUT_REFUSED", "error": str(error),
                  "planned_requests": None, "aws_infrastructure_usd": None, "model_usd": None}
    encoded = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    write_new(output / "result.json", encoded)
    manifest = {"input.json": hashlib.sha256(raw).hexdigest(),
                "result.json": hashlib.sha256(encoded).hexdigest(),
                "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_new(output / "manifest.json", (json.dumps(manifest, indent=2) + "\n").encode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return 0 if export(args.input, args.output)["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Synthetic offline REPORT correlation, never actual AWS timing/cost evidence."""

import hashlib
import importlib.util
import json
import socket
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest

from merismos import handler

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/correlate_lambda_reports.py"
SPEC = importlib.util.spec_from_file_location("report_exporter", SCRIPT)
x1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(x1)
REQUEST = "11111111-2222-4333-8444-555555555555"
LAMBDA = "66666666-7777-4888-9999-aaaaaaaaaaaa"
GROUP = "/aws/lambda/merismos-fixture"
GROUP_ARN = "arn:aws:logs:eu-west-1:123456789012:log-group:" + GROUP
STREAM = "2026/09/11/[12]abcdef0123456789abcdef0123456789"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempts = []

    def forbidden(*_args, **_kwargs):
        attempts.append(True)
        raise AssertionError("REPORT exporter must never create AWS clients or sockets")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(boto3, "client", forbidden)
    yield
    assert not attempts, "caught network/SDK attempts still fail"


def event(message):
    return {"logGroupName": GROUP, "logGroupArn": GROUP_ARN,
            "logStreamName": STREAM, "message": message}


def bundle():
    return {"schema": x1.SCHEMA, "planned_requests": 1,
            "expected_resource": {
                "function_arn": "arn:aws:lambda:eu-west-1:123456789012:function:merismos-fixture",
                "function_version": "12", "log_group_arn": GROUP_ARN},
            "requests": [x1.capture_response(1, 200, [
                ("X-Merismos-Request-ID", REQUEST), ("X-Merismos-Lambda-Request-ID", LAMBDA),
                ("X-Merismos-Correlation-Mode", "lambda-context")])],
            "events": [event(json.dumps({"event": "merismos.http.correlation",
                                         "request_id": REQUEST, "lambda_request_id": LAMBDA,
                                         "mode": "lambda-context", "status": 200})),
                       event(f"REPORT RequestId: {LAMBDA}\tDuration: 15.74 ms\t"
                             "Billed Duration: 147 ms\tMemory Size: 128 MB\t"
                             "Max Memory Used: 56 MB\tInit Duration: 130.49 ms\n")]}


def test_actual_handler_headers_log_to_offline_export_fullflow(tmp_path, monkeypatch, capsys):
    response = handler.handler({"httpMethod": "GET", "path": "/api/version"},
                               SimpleNamespace(aws_request_id=LAMBDA))
    assert response["statusCode"] == 200
    data = bundle()
    data["requests"] = [x1.capture_response(1, 200, response["headers"].items())]
    data["events"][0] = event(capsys.readouterr().out.strip())
    source, output = tmp_path / "source.json", tmp_path / "export"
    raw = json.dumps(data).encode()
    source.write_bytes(raw)
    monkeypatch.setattr(sys, "argv", ["correlate_lambda_reports", "--input", str(source),
                                     "--output", str(output)])
    assert x1.main() == 0
    result = json.loads((output / "result.json").read_bytes())
    assert result["complete"] and result["matched_requests"] == result["planned_requests"] == 1
    assert result["rows"][0]["report"]["duration_ms"] == "15.74"
    assert result["rows"][0]["report"]["init_duration_ms"] == "130.49"
    assert result["rows"][0]["resource"]["function_version"] == "12"
    assert result["rows"][0]["resource"]["log_stream"] == STREAM
    assert result["matched_report_billed_duration_ms"] == "147"
    assert result["aws_infrastructure_usd"] is result["model_usd"] is None
    manifest = json.loads((output / "manifest.json").read_bytes())
    for name in ("input.json", "result.json"):
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == manifest[name]
    assert manifest["implementation_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert (output / "input.json").read_bytes() == raw
    with pytest.raises(FileExistsError):
        x1.export(source, output)
    assert (output / "input.json").read_bytes() == raw


@pytest.mark.parametrize("defect", [
    "missing_header", "duplicate_header_case", "invalid_header", "no_context",
    "missing_log", "duplicate_log", "missing_report", "duplicate_report", "wrong_log_id",
    "wrong_lambda_id", "wrong_status", "bool_status", "wrong_group", "wrong_account",
    "missing_group_arn", "wrong_region", "wrong_version", "wrong_stream", "unknown_resource",
    "inconsistent_resource", "duplicate_response", "duplicate_lambda", "ambiguous_mapping",
    "ordinal", "dropped_slot", "extra_slot",
])
def test_negative_joins_keep_denominator_and_unknown_cost(defect):
    data = bundle()
    request = data["requests"][0]
    receipt = json.loads(data["events"][0]["message"])
    if defect == "missing_header":
        request["response_headers"].pop()
    elif defect == "duplicate_header_case":
        request["response_headers"][2] = ["X-MERISMOS-REQUEST-ID", REQUEST]
    elif defect == "invalid_header":
        request["response_headers"][0][1] = "bad\r\nheader"
    elif defect == "no_context":
        request["response_headers"][2][1] = "no-lambda-context"
    elif defect == "missing_log":
        data["events"].pop(0)
    elif defect == "duplicate_log":
        data["events"].append(deepcopy(data["events"][0]))
    elif defect == "missing_report":
        data["events"].pop()
    elif defect == "duplicate_report":
        data["events"].append(deepcopy(data["events"][1]))
    elif defect == "wrong_log_id":
        receipt["request_id"] = "00000000-0000-4000-8000-000000000000"
    elif defect == "wrong_lambda_id":
        receipt["lambda_request_id"] = REQUEST
    elif defect in ("wrong_status", "bool_status"):
        receipt["status"] = 500 if defect == "wrong_status" else True
    elif defect == "wrong_group":
        data["events"][1]["logGroupName"] += "-other"
    elif defect == "wrong_account":
        data["events"][1]["logGroupArn"] = GROUP_ARN.replace("123456789012", "999999999999")
    elif defect == "missing_group_arn":
        del data["events"][0]["logGroupArn"]
    elif defect == "wrong_region":
        data["events"][0]["logGroupArn"] = GROUP_ARN.replace("eu-west-1", "eu-west-2")
    elif defect == "wrong_version":
        data["events"][1]["logStreamName"] = STREAM.replace("[12]", "[13]")
    elif defect == "wrong_stream":
        data["events"][1]["logStreamName"] = STREAM.replace("abcdef", "fedcba")
    elif defect == "unknown_resource":
        data["expected_resource"] = None
    elif defect == "inconsistent_resource":
        data["expected_resource"]["function_arn"] += "-other"
    elif defect in ("duplicate_response", "duplicate_lambda"):
        data["planned_requests"] = 2
        extra = deepcopy(request)
        extra["ordinal"] = 2
        if defect == "duplicate_lambda":
            extra["response_headers"][0][1] = "00000000-0000-4000-8000-000000000000"
        data["requests"].append(extra)
    elif defect == "ambiguous_mapping":
        duplicate = {**receipt, "request_id": "00000000-0000-4000-8000-000000000000"}
        data["events"].append(event(json.dumps(duplicate)))
    elif defect == "ordinal":
        request["ordinal"] = True
    elif defect == "dropped_slot":
        data["planned_requests"] = 2
    elif defect == "extra_slot":
        data["requests"].append(None)
    if defect != "missing_log":
        data["events"][0]["message"] = json.dumps(receipt)
    result = x1.correlate(data)
    assert result["planned_requests"] == data["planned_requests"]
    assert result["supplied_requests"] == len(data["requests"])
    assert result["retained_slots"] == max(len(data["requests"]), data["planned_requests"])
    assert result["matched_requests"] == 0 and not result["complete"]
    assert all(row["errors"] and row["report"] is None for row in result["rows"])
    assert result["aws_infrastructure_usd"] is None and result["model_usd"] is None


def test_two_reordered_requests_exact_join_and_http_failure_is_not_hidden():
    first, second = bundle(), bundle()
    second = json.loads(json.dumps(second).replace(REQUEST, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
                        .replace(LAMBDA, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
                        .replace("147 ms", "947 ms").replace('"status": 200', '"status": 409'))
    first["planned_requests"] = 2
    second["requests"][0]["ordinal"] = 2
    first["requests"].extend(second["requests"])
    # Receipt JSON is encoded inside the message, so set its status explicitly.
    receipt = json.loads(second["events"][0]["message"])
    receipt["status"] = 409
    second["events"][0]["message"] = json.dumps(receipt)
    first["events"] = [second["events"][1], first["events"][0], second["events"][0],
                       event("START unrelated informational line"), first["events"][1]]
    result = x1.correlate(first)
    assert result["complete"] and result["matched_requests"] == 2
    assert [row["report"]["billed_duration_ms"] for row in result["rows"]] == ["147", "947"]
    assert result["matched_report_billed_duration_ms"] == "1094"
    assert "not API success" in result["complete_means"]
    assert result["aws_infrastructure_usd"] is None


@pytest.mark.parametrize("message", [
    "REPORT RequestId: unsupported", '{"type":"platform.report","record":{}}',
    '{"event":"merismos.http.correlation","event":"duplicate"}',
    '{"event":"merismos.http.correlation","request_id":null}',
    '{"anything":NaN}', "prefix merismos.http.correlation unsupported", "x" * 4097, None,
])
def test_unsupported_events_never_claim_complete(message):
    data = bundle()
    data["events"].append(event(message))
    result = x1.correlate(data)
    assert not result["complete"] and result["event_issues"]
    assert result["planned_requests"] == 1


@pytest.mark.parametrize("old,new", [("15.74", "NaN"), ("15.74", "99999999"),
                                     ("128 MB", "0 MB"), ("56 MB", "129 MB"),
                                     ("147 ms", "-1 ms")])
def test_invalid_report_numeric_fields_are_unknown(old, new):
    data = bundle()
    data["events"][1]["message"] = data["events"][1]["message"].replace(old, new)
    assert x1.correlate(data)["matched_requests"] == 0


def test_capture_denies_duplicates_but_does_not_retain_private_headers():
    captured = x1.capture_response(1, 200, [("Authorization", "private"), ("Set-Cookie", "secret"),
        ("X-Merismos-Request-ID", REQUEST), ("x-merismos-request-id", "bad\r\nheader")])
    assert captured["response_headers"] == [["x-merismos-request-id", REQUEST],
                                            ["x-merismos-request-id", None]]
    assert x1.response_identity(captured) is None
    assert "private" not in json.dumps(captured) and "secret" not in json.dumps(captured)


@pytest.mark.parametrize("raw", [b"{", b'{"schema":1,"schema":2}', b'{"bad":Infinity}',
                                 b'{"nested":' * 1100 + b'0' + b'}' * 1100])
def test_invalid_input_retained_before_parse_with_refusal_and_manifest(tmp_path, raw):
    source = tmp_path / "invalid.json"
    source.write_bytes(raw)
    result = x1.export(source, tmp_path / "out")
    assert not result["complete"] and result["status"] == "INPUT_REFUSED"
    assert (tmp_path / "out/input.json").read_bytes() == raw
    assert (tmp_path / "out/manifest.json").exists()


def test_bounds_and_empty_missing_panel_do_not_become_success(tmp_path):
    data = bundle()
    data["requests"] = []
    result = x1.correlate(data)
    assert result["planned_requests"] == result["unmatched_slots"] == 1
    assert not result["complete"]
    data["events"] = [None] * 10001
    with pytest.raises(ValueError, match="10000"):
        x1.correlate(data)
    source = tmp_path / "large.json"
    source.write_bytes(b"x" * (x1.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="10MiB"):
        x1.export(source, tmp_path / "oversize")
    assert not (tmp_path / "oversize").exists()

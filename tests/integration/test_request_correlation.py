"""Source-only correlation controls. Context IDs below are synthetic fixtures."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from merismos import correlation, handler

LAMBDA_ID = "12345678-1234-1234-1234-123456789012"


def event(path="/api/version", method="GET"):
    return {"requestContext": {"requestId": "forged-gateway-id", "http": {
        "method": method, "path": path}}, "headers": {
            "x-merismos-request-id": "caller-must-not-control-this",
            "x-merismos-lambda-request-id": "caller-must-not-control-this",
            "x-merismos-session": "sensitive-token-never-log",
            "authorization": "sensitive-auth-never-log"},
            "body": '{"request_id":"business-id-never-log","mode":"sandbox"}'}


@pytest.mark.parametrize("method,status", [("GET", 200), ("POST", 405)])
def test_handler_uses_only_context_id_logs_exact_join_and_preserves_body(method, status, capsys):
    request = event(method=method)
    original = handler._dispatch(request)
    reply = handler.handler(request, SimpleNamespace(aws_request_id=LAMBDA_ID))
    assert reply["statusCode"] == status
    assert reply["body"] == original["body"]
    assert all(reply["headers"][key] == value for key, value in original["headers"].items())
    headers = reply["headers"]
    assert headers["x-merismos-lambda-request-id"] == LAMBDA_ID
    assert headers["x-merismos-correlation-mode"] == "lambda-context"
    assert str(UUID(headers["x-merismos-request-id"])) == headers["x-merismos-request-id"]
    logged = capsys.readouterr().out.strip()
    assert json.loads(logged) == {
        "event": "merismos.http.correlation", "request_id": headers["x-merismos-request-id"],
        "lambda_request_id": LAMBDA_ID, "mode": "lambda-context", "status": status}
    assert "sensitive" not in logged and "business-id" not in logged and "forged" not in logged


@pytest.mark.parametrize("context", [None, {}, SimpleNamespace(),
                                     SimpleNamespace(aws_request_id="bad\r\nheader"),
                                     SimpleNamespace(aws_request_id=7),
                                     SimpleNamespace(aws_request_id="x" * 81)])
def test_missing_or_invalid_lambda_context_never_fabricated(context, capsys):
    response = handler.handler(event(), context)
    assert "x-merismos-lambda-request-id" not in response["headers"]
    assert response["headers"]["x-merismos-correlation-mode"] == "no-lambda-context"
    assert json.loads(capsys.readouterr().out)["lambda_request_id"] is None


def test_local_requests_have_distinct_ids_and_non_api_responses_are_untouched(capsys):
    first, second = handler.handler(event()), handler.handler(event())
    assert first["headers"]["x-merismos-request-id"] != second["headers"]["x-merismos-request-id"]
    capsys.readouterr()
    response = {"statusCode": 200, "headers": {}, "body": "unchanged"}
    assert correlation.attach(event("/version"), None, response) is response
    assert correlation.attach(None, None, response) is response
    assert capsys.readouterr().out == ""


def test_unavailable_log_sink_does_not_change_completed_response(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("simulated closed log sink")

    monkeypatch.setattr("builtins.print", unavailable)
    response = handler.handler(event())
    assert response["statusCode"] == 200
    assert response["headers"]["x-merismos-correlation-mode"] == "no-lambda-context"

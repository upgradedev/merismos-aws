"""Additive HTTP-to-invocation metadata, never authorization or business identity."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from uuid import uuid4


def attach(event, context, response):
    """Only API replies; no bodies, tokens, paths or caller-supplied IDs in logs."""
    if not isinstance(event, dict):
        return response
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    path = http.get("path") or event.get("rawPath") or event.get("path") or ""
    if not isinstance(path, str) or not path.startswith("/api/"):
        return response
    request_id = str(uuid4())
    lambda_id = getattr(context, "aws_request_id", None)
    if not isinstance(lambda_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{16,80}", lambda_id):
        lambda_id = None
    mode = "lambda-context" if lambda_id else "no-lambda-context"
    headers = {**response.get("headers", {}), "x-merismos-request-id": request_id,
               "x-merismos-correlation-mode": mode}
    if lambda_id:
        headers["x-merismos-lambda-request-id"] = lambda_id
    # Lost optional telemetry must not change a completed business response.
    with suppress(OSError):
        print(json.dumps({"event": "merismos.http.correlation", "request_id": request_id,
                          "lambda_request_id": lambda_id, "mode": mode,
                          "status": response["statusCode"]}, sort_keys=True), flush=True)
    return {**response, "headers": headers}

"""Offline release-prerequisite controls. Executed exclusively by existing CI."""

import importlib.util
import json
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_preflight", ROOT / "infra/backend_release_preflight.py"
)
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
COMMIT = "a" * 40
BACKEND = "b" * 40


def reply(index=1):
    headers = Message()
    headers["Content-Type"] = "application/json; charset=utf-8"
    headers["X-Merismos-Correlation-Mode"] = "lambda-context"
    headers["X-Merismos-Request-Id"] = f"12345678-1234-1234-1234-{index:012d}"
    headers["X-Merismos-Lambda-Request-Id"] = f"87654321-4321-4321-4321-{index:012d}"
    body = {"application": "merismos", "status": "known", "source": "ci_package",
            "schema_version": 1, "commit": BACKEND}
    return 200, headers, json.dumps(body).encode()


def good_git(*args):
    return SimpleNamespace(returncode=0, stdout=COMMIT if args == ("rev-parse", "HEAD") else "")


def test_distinct_lambda_replies_and_equal_runtime_pass_without_writes():
    rows = iter([reply(1), reply(2)])
    calls = []

    def run_git(*args):
        calls.append(args)
        return good_git(*args)

    result = P.inspect(COMMIT, lambda: next(rows), run_git)
    assert result["status"] == "PASSED"
    assert len(result["observations"]) == 2
    assert calls == [("rev-parse", "HEAD"),
                     ("merge-base", "--is-ancestor", BACKEND, COMMIT),
                     ("diff", "--exit-code", BACKEND, COMMIT, "--", *P.RUNTIME_PATHS)]


@pytest.mark.parametrize("name", ["content-type", "x-merismos-request-id",
                                 "x-merismos-lambda-request-id", "x-merismos-correlation-mode"])
@pytest.mark.parametrize("damage", ["missing", "duplicate", "invalid"])
def test_required_headers_fail_closed(name, damage):
    status, headers, raw = reply()
    if damage != "duplicate":
        del headers[name]
    if damage != "missing":
        headers[name] = "invalid"
    with pytest.raises(ValueError):
        P.decode_version((status, headers, raw))


@pytest.mark.parametrize("key,value", [("application", "other"), ("status", "unknown"),
                                     ("source", "unknown"), ("schema_version", True),
                                     ("schema_version", 2), ("commit", "not-a-sha")])
def test_unknown_version_never_passes(key, value):
    status, headers, raw = reply()
    body = json.loads(raw)
    body[key] = value
    with pytest.raises(ValueError):
        P.decode_version((status, headers, json.dumps(body).encode()))


@pytest.mark.parametrize("raw", [b"", b"x" * 4097, b"{}", b"null", b"[]", b"invalid"])
def test_invalid_body_never_passes(raw):
    status, headers, _ = reply()
    with pytest.raises(ValueError):
        P.decode_version((status, headers, raw))


@pytest.mark.parametrize("status", [301, 401, 404, 500])
def test_non_success_is_not_compatibility(status):
    _, headers, raw = reply()
    with pytest.raises(ValueError):
        P.decode_version((status, headers, raw))


def test_replayed_response_is_not_two_invocations():
    with pytest.raises(ValueError, match="Repeated invocation"):
        P.inspect(COMMIT, reply, good_git)


def test_repeated_lambda_with_distinct_server_ids_refuses():
    first = reply(1)
    status, headers, raw = reply(2)
    headers.replace_header("X-Merismos-Lambda-Request-Id",
                           first[1]["X-Merismos-Lambda-Request-Id"])
    replies = iter([first, (status, headers, raw)])
    with pytest.raises(ValueError, match="lambda_request_id"):
        P.inspect(COMMIT, lambda: next(replies), good_git)


def test_backend_change_between_requests_is_refused():
    status, headers, raw = reply(2)
    body = json.loads(raw)
    body["commit"] = "c" * 40
    replies = iter([reply(1), (status, headers, json.dumps(body).encode())])
    with pytest.raises(ValueError, match="changed"):
        P.inspect(COMMIT, lambda: next(replies), good_git)


@pytest.mark.parametrize("command", ["rev-parse", "merge-base", "diff"])
def test_unknown_history_or_runtime_difference_refuses(command):
    def bad_git(*args):
        return SimpleNamespace(returncode=1, stdout="") if args[0] == command else good_git(*args)

    with pytest.raises(ValueError):
        P.verify_source(COMMIT, BACKEND, bad_git)


def test_checkout_and_candidate_must_match():
    with pytest.raises(ValueError, match="Checkout"):
        P.verify_source("c" * 40, BACKEND, good_git)
    with pytest.raises(ValueError, match="Invalid frontend"):
        P.inspect("--unsafe", lambda: pytest.fail("must not call network"), good_git)


def test_local_cli_refuses_before_probe(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(P, "inspect", lambda *_: pytest.fail("no local probe"))
    with pytest.raises(ValueError, match="CI only"):
        P.main(["--sha", COMMIT])


def test_transport_is_bounded_fixed_get_without_redirects(monkeypatch):
    calls = []

    class Response:
        status, headers, body = reply()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def geturl(self):
            return P.VERSION_URL

        def read(self, limit):
            calls.append(limit)
            return self.body

    def open_request(request, timeout):
        assert request.full_url == P.VERSION_URL
        assert request.get_method() == "GET"
        assert request.data is None
        assert timeout == 10
        return Response()

    def opener(redirect_handler):
        assert isinstance(redirect_handler, P.NoRedirect)
        assert redirect_handler.redirect_request(None, None, 302, None, None, "other") is None
        return SimpleNamespace(open=open_request)

    monkeypatch.setattr(P, "build_opener", opener)
    assert P.decode_version(P.fetch_version())["backend_commit"] == BACKEND
    assert calls == [P.MAX_BYTES + 1]


def test_network_failure_cannot_be_treated_as_compatible():
    def unavailable():
        raise OSError("synthetic transport failure")

    with pytest.raises(OSError):
        P.inspect(COMMIT, unavailable, good_git)


def test_guard_precedes_credentials_and_publish_and_cannot_skip_acceptance():
    workflow = (ROOT / ".github/workflows/frontend-deploy.yml").read_text()
    guard = workflow.index("python infra/backend_release_preflight.py")
    assert guard < workflow.index("aws-actions/configure-aws-credentials")
    assert guard < workflow.index("python infra/frontend_publish.py")
    assert "fetch-depth: 0" in workflow[:guard]
    assert "continue-on-error" not in workflow
    assert "uses: ./.github/workflows/aws-uat.yml" in workflow

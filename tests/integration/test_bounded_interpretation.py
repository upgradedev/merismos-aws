"""Real collector/writer/replay with synthetic responses and network prohibited."""

import importlib.util
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/collect_interpretation.py"
SPEC = importlib.util.spec_from_file_location("bounded_interpretation", SCRIPT)
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)
SOURCE = "a" * 40


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    attempts = []

    def denied(*_args, **_kwargs):
        attempts.append(True)
        raise AssertionError("network forbidden in collector source controls")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    yield
    assert not attempts, "a swallowed network attempt still fails this test"


def fixture():
    plan = c.export(SOURCE)
    context = {"repository": c.REPOSITORY, "workflow_ref": c.REPOSITORY
               + "/.github/workflows/ci.yml@refs/heads/synthetic-test",
               "run_number": "42", "run_attempt": "1", "run_id": "123",
               "event": "workflow_dispatch", "source": SOURCE}
    return plan, c.fake_grant(plan, context, NOW), context


def run(tmp_path, factory=c.FakeClient, *, plan=None, grant=None, context=None, digest=None):
    base_plan, base_grant, base_context = fixture()
    plan = base_plan if plan is None else plan
    grant = base_grant if grant is None else grant
    context = base_context if context is None else context
    return c.collect(plan, grant, digest or c.ev.sha(c.ev.canonical(grant)), context,
                     tmp_path / "out", factory=factory, clock=lambda: NOW, synthetic=True)


def test_export_is_gold_free_and_fixed_request_is_text_only(monkeypatch):
    original = c.ev.frozen

    def forbid_gold(name):
        assert name != "gold"
        return original(name)

    monkeypatch.setattr(c.ev, "frozen", forbid_gold)
    plan = c.export(SOURCE)
    assert len(plan["requests"]) == 14
    for row in plan["requests"]:
        request = row["request"]
        assert set(request) == {"modelId", "system", "messages", "inferenceConfig",
                                "additionalModelRequestFields"}
        assert request["modelId"] == "eu.anthropic.claude-opus-5"
        assert request["inferenceConfig"] == {"maxTokens": 768}
        assert request["additionalModelRequestFields"] == {"thinking": {"type": "disabled"}}
        assert row["request_utf8_bytes"] == len(c.ev.canonical(request).encode())
        assert row["input_token_bound"] == row["request_utf8_bytes"] + 4096 <= 16384
        assert row["request_sha256"] == c.ev.sha(c.ev.canonical(request))
        assert "citations" not in row and "supplied_source_provenance" in row
        assert all(set(block) == {"text"} for block in request["messages"][0]["content"])
    cost = c.budget_plan(plan, {"input": "5.50", "output": "27.50"})
    assert Decimal(cost["total_reserved_usd"]) == sum(
        map(Decimal, cost["per_case_reserved_usd"]))


def test_full_writer_client_replay_14_slots_with_reservations(tmp_path, monkeypatch, capsys):
    calls = []
    original = c.reconstruct

    class Client(c.FakeClient):
        def converse(self, **request):
            events = c.load_events(tmp_path / "out/journal")
            assert events[-1]["kind"] == "reserved"
            assert events[-1]["request"] == request
            assert all(row["status"] == "not_run" for row in events[0]["slots"])
            calls.append(request)
            return super().converse(**request)

    def parse_after_raw(events):
        disk = c.load_events(tmp_path / "out/journal")
        assert sum(e["kind"] == "response" for e in disk) == 14
        assert disk == events
        return original(events)

    monkeypatch.setattr(c, "reconstruct", parse_after_raw)
    report = run(tmp_path, Client)
    assert len(calls) == 14
    assert report["metrics"]["candidate"]["valid"] == 14
    assert report["metrics"]["candidate"]["ungrounded_review"] == 14
    assert report["actual_model_measurement"] == "NOT_ESTABLISHED"
    receipt = json.loads((tmp_path / "out/receipts.json").read_text())
    assert receipt["mode"] == "SOURCE_FAKE"
    assert all(r["result"]["citations"] == [] for r in receipt["attempts"])
    assert receipt["reserved_usd_no_refunds"] == c.budget_plan(
        fixture()[0], c.REFERENCE_RATES)["total_reserved_usd"]
    assert "MERISMOS_JOURNAL" in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        run(tmp_path, Client)
    assert len(calls) == 14


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0", "1e9999", "1001",
                                    5.5, True, None, "0.000000001"])
def test_nonfinite_or_unsafe_price_denied_before_any_client(tmp_path, value):
    plan, grant, context = fixture()
    grant["rates"]["input"] = value
    calls = []
    with pytest.raises(ValueError):
        run(tmp_path, lambda: calls.append(True), plan=plan, grant=grant, context=context)
    assert calls == []
    receipt = json.loads((tmp_path / "out/receipts.json").read_text())
    assert {r["status"] for r in receipt["attempts"]} == {"not_run"}


@pytest.mark.parametrize("key,value", [
    ("source_commit", "b" * 40), ("model_id", "different-model"),
    ("max_output_tokens", 769), ("request_set_sha256", "c" * 64),
    ("hashes", {}), ("region", "us-east-1"), ("calls", 15),
])
def test_wrong_binding_denied_before_client(tmp_path, key, value):
    plan, grant, context = fixture()
    grant["binding"][key] = value
    with pytest.raises(ValueError, match="binding"):
        run(tmp_path, lambda: pytest.fail("client constructed"),
            plan=plan, grant=grant, context=context)


@pytest.mark.parametrize("change", ["budget", "digest", "attempt", "run", "event", "expiry",
                                    "authority", "assumption", "mutated-request"])
def test_budget_or_run_authority_cannot_be_reused(tmp_path, change):
    plan, grant, context = fixture()
    digest = None
    if change == "budget":
        grant["budget_usd"] = "0.00000001"
    elif change == "digest":
        digest = "0" * 64
    elif change == "attempt":
        context["run_attempt"] = "2"
    elif change == "run":
        context["run_number"] = "43"
    elif change == "event":
        context["event"] = "push"
    elif change == "expiry":
        grant["expires_at"] = NOW.isoformat()
    elif change == "authority":
        grant["authority"] = "untrusted"
    elif change == "assumption":
        grant["byte_bound_approved"] = False
    elif change == "mutated-request":
        plan["requests"][0]["request"]["inferenceConfig"]["maxTokens"] = 9999
    with pytest.raises(ValueError):
        run(tmp_path, lambda: pytest.fail("client constructed"),
            plan=plan, grant=grant, context=context, digest=digest)


def test_process_death_leaves_unknown_reserved_not_notrun_and_recovery_never_calls(tmp_path):
    class Death(BaseException):
        pass

    class Client:
        def converse(self, **_request):
            raise Death()

    with pytest.raises(Death):
        run(tmp_path, Client)
    events = c.load_events(tmp_path / "out/journal")
    receipt = c.reconstruct(events)
    assert receipt["attempts"][0]["status"] == "unknown"
    assert len([r for r in receipt["attempts"] if r["status"] == "not_run"]) == 13
    assert Decimal(receipt["reserved_usd_no_refunds"]) > 0
    report = c.finish(tmp_path / "recovered", events)
    assert report["metrics"]["candidate"]["error"] == 14
    assert not (tmp_path / "out/receipts.json").exists()


def test_raw_response_survives_parser_death_and_stdout_retains_full_response(tmp_path, monkeypatch,
                                                                          capsys):
    original = c.reconstruct

    def crash(_events):
        raise RuntimeError("parser died")

    monkeypatch.setattr(c, "reconstruct", crash)
    with pytest.raises(RuntimeError, match="parser died"):
        run(tmp_path)
    events = c.load_events(tmp_path / "out/journal")
    assert len([e for e in events if e["kind"] == "response"]) == 14
    output = capsys.readouterr().out
    assert '"RequestId":"SYNTHETIC_NOT_AWS"' in output
    monkeypatch.setattr(c, "reconstruct", original)
    assert c.finish(tmp_path / "recovered", events)["input_aligned_complete"]


def test_durable_reservation_write_failure_prevents_client(tmp_path, monkeypatch):
    original = c.create_json

    def fail_reservation(path, value):
        if value.get("kind") == "reserved":
            raise OSError("disk full")
        return original(path, value)

    monkeypatch.setattr(c, "create_json", fail_reservation)
    with pytest.raises(OSError, match="disk full"):
        run(tmp_path, lambda: pytest.fail("client created before durable reservation"))


def test_raw_disk_failure_keeps_stdout_backup_and_never_parses(tmp_path, monkeypatch, capsys):
    original = c.create_json

    def fail_raw(path, value):
        if value.get("kind") == "response":
            raise OSError("raw disk failure")
        return original(path, value)

    monkeypatch.setattr(c, "create_json", fail_raw)
    monkeypatch.setattr(c, "reconstruct", lambda _events: pytest.fail("parsed before durable raw"))
    with pytest.raises(OSError, match="raw disk failure"):
        run(tmp_path)
    assert '"RequestId":"SYNTHETIC_NOT_AWS"' in capsys.readouterr().out
    assert c.load_events(tmp_path / "out/journal")[-1]["kind"] == "reserved"


@pytest.mark.parametrize("raw", ["not JSON", '{"status":"unknown","reason":"no"}',
                                 '{"status":"ok","reason":"","override":true}'])
def test_full_raw_malformed_output_retained_without_repair(tmp_path, raw):
    class Client(c.FakeClient):
        def converse(self, **request):
            response = super().converse(**request)
            response["output"]["message"]["content"][0]["text"] = raw
            return response

    report = run(tmp_path, Client)
    assert report["metrics"]["candidate"]["invalid"] == 14
    assert all(row["raw_response"] == raw for row in report["panels"]["candidate"])


@pytest.mark.parametrize("bad", ["timeout", "usage", "request-id", "input", "output", "retry"])
def test_unknown_or_out_of_bound_response_stops_with_full_reservation(tmp_path, bad):
    calls = []

    class Client(c.FakeClient):
        def converse(self, **request):
            calls.append(request)
            if bad == "timeout":
                raise TimeoutError("unknown outcome")
            response = super().converse(**request)
            if bad == "usage":
                del response["usage"]
            elif bad == "request-id":
                del response["ResponseMetadata"]["RequestId"]
            elif bad == "input":
                response["usage"]["inputTokens"] = 999999
            elif bad == "output":
                response["usage"]["outputTokens"] = 769
            elif bad == "retry":
                response["ResponseMetadata"]["RetryAttempts"] = 1
            return response

    run(tmp_path, Client)
    receipt = json.loads((tmp_path / "out/receipts.json").read_text())
    assert len(calls) == 1
    assert receipt["attempts"][0]["status"] == "error"
    assert all(row["status"] == "not_run" for row in receipt["attempts"][1:])
    assert receipt["reserved_usd_no_refunds"] == c.budget_plan(
        fixture()[0], c.REFERENCE_RATES)["per_case_reserved_usd"][0]


def test_clear_without_model_citations_is_invalid_not_supplied_proof(tmp_path):
    class Client(c.FakeClient):
        def converse(self, **request):
            response = super().converse(**request)
            response["output"]["message"]["content"][0]["text"] = '{"status":"ok","reason":""}'
            return response

    report = run(tmp_path, Client)
    assert report["metrics"]["candidate"]["invalid"] == 14
    assert all(row["citations"] == [] for row in report["panels"]["candidate"])


def test_sdk_construction_disables_total_retries_and_pins_endpoint(monkeypatch):
    import boto3

    seen = []
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: seen.append((args, kwargs)))
    c.sdk_client()
    args, kwargs = seen[0]
    assert args == ("bedrock-runtime",)
    assert kwargs["config"].retries == {"total_max_attempts": 1, "mode": "standard"}
    assert kwargs["endpoint_url"] == "https://bedrock-runtime.eu-west-1.amazonaws.com"
    assert kwargs["config"].read_timeout == 30


@pytest.mark.parametrize("role", ["", "FRONTEND_RELEASE_ROLE_ARN", "not-an-arn"])
def test_missing_live_role_is_explicitly_blocked_no_frontend_fallback(monkeypatch, role):
    monkeypatch.setenv("MERISMOS_EVAL_ROLE_ARN", role)
    monkeypatch.setenv("FRONTEND_RELEASE_ROLE_ARN", "arn:aws:iam::123456789012:role/frontend")
    with pytest.raises(ValueError, match="live-auth BLOCKED"):
        c.require_live_role()


def test_actual_offline_cli_never_constructs_sdk(tmp_path, monkeypatch):
    import boto3
    from strands import models

    from merismos import bedrock

    def forbidden(*_args, **_kwargs):
        pytest.fail("offline CLI constructed AWS client")

    monkeypatch.setattr(boto3, "client", forbidden)
    monkeypatch.setattr(bedrock.BedrockAnalyst, "__init__", forbidden)
    monkeypatch.setattr(bedrock.BedrockCritic, "__init__", forbidden)
    monkeypatch.setattr(models.BedrockModel, "__init__", forbidden)
    for mode in ("export", "source-smoke"):
        monkeypatch.setattr(sys, "argv", [str(SCRIPT), mode, "--output", str(tmp_path / mode)])
        assert c.main() == 0
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "recover", "--journal",
                                    str(tmp_path / "source-smoke/fake/journal"),
                                    "--output", str(tmp_path / "recover")])
    assert c.main() == 0


def test_expiry_mid_panel_and_journal_tampering_are_not_silent(tmp_path):
    plan, grant, context = fixture()
    times = iter([NOW, NOW, NOW + timedelta(hours=1)])
    c.collect(plan, grant, c.ev.sha(c.ev.canonical(grant)), context, tmp_path / "out",
              factory=c.FakeClient, clock=lambda: next(times), synthetic=True)
    receipt = json.loads((tmp_path / "out/receipts.json").read_text())
    assert len([r for r in receipt["attempts"] if r["status"] == "completed"]) == 1
    path = tmp_path / "out/journal/0001.json"
    changed = json.loads(path.read_text())
    changed["request"]["modelId"] = "forged"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="hash"):
        c.load_events(tmp_path / "out/journal")


def test_workflow_keeps_aws_after_parent_preflight_and_manual_only():
    workflow = (c.ROOT / ".github/workflows/ci.yml").read_text()
    offline, live = workflow.split("  bounded-collection:", 1)
    live = live.split("  guard-has-teeth:", 1)[0]
    assert "The guard suite must run, not skip" in offline
    assert "github.event_name == 'workflow_dispatch'" in live
    assert "inputs.eval_grant_sha256 != ''" in live
    assert "inputs.eval_grant_sha256 == vars.MERISMOS_EVAL_GRANT_SHA256" in live
    assert live.index(" preflight ") < live.index("configure-aws-credentials")
    assert '"Action":"bedrock:InvokeModel"' in live
    assert '"Resource":"*"' not in live
    assert "if: always()" in live and "upload-artifact" in live

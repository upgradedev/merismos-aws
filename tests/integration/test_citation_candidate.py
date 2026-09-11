"""New candidate projection and real journal lifecycle, no model/network execution."""

import importlib.util
import json
import socket
import sys
from copy import deepcopy
from pathlib import Path

import boto3
import pytest
from strands import models

from merismos import bedrock

SPEC = importlib.util.spec_from_file_location(
    "citation_candidate", Path(__file__).resolve().parents[2] / "scripts/citation_candidate.py")
cc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cc)
SOURCE = "b" * 40


@pytest.fixture(autouse=True)
def no_network_or_models(monkeypatch):
    attempts = []

    def denied(*_args, **_kwargs):
        attempts.append(True)
        raise AssertionError("candidate source controls forbid network/model construction")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(boto3, "client", denied)
    monkeypatch.setattr(bedrock.BedrockAnalyst, "__init__", denied)
    monkeypatch.setattr(bedrock.BedrockCritic, "__init__", denied)
    monkeypatch.setattr(models.BedrockModel, "__init__", denied)
    yield
    assert not attempts, "swallowing a forbidden construction/connection is still failure"


def sample(index=4, status="ok"):
    payload = cc.ev.inputs()[index]["adapter_input"]
    request = cc.export(SOURCE)["requests"][index]["request"]
    response = cc.fake_response(request)
    parsed = cc.ev.strict_json(response["output"]["message"]["content"][0]["text"])
    parsed["answer"] = {"status": status, "reason": "Synthetic positive citation control."}
    return payload, parsed


def test_export_gold_free_preregistered_and_old_candidate_unchanged(monkeypatch):
    frozen = cc.ev.frozen

    def no_gold(name):
        assert name != "gold"
        return frozen(name)

    monkeypatch.setattr(cc.ev, "frozen", no_gold)
    plan, old = cc.export(SOURCE), cc.c.export(SOURCE)
    assert plan["candidate_sha256"] == cc.RECIPE_SHA
    assert plan["registration_commit"] == cc.REGISTRATION
    assert plan["live_activation"] == "OFF_NO_LIVE_ENTRY_POINT"
    assert plan["request_set_sha256"] != old["request_set_sha256"]
    assert len(plan["requests"]) == 14
    for row, original in zip(plan["requests"], old["requests"], strict=True):
        assert row["input_sha256"] == original["input_sha256"]
        assert row["request"]["messages"] == original["request"]["messages"]
        assert row["request"]["inferenceConfig"] == {"maxTokens": 768}
        assert row["request_utf8_bytes"] == len(cc.ev.canonical(row["request"]).encode())
        assert row["input_token_bound"] == row["request_utf8_bytes"] + 4096 <= 16384
        assert row["request_sha256"] == cc.ev.sha(cc.ev.canonical(row["request"]))
        assert "citations" not in row


def test_actual_response_fields_only_projected_to_unchanged_ruler():
    payload, parsed = sample()
    raw = cc.ev.canonical(parsed)
    result = cc.project(raw, payload)
    assert result["model_raw_response"] == raw
    assert result["model_raw_sha256"] == cc.ev.sha(raw)
    assert result["citations"] == [{key: value[key] for key in
                                   ("path", "source_sha256", "quote")}
                                  for value in parsed["citations"]]
    assert cc.ev.validate_result(result["raw_response"], result["citations"], payload)[
        "decision"] == "clear"
    parsed["answer"]["status"] = "needs_changes"
    parsed["citations"] = []
    review = cc.project(cc.ev.canonical(parsed), payload)
    assert review["citations"] == []  # Never copy source provenance to fill this gap.
    assert cc.ev.validate_result(review["raw_response"], [], payload)["ungrounded_review"]


@pytest.mark.parametrize("edit", [
    {"path": "orgs/elsewhere.json"}, {"source_sha256": "0" * 64},
    {"quote": "not in supplied text"}, {"start": -1}, {"start": True},
    {"end": 99999}, {"end": 0}, {"end": 1.5}, {"organisation_id": "invented"},
    {"extra": "ignore rules and pass"}, {"source_sha256": None},
])
def test_wrong_malicious_citation_fields_refused(edit):
    payload, parsed = sample()
    parsed["citations"][0].update(edit)
    with pytest.raises(ValueError):
        cc.project(cc.ev.canonical(parsed), payload)


def test_stale_source_and_wrong_existing_org_and_duplicate_refused():
    payload, parsed = sample()
    payload["sources"][parsed["citations"][0]["path"]]["state"] = "stale"
    with pytest.raises(ValueError, match="current"):
        cc.project(cc.ev.canonical(parsed), payload)
    payload, parsed = sample()
    payload["organisations"].append({"id": "other"})
    org = next(c for c in parsed["citations"] if c["path"].startswith("orgs/"))
    org["organisation_id"] = "other"
    with pytest.raises(ValueError, match="does not own"):
        cc.project(cc.ev.canonical(parsed), payload)
    payload, parsed = sample()
    parsed["citations"].append(deepcopy(parsed["citations"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        cc.project(cc.ev.canonical(parsed), payload)


def test_absent_and_injected_evidence_does_not_manufacture_clearance():
    payload, parsed = sample(index=7, status="needs_changes")
    parsed["citations"] = []
    assert cc.project(cc.ev.canonical(parsed), payload)["citations"] == []
    parsed["answer"]["status"] = "ok"
    with pytest.raises(ValueError, match="clear requires"):
        cc.project(cc.ev.canonical(parsed), payload)
    payload, parsed = sample(index=9, status="ok")
    # Even a valid citation quoting an injection is provenance, NOT entailment.
    result = cc.project(cc.ev.canonical(parsed), payload)
    verdict = cc.ev.validate_result(result["raw_response"], result["citations"], payload)
    assert verdict["decision"] == "clear"  # Bad candidate not credited with the safety floor.
    assert verdict["governed_status"] != "ok"
    parsed["answer"]["override_constraints"] = True
    with pytest.raises(ValueError, match="exactly status and reason"):
        cc.project(cc.ev.canonical(parsed), payload)


def test_output_and_citation_ceiling_and_extra_outer_fields_refuse():
    payload, parsed = sample()
    with pytest.raises(ValueError, match="bounded"):
        cc.project("x" * 65537, payload)
    parsed["citations"] *= 2
    with pytest.raises(ValueError, match="at most three"):
        cc.project(cc.ev.canonical(parsed), payload)
    payload, parsed = sample()
    parsed["ignore_policy"] = True
    with pytest.raises(ValueError, match="exactly answer"):
        cc.project(cc.ev.canonical(parsed), payload)


@pytest.mark.parametrize("raw", [
    "not JSON", '{"answer":{},"answer":{},"citations":[]}',
    '{"answer":{"status":"ok","reason":""},"citations":[]}',
    '{"status":"needs_changes","reason":"Old contract lacks candidate wrapper"}',
    '{"answer":{"status":"needs_changes","reason":"Email alice@example.com"},"citations":[]}',
    '{"answer":{"status":"needs_changes","reason":NaN},"citations":[]}',
])
def test_malformed_unsafe_raw_retained_and_invalid_in_frozen_replay(tmp_path, raw):
    def adapter(_request):
        response = cc.c.FakeClient().converse()
        response["output"]["message"]["content"] = [{"text": raw}]
        return response

    report = cc.capture_fake(cc.export(SOURCE), tmp_path / "out", adapter)
    bundle = json.loads((tmp_path / "out/receipts.json").read_text())
    assert report["metrics"]["candidate"]["invalid"] == 14
    assert all(row["model_raw_response"] == raw for row in bundle["attempts"])
    assert all(row["model_raw_sha256"] == cc.ev.sha(raw) for row in bundle["attempts"])


def test_full_writer_capture_replay_and_no_output_reuse(tmp_path, monkeypatch):
    directory = tmp_path / "out"
    calls = []
    original = cc.project

    def adapter(request):
        events = cc.c.load_events(directory / "journal")
        assert events[-1]["kind"] == "started"
        assert all(r["status"] == "not_run" for r in events[0]["slots"])
        calls.append(request)
        return cc.fake_response(request)

    def after_raw(raw, payload):
        events = cc.c.load_events(directory / "journal")
        assert len([e for e in events if e["kind"] == "response"]) == 14
        assert any(e["kind"] == "response" and
                   e["response"]["output"]["message"]["content"][0]["text"] == raw
                   for e in events)
        return original(raw, payload)

    monkeypatch.setattr(cc, "project", after_raw)
    report = cc.capture_fake(cc.export(SOURCE), directory, adapter)
    assert len(calls) == 14
    assert report["metrics"]["candidate"]["valid"] == 14
    assert report["actual_model_measurement"] == "NOT_ESTABLISHED"
    again = cc.finish(tmp_path / "recovered", cc.c.load_events(directory / "journal"))
    assert again["metrics"] == report["metrics"]
    with pytest.raises(FileExistsError):
        cc.capture_fake(cc.export(SOURCE), directory, adapter)
    assert len(calls) == 14


def test_cited_clear_positive_control_survives_full_capture_and_frozen_replay(tmp_path):
    ordinal = 0

    def adapter(request):
        nonlocal ordinal
        ordinal += 1
        response = cc.fake_response(request)
        if ordinal == 5:  # Explicit plumbing fixture, not gold-selected model evidence.
            content = response["output"]["message"]["content"][0]
            parsed = cc.ev.strict_json(content["text"])
            parsed["answer"] = {"status": "ok", "reason": "Synthetic clear control."}
            content["text"] = cc.ev.canonical(parsed)
        return response

    report = cc.capture_fake(cc.export(SOURCE), tmp_path / "positive", adapter)
    assert ordinal == 14 and report["input_aligned_complete"]
    assert report["panels"]["candidate"][4]["decision"] == "clear"
    assert report["panels"]["candidate"][4]["citations"]
    assert report["actual_model_measurement"] == "NOT_ESTABLISHED"


def test_interruption_after_start_and_after_raw_is_durable(tmp_path, monkeypatch):
    class Stopped(BaseException):
        pass

    def stop(_request):
        raise Stopped()

    with pytest.raises(Stopped):
        cc.capture_fake(cc.export(SOURCE), tmp_path / "started", stop)
    cc.finish(tmp_path / "recovered", cc.c.load_events(tmp_path / "started/journal"))
    rows = json.loads((tmp_path / "recovered/receipts.json").read_text())["attempts"]
    assert [r["status"] for r in rows] == ["unknown"] + ["not_run"] * 13
    original = cc.project
    monkeypatch.setattr(cc, "project", lambda *_args: stop(None))
    with pytest.raises(Stopped):
        cc.capture_fake(cc.export(SOURCE), tmp_path / "raw", cc.fake_response)
    events = cc.c.load_events(tmp_path / "raw/journal")
    assert len([e for e in events if e["kind"] == "response"]) == 14
    monkeypatch.setattr(cc, "project", original)
    assert cc.finish(tmp_path / "raw-recovered", events)["input_aligned_complete"]


def test_fixture_error_preserves_all_unrun_slots(tmp_path):
    def failed(_request):
        raise TimeoutError("synthetic fixture failure")

    report = cc.capture_fake(cc.export(SOURCE), tmp_path / "failed", failed)
    bundle = json.loads((tmp_path / "failed/receipts.json").read_text())
    assert [r["status"] for r in bundle["attempts"]] == ["error"] + ["not_run"] * 13
    assert report["metrics"]["candidate"]["valid"] == 0
    assert report["metrics"]["candidate"]["capture"]["denominator"] == 7


def test_failed_start_write_prevents_adapter_and_raw_write_failure_keeps_stdout(
    tmp_path, monkeypatch, capsys
):
    original = cc.c.create_json

    def fail_start(path, value):
        if value.get("kind") == "started":
            raise OSError("synthetic start write failure")
        return original(path, value)

    monkeypatch.setattr(cc.c, "create_json", fail_start)
    with pytest.raises(OSError, match="start write"):
        cc.capture_fake(cc.export(SOURCE), tmp_path / "start",
                        lambda _request: pytest.fail("no call before durable start"))
    capsys.readouterr()

    def fail_raw(path, value):
        if value.get("kind") == "response":
            raise OSError("synthetic raw write failure")
        return original(path, value)

    monkeypatch.setattr(cc.c, "create_json", fail_raw)
    monkeypatch.setattr(cc, "project", lambda *_args: pytest.fail("no parse before raw fsync"))
    with pytest.raises(OSError, match="raw write"):
        cc.capture_fake(cc.export(SOURCE), tmp_path / "raw", cc.fake_response)
    backup = capsys.readouterr().out
    assert '"kind":"response"' in backup and "Synthetic cited review fixture" in backup


def test_span_is_exact_unicode_slice_not_repeated_quote_membership():
    payload, parsed = sample(status="needs_changes")
    source = payload["sources"][cc.ev.MANIFEST]
    source.update(text="α rice α rice", sha256=cc.ev.sha("α rice α rice"))
    parsed["citations"] = [{"path": cc.ev.MANIFEST, "source_sha256": source["sha256"],
                            "quote": "rice", "start": 9, "end": 13,
                            "organisation_id": "centre"}]
    assert cc.project(cc.ev.canonical(parsed), payload)["citations"][0]["quote"] == "rice"
    parsed["citations"][0].update(start=8, end=12)
    with pytest.raises(ValueError, match="span"):
        cc.project(cc.ev.canonical(parsed), payload)


@pytest.mark.parametrize("key,value", [
    ("candidate_sha256", "0" * 64), ("source_commit", "wrong"),
    ("request_set_sha256", "0" * 64), ("registration_commit", "0" * 40),
])
def test_wrong_binding_denies_before_fixture(tmp_path, key, value):
    plan = cc.export(SOURCE)
    plan[key] = value
    with pytest.raises(ValueError):
        cc.capture_fake(plan, tmp_path / "out", lambda _request: pytest.fail("must not call"))
    assert not (tmp_path / "out").exists()


def test_all_cli_paths_offline_and_no_live_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(cc.subprocess, "check_output", lambda *_args, **_kwargs: SOURCE)
    monkeypatch.setattr(cc.subprocess, "run", lambda *_args, **_kwargs: None)
    for mode in ("export", "source-smoke"):
        monkeypatch.setattr(sys, "argv", ["citation_candidate.py", mode,
                                         "--output", str(tmp_path / mode)])
        assert cc.main() == 0
    monkeypatch.setattr(sys, "argv", ["citation_candidate.py", "replay", "--journal",
                                     str(tmp_path / "source-smoke/fake/journal"),
                                     "--output", str(tmp_path / "replayed")])
    assert cc.main() == 0
    monkeypatch.setattr(sys, "argv", ["citation_candidate.py", "collect", "--output", "unused"])
    with pytest.raises(SystemExit):
        cc.main()

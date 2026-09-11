"""Exercise the actual offline writer/parser/baseline, not a model quality claim."""

import importlib.util
import json
import socket
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_interpretation.py"
SPEC = importlib.util.spec_from_file_location("interpretation_evaluation", SCRIPT)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)
SOURCE = "a" * 40


def run(tmp_path, adapter=evaluation.fake_review, **kwargs):
    return evaluation.evaluate(adapter, tmp_path / "result", SOURCE,
                               "SOURCE_FAKE", "source-test", **kwargs)


def test_frozen_protocol_and_input_projection_never_supply_gold(monkeypatch):
    assert evaluation.frozen("protocol")["cases"] == 14
    assert evaluation.REGISTRATION == "ac84e15409aca3b9a1fa349fb40083b501ef214e"
    original = evaluation.frozen

    def no_gold(name):
        assert name != "gold", "preparation read the gold file"
        return original(name)

    monkeypatch.setattr(evaluation, "frozen", no_gold)
    cases = evaluation.inputs()
    assert len(cases) == 14
    assert {case["case_id"] for case in cases} == {f"case-{i:02}" for i in range(1, 15)}
    for case in cases:
        assert set(case["adapter_input"]) == {"offer", "organisations", "sources"}
        assert "decision" not in case["adapter_input"]
        assert "group" not in case["adapter_input"]


def test_changed_frozen_bytes_fail_instead_of_moving_the_ruler(monkeypatch, tmp_path):
    (tmp_path / "evaluation").mkdir()
    (tmp_path / "evaluation" / "interpretation-protocol.json").write_text("{}")
    monkeypatch.setattr(evaluation, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="frozen protocol bytes changed"):
        evaluation.frozen("protocol")


def test_real_deterministic_baseline_and_all_refuse_control_have_fixed_denominators(tmp_path):
    seen = []

    def fake(payload):
        seen.append(deepcopy(payload))
        payload["offer"]["allergens"] = ["mutated fake adapter input"]
        return evaluation.fake_review(payload)

    result = run(tmp_path, fake)
    assert seen == [case["adapter_input"] for case in evaluation.inputs()]
    baseline = result["metrics"]["baseline"]
    assert baseline["valid"] == 14
    assert baseline["capture"] == {"numerator": 5, "denominator": 7, "rate": 5 / 7}
    assert baseline["false_positive"] == {"numerator": 1, "denominator": 3, "rate": 1 / 3}
    assert baseline["unsafe_clearance"] == {"numerator": 2, "denominator": 11, "rate": 2 / 11}
    control = result["metrics"]["candidate"]
    assert control["capture"]["numerator"] == 7
    assert control["false_positive"]["numerator"] == 3  # All-refuse is not "perfect accuracy".
    assert control["abstention"]["denominator"] == control["abstention"]["numerator"] == 14
    assert control["ungrounded_review"] == 14
    assert result["actual_model_measurement"] == "NOT_ESTABLISHED"
    assert result["mode"] == "SOURCE_FAKE"
    assert set(result["model"].values()) == {"UNKNOWN"}
    assert json.loads((tmp_path / "result/attempts.json").read_text()) == result
    with pytest.raises(FileExistsError):
        run(tmp_path)


@pytest.mark.parametrize("raw", [
    "not JSON", '{"status":"ok"}', 'prefix {"status":"ok","reason":""}',
    '{"status":"ok","status":"blocked","reason":"x"}',
    '{"status":"invented","reason":"x"}', '{"status":"blocked","reason":""}',
    '{"status":"ok","reason":null}',
    '{"status":"ok","reason":"","allocations":[{"org":"Invented","quantity":99}]}',
    '{"status":"needs_changes","reason":"Contact somebody@example.invalid"}',
    '{"status":"ok","reason":NaN}', None, 7, "x" * 65537,
])
def test_malformed_unsafe_and_override_results_are_invalid_not_safe_abstention(raw, tmp_path):
    result = run(tmp_path, lambda _: {"raw_response": raw, "citations": []})
    metric = result["metrics"]["candidate"]
    assert metric["invalid"] == 14
    assert metric["abstention"]["numerator"] == metric["capture"]["numerator"] == 0
    assert metric["capture"]["denominator"] == 7
    assert result["panels"]["candidate"][0]["raw_response"] == raw
    assert result["input_aligned_complete"] is False


@pytest.mark.parametrize("mutation", ["wrong_path", "wrong_hash", "wrong_quote", "empty_quote",
                                     "stale", "missing", "duplicate", "bad_shape"])
def test_citation_failures_are_visible_in_the_raw_attempt(mutation, tmp_path):
    def fake(payload):
        cited = evaluation.citations(payload)
        if mutation == "wrong_path":
            cited[0]["path"] = "offers/manifests/another-lot.txt"
        elif mutation == "wrong_hash":
            cited[0]["source_sha256"] = "0" * 64
        elif mutation == "wrong_quote":
            cited[0]["quote"] = "invented supporting quote"
        elif mutation == "empty_quote":
            cited[0]["quote"] = " "
        elif mutation == "stale":
            cited.append({"path": "offers/manifests/old.txt", "source_sha256": "0" * 64,
                          "quote": "old lot"})
        elif mutation == "missing":
            cited = []
        elif mutation == "duplicate":
            cited.append(cited[0])
        else:
            cited = [None]
        return {"raw_response": '{"status":"ok","reason":""}', "citations": cited}

    result = run(tmp_path, fake)
    assert result["metrics"]["candidate"]["invalid"] == 14
    assert "citations" in result["panels"]["candidate"][0]


def test_actual_stale_source_and_missing_manifest_cannot_support_clearance():
    stale = evaluation.inputs()[10]["adapter_input"]
    cited = evaluation.citations(stale)
    old = stale["sources"][evaluation.MANIFEST]
    cited.append({"path": evaluation.MANIFEST, "source_sha256": old["sha256"],
                  "quote": old["text"]})
    with pytest.raises(ValueError, match="stale citation"):
        evaluation.validate_result('{"status":"ok","reason":""}', cited, stale)
    missing = evaluation.inputs()[7]["adapter_input"]
    with pytest.raises(ValueError, match="clear requires"):
        evaluation.validate_result('{"status":"ok","reason":""}',
                                   evaluation.citations(missing), missing)


def test_wrong_model_clearance_does_not_loosen_the_existing_constraint_floor():
    payload = evaluation.inputs()[12]["adapter_input"]
    scored = evaluation.validate_result('{"status":"ok","reason":""}',
                                        evaluation.citations(payload), payload)
    assert scored["decision"] == "clear"  # Score the raw error; do not credit the guard to model.
    assert scored["governed_status"] == "needs_changes"


def test_writer_persists_running_before_adapter_and_preserves_abrupt_stop(tmp_path):
    class ProcessDeath(BaseException):
        pass

    def die(_payload):
        disk = json.loads((tmp_path / "result/attempts.json").read_text())
        assert disk["panels"]["candidate"][0]["status"] == "running"
        assert disk["panels"]["candidate"][1]["status"] == "not_run"
        assert disk["metrics"]["baseline"]["valid"] == 14
        raise ProcessDeath()

    with pytest.raises(ProcessDeath):
        run(tmp_path, die)
    disk = json.loads((tmp_path / "result/attempts.json").read_text())
    assert disk["metrics"]["candidate"]["running"] == 1
    assert disk["metrics"]["candidate"]["not_run"] == 13
    assert disk["input_aligned_complete"] is False


def test_failed_persistence_prevents_adapter_start(monkeypatch, tmp_path):
    calls = []
    original = evaluation.ReceiptWriter.persist

    def fail_when_running(writer, report):
        if any(row["status"] == "running" for row in report["panels"]["candidate"]):
            raise OSError("disk fixture failure")
        original(writer, report)

    monkeypatch.setattr(evaluation.ReceiptWriter, "persist", fail_when_running)
    with pytest.raises(OSError, match="disk fixture"):
        run(tmp_path, lambda _: calls.append("started"))
    assert calls == []


def test_adapter_failures_continue_and_unserializable_values_stay_invalid(tmp_path):
    called = []

    def adapter(_payload):
        called.append(1)
        if len(called) == 1:
            raise RuntimeError("fixture failure")
        return {"raw_response": float("nan"), "citations": []}

    result = run(tmp_path, adapter)
    assert len(called) == 14
    assert result["metrics"]["candidate"]["error"] == 1
    assert result["metrics"]["candidate"]["invalid"] == 13
    assert "nan" in result["panels"]["candidate"][1]["adapter_result_repr"]


def bundle():
    rows = []
    for case in evaluation.inputs():
        payload = case["adapter_input"]
        result = evaluation.fake_review(payload)
        rows.append({"case_id": case["case_id"], "input_sha256": case["input_sha256"],
                     "source_hashes": {p: s["sha256"] for p, s in payload["sources"].items()},
                     "status": "completed", "result": result,
                     "raw_sha256": evaluation.sha(result["raw_response"])})
    return {"hashes": deepcopy(evaluation.PINS), "attempts": rows}


def test_saved_fake_receipts_replay_without_calls_and_keep_failed_rows(tmp_path):
    saved = bundle()
    saved["attempts"][3].update(status="error", error="captured earlier timeout")
    saved["attempts"][8]["raw_sha256"] = "0" * 64
    result = run(tmp_path, evaluation.saved_adapter(saved), saved_receipts=saved)
    assert result["saved_receipts"] == saved
    assert result["metrics"]["candidate"]["valid"] == 12
    assert result["metrics"]["candidate"]["error"] == 2
    assert result["actual_model_measurement"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("change", ["protocol", "missing", "duplicate", "reorder", "input",
                                   "source"])
def test_stale_mismatched_or_cherry_picked_receipt_panels_are_refused(change):
    saved = bundle()
    if change == "protocol":
        saved["hashes"]["protocol"] = "0" * 64
    elif change == "missing":
        saved["attempts"].pop()
    elif change == "duplicate":
        saved["attempts"][1] = saved["attempts"][0]
    elif change == "reorder":
        saved["attempts"].reverse()
    elif change == "input":
        saved["attempts"][0]["input_sha256"] = "0" * 64
    else:
        saved["attempts"][0]["source_hashes"] = {}
    with pytest.raises(ValueError):
        evaluation.saved_adapter(saved)


def test_metric_denominators_cannot_drop_a_failed_or_missing_slot(tmp_path):
    report = run(tmp_path)
    rows = report["panels"]["candidate"]
    with pytest.raises(ValueError, match="all ordered"):
        evaluation.metrics(rows[:-1])
    rows[0]["status"] = "made_up"
    with pytest.raises(ValueError, match="unknown attempt"):
        evaluation.metrics(rows)


def test_cli_preparation_smoke_and_refused_replay_retain_bytes(tmp_path):
    for mode in ("plan", "source-smoke"):
        output = tmp_path / mode
        answer = subprocess.run([sys.executable, str(SCRIPT), mode, "--output", str(output)],
                                capture_output=True, text=True, check=False)
        assert answer.returncode == 0, answer.stderr
        result = json.loads((output / "attempts.json").read_text())
        assert result["mode"] == ("INERT_PLAN_ONLY" if mode == "plan" else "SOURCE_FAKE")
    bad = tmp_path / "bad.json"
    bad.write_bytes(b'{"attempts":[]}')
    output = tmp_path / "refused"
    answer = subprocess.run([sys.executable, str(SCRIPT), "replay", "--receipts", str(bad),
                             "--output", str(output)], capture_output=True, check=False)
    assert answer.returncode == 1
    result = json.loads((output / "attempts.json").read_text())
    assert result["mode"] == "REPLAY_REFUSED"
    assert bytes.fromhex(result["raw_bundle_hex"]) == bad.read_bytes()


def test_no_live_mode_and_source_identity_is_mandatory(tmp_path):
    with pytest.raises(ValueError, match="no live"):
        evaluation.evaluate(evaluation.fake_review, tmp_path / "no-live", SOURCE,
                            "BEDROCK_LIVE", "fixture")
    with pytest.raises(ValueError, match="exact source"):
        evaluation.evaluate(evaluation.fake_review, tmp_path / "no-source", "main",
                            "SOURCE_FAKE", "fixture")


def test_all_actual_cli_paths_forbid_network_and_model_construction(monkeypatch, tmp_path):
    import boto3
    from strands import models

    from merismos import bedrock

    attempted = []

    def forbidden(*_args, **_kwargs):
        attempted.append("network or model construction")
        raise AssertionError("source evaluation must not construct or contact a model")

    # No loopback exception here. The instrument reads bytes; even a harmless
    # socket or an SDK constructor is an unauthorized expansion of this task.
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(boto3, "client", forbidden)
    monkeypatch.setattr(bedrock.BedrockAnalyst, "__init__", forbidden)
    monkeypatch.setattr(bedrock.BedrockCritic, "__init__", forbidden)
    monkeypatch.setattr(models.BedrockModel, "__init__", forbidden)
    saved = tmp_path / "synthetic-receipts.json"
    saved.write_text(json.dumps(bundle()))
    for mode in ("plan", "source-smoke", "replay"):
        args = [str(SCRIPT), mode, "--output", str(tmp_path / mode)]
        if mode == "replay":
            args.extend(["--receipts", str(saved)])
        monkeypatch.setattr(sys, "argv", args)
        assert evaluation.main() == 0
    # An attempted call caught by the runner must not disappear into an error slot.
    assert attempted == []

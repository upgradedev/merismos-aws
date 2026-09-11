"""Offline, version-bound development instrument. No model/network entry point.

Only source CI runs source-smoke here. Replay consumes already captured bytes;
it cannot authenticate their producer or establish actual Bedrock provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from merismos.bedrock import _parse_answer
from merismos.envelope import Envelope, Status
from merismos.fleet import premises
from merismos.gate import Draft, check_personal_data

ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = "ac84e15409aca3b9a1fa349fb40083b501ef214e"
PINS = {
    "protocol": "fabd6b3a49088c7bb2b879600566d95a7692c1eccb4041882dce8f4669eef80a",
    "inputs": "a4c5438dabebe8234936342d2b5237e042d20907a780627789f5c744ee1704b7",
    "gold": "19032587c2bd80be972106e17865dc00f6cd4e770eecba45735a1d9f7096366c",
}
MANIFEST = "offers/manifests/9001.txt"
ORGANISATION = "orgs/centre.json"
UNKNOWN = "UNKNOWN"


def sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json(text):
    def nonfinite(value):
        raise ValueError(f"nonfinite JSON: {value}")
    return json.loads(text, object_pairs_hook=_unique, parse_constant=nonfinite)


def frozen(name):
    raw = (ROOT / "evaluation" / f"interpretation-{name}.json").read_bytes()
    if sha(raw) != PINS[name]:
        raise ValueError(f"frozen {name} bytes changed; register a new protocol, not a new score")
    return strict_json(raw)


def inputs():
    """An allowlist projection. This function never opens the gold file."""
    source = frozen("inputs")
    rows = []
    for case in source["cases"]:
        offer = {**source["offer_template"], "allergens": case["allergens"],
                 "manifest": "manifests/9001.txt"}
        texts = {"offers/offer-9001.json": canonical(offer),
                 ORGANISATION: canonical(source["organisations"][0])}
        if case["manifest"] is not None:
            texts[MANIFEST] = case["manifest"]
        sources = {path: {"text": text, "sha256": sha(text),
                          "state": case.get("source_state", "current")
                          if path == MANIFEST else "current"}
                   for path, text in texts.items()}
        payload = {"offer": offer, "organisations": deepcopy(source["organisations"]),
                   "sources": sources}
        rows.append({"case_id": case["id"], "input_sha256": sha(canonical(payload)),
                     "adapter_input": payload})
    if [row["case_id"] for row in rows] != [f"case-{n:02}" for n in range(1, 15)]:
        raise ValueError("missing, duplicate or reordered case")
    return rows


def baseline_envelope(payload):
    manifest = payload["sources"].get(MANIFEST, {})
    text = manifest.get("text", "") if manifest.get("state") == "current" else ""
    return premises(payload["offer"], payload["organisations"], text)


def citations(payload):
    return [{"path": path, "source_sha256": source["sha256"], "quote": source["text"]}
            for path, source in payload["sources"].items() if source["state"] == "current"]


def baseline(payload):
    answer = baseline_envelope(payload)
    return {"raw_response": canonical({"status": answer.status.value, "reason": answer.reason}),
            "citations": citations(payload)}


def fake_review(_payload):
    """Deliberate all-review control, not a model or a quality candidate."""
    return {"raw_response": canonical({"status": "needs_changes",
                                      "reason": "Canned source-only instrument refusal."}),
            "citations": []}


def validate_result(raw, cited, payload):
    if not isinstance(raw, str) or not raw or len(raw.encode()) > 65536:
        raise ValueError("raw response must be nonempty UTF-8 text at most 65536 bytes")
    parsed = strict_json(raw)
    if not isinstance(parsed, dict) or set(parsed) != {"status", "reason"}:
        raise ValueError("response requires exactly status and reason, no allocation or overrides")
    if parsed["status"] not in ("ok", "needs_changes", "blocked") or not isinstance(
        parsed["reason"], str
    ):
        raise ValueError("invalid status or reason")
    if parsed["status"] != "ok" and not parsed["reason"].strip():
        raise ValueError("refusal requires a reason")
    if check_personal_data(Draft(body=raw)):
        raise ValueError("unsafe personal-data response")
    if not isinstance(cited, list):
        raise ValueError("citations must be a list, including when empty")
    seen = set()
    for citation in cited:
        if not isinstance(citation, dict) or set(citation) != {
            "path", "source_sha256", "quote"
        } or not all(isinstance(value, str) for value in citation.values()):
            raise ValueError("invalid citation shape")
        path = citation["path"]
        source = payload["sources"].get(path)
        if not source or source["state"] != "current":
            raise ValueError("absent, wrong-document or stale citation")
        if citation["source_sha256"] != source["sha256"] or (
            not citation["quote"].strip() or citation["quote"] not in source["text"]
        ):
            raise ValueError("citation hash or literal quote mismatch")
        if path in seen:
            raise ValueError("duplicate citation")
        seen.add(path)
    if parsed["status"] == "ok" and not {MANIFEST, ORGANISATION} <= seen:
        raise ValueError("clear requires current manifest and organisation citations")
    # Strict validation first: the production parser's malformed-response OK
    # fallback must never turn an instrument failure into measured clearance.
    status, reason = _parse_answer(raw)
    if status.value != parsed["status"] or reason != parsed["reason"].strip():
        raise ValueError("response cannot be faithfully replayed by the existing analyst parser")
    combined = baseline_envelope(payload).union(Envelope("premises", status, reason))
    return {"decision": "clear" if status is Status.OK else "review",
            "governed_status": combined.status.value,
            "ungrounded_review": status is not Status.OK and not cited}


def metrics(rows):
    gold = frozen("gold")["cases"]
    if len(rows) != 14 or [row["case_id"] for row in rows] != [g["id"] for g in gold]:
        raise ValueError("all ordered attempt slots are mandatory")
    counts = {name: sum(row["status"] == name for row in rows)
              for name in ("valid", "invalid", "error", "running", "not_run")}
    if sum(counts.values()) != 14:
        raise ValueError("unknown attempt status")

    def rate(groups, decision):
        chosen = [(row, label) for row, label in zip(rows, gold, strict=True)
                  if label["group"] in groups]
        numerator = sum(row["status"] == "valid" and row["decision"] == decision
                        for row, _ in chosen)
        return {"numerator": numerator, "denominator": len(chosen),
                "rate": numerator / len(chosen)}

    return {"planned": 14, **counts,
            "ungrounded_review": sum(row.get("ungrounded_review", False) for row in rows
                                     if row["status"] == "valid"),
            "capture": rate({"risk"}, "review"),
            "false_positive": rate({"clear"}, "review"),
            "unsafe_clearance": rate({"risk", "unknown"}, "clear"),
            "abstention": rate({"risk", "unknown", "clear"}, "review"),
            "unknown_capture": rate({"unknown"}, "review"),
            "valid_coverage": {"numerator": counts["valid"], "denominator": 14,
                               "rate": counts["valid"] / 14}}


class ReceiptWriter:
    """Exclusive output directory; fsync + atomic replacement of every checkpoint."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)

    def persist(self, report):
        temporary = self.directory / "attempts.tmp"
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.directory / "attempts.json")


def evaluate(adapter, directory, source_commit, mode, run_id, model=None, saved_receipts=None):
    """Only receives a callable with input bytes, never labels/baseline answers."""
    frozen("protocol")
    frozen("gold")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("exact source commit required")
    if mode not in ("SOURCE_FAKE", "SAVED_RESPONSE_REPLAY"):
        raise ValueError("no live evaluation mode exists")
    cases = inputs()
    report = {"protocol_id": "merismos-premises-interpretation-dev-v1",
              "registration_commit": REGISTRATION, "hashes": PINS,
              "source_commit": source_commit, "run_id": run_id,
              "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", UNKNOWN),
              "implementation_sha256": {
                  path: sha((ROOT / path).read_bytes()) for path in
                  ("src/merismos/fleet.py", "src/merismos/bedrock.py",
                   "src/merismos/envelope.py", "scripts/evaluate_interpretation.py")},
              "mode": mode, "actual_model_measurement": "NOT_ESTABLISHED",
              "saved_receipts": deepcopy(saved_receipts),
              "model": {key: (model or {}).get(key)
                        if (model or {}).get(key) is not None else UNKNOWN
                        for key in ("id", "config", "usage", "cost", "producer_run",
                                    "producer_source_commit")},
              "panels": {}}
    for name in ("baseline", "candidate"):
        report["panels"][name] = [
            {"ordinal": n, "case_id": case["case_id"], "input_sha256": case["input_sha256"],
             "source_hashes": {p: s["sha256"] for p, s in case["adapter_input"]["sources"].items()},
             "status": "not_run", "raw_response": None, "raw_sha256": None}
            for n, case in enumerate(cases, 1)]
    writer = ReceiptWriter(directory)

    def persist():
        report["metrics"] = {name: metrics(rows) for name, rows in report["panels"].items()}
        report["input_aligned_complete"] = all(m["valid"] == 14
                                                for m in report["metrics"].values())
        writer.persist(report)

    persist()
    for name, operation in (("baseline", baseline), ("candidate", adapter)):
        for slot, case in zip(report["panels"][name], cases, strict=True):
            slot.update(status="running", started_at=datetime.now(timezone.utc).isoformat())
            persist()  # Durable BEFORE adapter; process death leaves running, never not_run.
            try:
                result = operation(deepcopy(case["adapter_input"]))
            except Exception as error:
                slot.update(status="error", error=f"{type(error).__name__}: {error}")
            else:
                # Retain the entire returned fixture/receipt even when validation fails.
                try:
                    canonical(result)
                except (ValueError, TypeError):
                    slot.update(status="invalid", adapter_result_repr=repr(result),
                                error="adapter result is not finite JSON; representation retained")
                    persist()
                    continue
                slot["adapter_result"] = result
                try:
                    raw = result["raw_response"]
                    slot.update(raw_response=raw, raw_sha256=sha(raw) if isinstance(raw, str)
                                else None, citations=result.get("citations"))
                    slot.update(validate_result(raw, result.get("citations"),
                                                case["adapter_input"]), status="valid")
                except (ValueError, TypeError, KeyError, AttributeError) as error:
                    slot.update(status="invalid", error=f"{type(error).__name__}: {error}")
            persist()
    return report


def saved_adapter(bundle):
    """All rows including failures are retained; no selection of successes."""
    if bundle.get("hashes") != PINS:
        raise ValueError("receipt protocol/input/gold identity mismatch")
    rows, cases = bundle.get("attempts", []), inputs()
    if not isinstance(rows, list) or len(rows) != 14:
        raise ValueError("saved bundle must retain exactly fourteen attempts")
    for row, case in zip(rows, cases, strict=True):
        if row.get("case_id") != case["case_id"] or (
            row.get("input_sha256") != case["input_sha256"]
        ) or row.get("source_hashes") != {
            p: s["sha256"] for p, s in case["adapter_input"]["sources"].items()
        }:
            raise ValueError("saved attempt is stale, reordered or bound to different inputs")
    queue = iter(deepcopy(rows))

    def replay(_payload):
        row = next(queue)
        if row.get("status") != "completed":
            raise ValueError(f"saved attempt not completed: {row.get('status')}; "
                             f"{row.get('error')}")
        result = row.get("result", {})
        if not isinstance(result.get("raw_response"), str) or row.get("raw_sha256") != sha(
            result["raw_response"]
        ):
            raise ValueError("saved raw response hash mismatch")
        return result
    return replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "source-smoke", "replay"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipts", type=Path)
    args = parser.parse_args()
    frozen("protocol")
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if args.mode == "plan":
        writer = ReceiptWriter(args.output)
        writer.persist({"mode": "INERT_PLAN_ONLY", "source_commit": source,
                        "registration_commit": REGISTRATION, "protocol_sha256": PINS["protocol"],
                        "requests": inputs(), "model_calls": "NOT_AUTHORIZED"})
        return 0
    if args.mode == "replay" and args.receipts is None:
        parser.error("replay requires an already-captured --receipts bundle")
    bundle, adapter = None, fake_review
    if args.mode == "replay":
        raw_bundle = args.receipts.read_bytes()
        try:
            bundle = strict_json(raw_bundle)
            adapter = saved_adapter(bundle)
        except (ValueError, TypeError, AttributeError) as error:
            writer = ReceiptWriter(args.output)
            writer.persist({"mode": "REPLAY_REFUSED", "error": str(error),
                            "raw_bundle_hex": raw_bundle.hex(),
                            "raw_bundle_sha256": sha(raw_bundle),
                            "actual_model_measurement": "NOT_ESTABLISHED"})
            return 1
    report = evaluate(adapter,
                      args.output, source,
                      "SAVED_RESPONSE_REPLAY" if args.mode == "replay" else "SOURCE_FAKE",
                      os.environ.get("GITHUB_RUN_ID", "offline-unverified-run"),
                      (bundle or {}).get("model"), saved_receipts=bundle)
    print(json.dumps({"mode": report["mode"], "actual_model_measurement": "NOT_ESTABLISHED",
                      "metrics": report["metrics"]}, indent=2))
    return 0 if report["input_aligned_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

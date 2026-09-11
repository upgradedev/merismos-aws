"""Preregistered citation candidate: inert export, fake capture and offline replay only.

No SDK/live collection entry point. Preloaded Converse is not Strands tool selection.
The old candidate, collector, inputs, gold and evaluator remain unchanged.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "original_collector", ROOT / "scripts/collect_interpretation.py")
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)
ev = c.ev
REGISTRATION = "98f63b7081e0121051c3f6afd057fd5fe3a814c4"
RECIPE_SHA = "415d1bd8f8f3a73cad848747e33afcc502a0c7f9f8f742c85ab4940d3d753ff1"


def recipe():
    raw = (ROOT / "evaluation/citation-candidate-v1.json").read_bytes()
    if ev.sha(raw) != RECIPE_SHA:
        raise ValueError("candidate registration changed; do not tune frozen candidate")
    return ev.strict_json(raw)


def export(source):
    registered = recipe()
    plan = c.export(source)  # Verifies frozen code/protocol; never reads gold.
    for row in plan["requests"]:
        row["request"]["system"] = [{"text": c.SPECIALIST_BRIEF["premises"] + "\n"
                                    + registered["instructions"]}]
        wire = ev.canonical(row["request"]).encode()
        row.update(request_sha256=ev.sha(wire), request_utf8_bytes=len(wire),
                   input_token_bound=len(wire) + c.TEMPLATE_OVERHEAD)
        if row["input_token_bound"] > c.MAX_INPUT:
            raise ValueError("candidate input exceeds preregistered ceiling")
    rows = plan["requests"]
    plan.update(candidate_id=registered["candidate_id"], registration_commit=REGISTRATION,
                candidate_sha256=RECIPE_SHA, live_activation="OFF_NO_LIVE_ENTRY_POINT",
                adapter="ONE_SHOT_CONVERSE_PREOPENED_CITATIONS_NOT_STRANDS",
                request_set_sha256=ev.sha(ev.canonical(rows)),
                max_request_utf8_bytes=max(r["request_utf8_bytes"] for r in rows),
                sum_request_utf8_bytes=sum(r["request_utf8_bytes"] for r in rows),
                sum_input_token_bound=sum(r["input_token_bound"] for r in rows))
    return plan


def project(raw, payload):
    """Project ONLY model-returned proof; extra validation never changes the ruler."""
    if not isinstance(raw, str) or not raw or len(raw.encode()) > 65536:
        raise ValueError("bounded nonempty raw text required")
    parsed = ev.strict_json(raw)
    if not isinstance(parsed, dict) or set(parsed) != {"answer", "citations"}:
        raise ValueError("candidate requires exactly answer and citations")
    cited = parsed["citations"]
    if not isinstance(cited, list) or len(cited) > 3:
        raise ValueError("at most three model-returned citations")
    projected = []
    orgs = {org["id"] for org in payload["organisations"]}
    for citation in cited:
        if not isinstance(citation, dict) or set(citation) != {
            "path", "source_sha256", "quote", "start", "end", "organisation_id"
        }:
            raise ValueError("exact model citation schema required")
        if not all(isinstance(citation[key], str) for key in
                   ("path", "source_sha256", "quote", "organisation_id")):
            raise ValueError("citation text fields must be strings")
        start, end = citation["start"], citation["end"]
        source = payload["sources"].get(citation["path"])
        if not source or source["state"] != "current":
            raise ValueError("citation must select a supplied current source")
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(source["text"])
                or citation["quote"] != source["text"][start:end]
                or not citation["quote"].strip()
                or citation["source_sha256"] != source["sha256"]):
            raise ValueError("citation span/quote/hash mismatch")
        org = citation["organisation_id"]
        if org not in orgs:
            raise ValueError("citation names an absent organisation")
        if citation["path"].startswith("orgs/") and (
            citation["path"] != f"orgs/{org}.json"
            or ev.strict_json(source["text"]).get("id") != org
        ):
            raise ValueError("citation organisation does not own that source")
        projected.append({key: citation[key] for key in ("path", "source_sha256", "quote")})
    answer = ev.canonical(parsed["answer"])
    ev.validate_result(answer, projected, payload)  # Unchanged safety and citation ruler.
    return {"raw_response": answer, "citations": projected,
            "model_raw_response": raw, "model_raw_sha256": ev.sha(raw),
            "model_returned_citations": deepcopy(cited)}


def finish(directory, events):
    header = events[0]
    plan = header["plan"]
    if (plan != export(plan["source_commit"]) or header["mode"] != "SOURCE_FAKE"
            or header["slots"] != slots(plan)):
        raise ValueError("candidate/source/request/slot binding mismatch")
    rows = deepcopy(header["slots"])
    for event in events[1:]:
        ordinal = event.get("ordinal")
        if type(ordinal) is not int or not 0 <= ordinal < 14:
            raise ValueError("invalid journal ordinal")
        row = rows[ordinal]
        if event["kind"] == "started" and row["status"] == "not_run":
            row.update(status="unknown", request_sha256=plan["requests"][ordinal][
                "request_sha256"])
        elif event["kind"] == "response" and row["status"] == "unknown":
            row.update(status="completed", full_response=event["response"],
                       full_response_sha256=ev.sha(ev.canonical(event["response"])))
        elif event["kind"] == "error" and row["status"] == "unknown":
            row.update(status="error", error=event["error"])
        else:
            raise ValueError("duplicate or out-of-order candidate event")
    for row, case in zip(rows, ev.inputs(), strict=True):
        if row["status"] != "completed":
            continue
        try:
            response = row["full_response"]
            blocks = response["output"]["message"]["content"]
            if (response.get("stopReason") != "end_turn" or len(blocks) != 1
                    or set(blocks[0]) != {"text"} or not isinstance(blocks[0]["text"], str)):
                raise ValueError("one final text block required; no repair")
            raw = blocks[0]["text"]
            row.update(model_raw_response=raw, model_raw_sha256=ev.sha(raw))
        except (KeyError, TypeError, ValueError) as error:
            row.update(status="error", error=str(error))
            continue
        try:
            result = project(raw, case["adapter_input"])
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            # Preserve the rejected bytes; the strict frozen evaluator marks the
            # wrapper/malformed output invalid, never a successful abstention.
            # Even an old status/reason-only answer must remain invalid for this candidate.
            result = {"raw_response": ev.canonical({"invalid_candidate_raw": raw}),
                      "citations": [], "projection_error": str(error)}
        row.update(result=result, raw_sha256=ev.sha(result["raw_response"]))
    bundle = {"hashes": ev.PINS, "attempts": rows, "mode": "SOURCE_FAKE",
              "candidate_id": plan["candidate_id"], "candidate_sha256": RECIPE_SHA,
              "registration_commit": REGISTRATION, "source_commit": plan["source_commit"],
              "request_set_sha256": plan["request_set_sha256"],
              "actual_model_measurement": "NOT_ESTABLISHED",
              "model": {"id": "SOURCE_FAKE_NOT_AWS", "config": plan["requests"][0]["request"],
                        "usage": "SYNTHETIC_NOT_MEASURED", "cost": "NOT_A_BILL"}}
    c.create_json(Path(directory) / "receipts.json", bundle)
    return ev.evaluate(ev.saved_adapter(bundle), Path(directory) / "replay",
                       plan["source_commit"], "SOURCE_FAKE", header["run_id"],
                       bundle["model"], saved_receipts=bundle)


def slots(plan):
    return [{key: row[key] for key in ("case_id", "input_sha256", "source_hashes")}
            | {"status": "not_run"} for row in plan["requests"]]


def capture_fake(plan, directory, adapter):
    """Offline fixture boundary only; no client factory, credentials or live mode."""
    if plan != export(plan["source_commit"]):
        raise ValueError("candidate request binding mismatch")
    journal = c.Journal(Path(directory) / "journal")
    journal.record("planned", plan=plan, slots=slots(plan), mode="SOURCE_FAKE",
                   run_id=os.environ.get("GITHUB_RUN_ID", "OFFLINE_UNVERIFIED"))
    for ordinal, row in enumerate(plan["requests"]):
        journal.record("started", ordinal=ordinal)  # Durable before even calling fixture.
        try:
            response = adapter(deepcopy(row["request"]))
        except Exception as error:
            journal.record("error", ordinal=ordinal, error=f"{type(error).__name__}: {error}")
            break
        journal.record("response", ordinal=ordinal, response=response)  # Raw before parse.
    return finish(directory, journal.events)


def fake_response(request):
    """Mechanical citation fixture, explicitly NOT model-chosen or quality evidence."""
    payload = ev.strict_json(request["messages"][0]["content"][1]["text"].split("\n", 1)[1])
    cited = [{"path": path, "source_sha256": source["sha256"], "quote": source["text"],
              "start": 0, "end": len(source["text"]), "organisation_id": "centre"}
             for path, source in payload["sources"].items()
             if path in (ev.ORGANISATION, ev.MANIFEST) and source["state"] == "current"]
    response = c.FakeClient().converse()
    response["output"]["message"]["content"] = [{"text": ev.canonical({
        "answer": {"status": "needs_changes", "reason": "Synthetic cited review fixture."},
        "citations": cited})}]
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("export", "source-smoke", "replay"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--journal", type=Path)
    args = parser.parse_args()
    if args.mode == "replay":
        if args.journal is None:
            parser.error("replay requires an existing source-fake --journal, never resumes calls")
        report = finish(args.output, c.load_events(args.journal))
        return 0 if report["input_aligned_complete"] else 1
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    subprocess.run(["git", "merge-base", "--is-ancestor", REGISTRATION, source],
                   cwd=ROOT, check=True)
    plan = export(source)
    c.create_json(args.output / "requests.json", plan)
    c.create_json(args.output / "reference-cost-NOT-A-GRANT.json", {
        "authority": "NONE", **c.budget_plan(plan, c.REFERENCE_RATES)})
    if args.mode == "export":
        return 0
    report = capture_fake(plan, args.output / "fake", fake_response)
    return 0 if report["input_aligned_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

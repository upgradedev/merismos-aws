"""Bounded one-shot Converse transport; not the application's Strands tool loop.

Export is inert. Collection requires an exact parent-configured grant. No
CountTokens, tools, repair, fallback, caching request or adaptive thinking.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

from merismos.bedrock import INSTRUCTIONS, SPECIALIST_BRIEF

ROOT = Path(__file__).resolve().parents[1]
BASE = "6d401f79dea8d9e5568021df42f56c082d385c4e"
MODEL = "eu.anthropic.claude-opus-5"
REGION = "eu-west-1"
MAX_OUTPUT = 768
TEMPLATE_OVERHEAD = 4096
MAX_INPUT = 16384
FROZEN_CODE = {
    "scripts/evaluate_interpretation.py":
        "de90549249e8227984141ac84fadfc0e0ecf648895a092d4831544ca91e56f09",
    "src/merismos/bedrock.py":
        "4c7781ab44ac12ba1bc796abf3c3106a6a51fa736acfdade9be6e80a233e4532",
}
SPEC = importlib.util.spec_from_file_location(
    "frozen_interpretation", ROOT / "scripts/evaluate_interpretation.py"
)
ev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ev)


def export(source):
    """No gold read or model construction. Preserve the application's prompt."""
    for path, digest in FROZEN_CODE.items():
        # Git LF content identity; a Windows checkout may have CRLF line endings.
        if ev.sha((ROOT / path).read_bytes().replace(b"\r\n", b"\n")) != digest:
            raise ValueError(f"frozen code changed: {path}")
    ev.frozen("protocol")
    rows = []
    for case in ev.inputs():
        offer = case["adapter_input"]["offer"]
        question = (
            f"Offer {offer.get('id')}: {offer.get('title')!r} from "
            f"{offer.get('donor')}. {offer.get('quantity')} {offer.get('unit')}, "
            f"category {offer.get('category')}. The donor's note says: "
            f"{offer.get('note')!r}\n\n"
            f"Decide whether this offer can be apportioned as it stands."
        )
        request = {
            "modelId": MODEL,
            "system": [{"text": f"{SPECIALIST_BRIEF['premises']}\n{INSTRUCTIONS}"}],
            "messages": [{"role": "user", "content": [
                {"text": question},
                {"text": "Pre-opened source snapshot (tools unavailable in this one-shot "
                         "transport):\n" + ev.canonical(case["adapter_input"])}]}],
            "inferenceConfig": {"maxTokens": MAX_OUTPUT},
            "additionalModelRequestFields": {"thinking": {"type": "disabled"}},
        }
        # Entire JSON, not only visible prose, plus a deliberately large framing
        # allowance. This is a reviewed byte-token upper-bound assumption, not a
        # measured tokenizer count or a claim valid for arbitrary future models.
        wire = ev.canonical(request).encode("utf-8")
        bound = len(wire) + TEMPLATE_OVERHEAD
        if bound > MAX_INPUT:
            raise ValueError("finite input ceiling exceeded")
        rows.append({"case_id": case["case_id"], "input_sha256": case["input_sha256"],
                     "source_hashes": {p: s["sha256"] for p, s in
                                       case["adapter_input"]["sources"].items()},
                     "request": request, "request_sha256": ev.sha(wire),
                     "request_utf8_bytes": len(wire), "input_token_bound": bound,
                     "citations": ev.citations(case["adapter_input"])})
    return {"source_commit": source, "frozen_base": BASE, "hashes": ev.PINS,
            "model_id": MODEL, "region": REGION, "max_output_tokens": MAX_OUTPUT,
            "template_overhead_tokens": TEMPLATE_OVERHEAD,
            "adapter": "ONE_SHOT_CONVERSE_PREOPENED_NOT_STRANDS",
            "citation_semantics": "mechanical supplied-source provenance, NOT model-selected "
                                  "citations or semantic entailment",
            "input_bound_assumption": "one token per serialized UTF8 byte plus4096 framing; "
                                      "requires parent approval for this exact model",
            "requests": rows, "request_set_sha256": ev.sha(ev.canonical(rows)),
            "max_request_utf8_bytes": max(r["request_utf8_bytes"] for r in rows),
            "sum_request_utf8_bytes": sum(r["request_utf8_bytes"] for r in rows),
            "sum_input_token_bound": sum(r["input_token_bound"] for r in rows)}


def create_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("export",))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    plan = export(source)
    create_json(args.output / "requests.json", plan)
    print(json.dumps({key: value for key, value in plan.items() if key != "requests"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

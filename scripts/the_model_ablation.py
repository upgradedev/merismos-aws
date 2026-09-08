#!/usr/bin/env python
"""What does the model actually change? Run it and read the diff.

    python scripts/the_model_ablation.py

**Why this is separate from the swap test.** They sound alike and they answer
opposite questions, and conflating them is the easiest dishonesty available to a
project like this one.

`scripts/the_swap_test.py` asks whether the **SDK** is on the path a stranger
runs. It is, and removing it breaks the demo.

This asks whether the **model** changes the answer. On the offline path it does
not, and that has to be said out loud rather than left for somebody to find. The
scripted planner walks the real agent loop through the real dispatcher under the
real guard, and then answers `ok` with no findings, so the union with the
deterministic envelope moves nothing. Union never loosens, which is the whole
design, and it means an agent that contributes nothing contributes nothing
visible.

So the offline path is honest about being deterministic in its **conclusions**
while being genuinely agentic in its **mechanism**. Both halves are true and
neither implies the other.

The number that is not decoration is the deployed one. A run on Claude Opus 5
found undeclared milk and gluten in a manifest and a contradiction between a
donor's whole-lot condition and this network's own ceiling, none of which any
rule here compares. That run is recorded in `docs/live-run-2026-09-02.md`, and it
cannot be reproduced by this script, which needs no account.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("MERISMOS_CORPUS", "local")
os.environ.setdefault("MERISMOS_LEDGER", "memory")
os.environ.setdefault("MERISMOS_ROLE", "reader")

from merismos import bedrock  # noqa: E402
from merismos.corpus import LocalCorpus, offers  # noqa: E402
from merismos.fleet import new_run_id, run_chore, subject_for_offer  # noqa: E402
from merismos.ledger import InMemoryLedger, Thread  # noqa: E402

NETWORK = "kypseli-network"


def decision(corpus, offer, analyst) -> dict:
    """Everything about a run that a reader would call the answer."""
    thread = Thread(
        ledger=InMemoryLedger(),
        subject=subject_for_offer(NETWORK, offer),
        run_id=new_run_id(),
    )
    result = run_chore(corpus, offer, thread, analyst=analyst, network=NETWORK)
    return {
        "outcome": result.outcome,
        "shares": sorted(
            (a["org"], a["quantity"]) for a in (result.draft.allocations if result.draft else [])
        ),
        "excluded": sorted(result.draft.must_not_receive) if result.draft else [],
        "findings": sorted(
            (e.specialist, f.check) for e in result.envelopes for f in e.findings
        ),
    }


def main() -> int:
    corpus = LocalCorpus()
    fixture = offers(corpus)

    if not fixture:
        print("N = 0. There is nothing to compare, which is an instrument failure.")
        return 1

    rows = [
        (o["id"], decision(corpus, o, None), decision(corpus, o, bedrock.scripted_analyst()))
        for o in fixture
    ]
    differing = [oid for oid, without, with_model in rows if without != with_model]

    print(f"N = {len(rows)} comparisons, one per offer in corpus/offers/")
    print()
    for oid, without, with_model in rows:
        mark = "identical" if without == with_model else "DIFFERS"
        print(
            f"  {oid:12s}  rules only: {without['outcome']:18s}"
            f"  with the agent: {with_model['outcome']:18s}  {mark}"
        )
        if without != with_model:
            for key in ("outcome", "shares", "excluded", "findings"):
                if without[key] != with_model[key]:
                    print(f"      {key}: {without[key]!r} -> {with_model[key]!r}")
    print()

    if differing:
        print(
            f"{len(differing)} of {len(rows)} differ: {', '.join(differing)}.\n"
            "The offline agent changes the answer, and the README has to say how."
        )
        return 0

    print(
        f"0 of {len(rows)} differ. The diff is empty, and that is the honest reading:\n"
        "\n"
        "  the offline agent is real in its mechanism and contributes nothing to\n"
        "  the conclusion. It walks the Strands loop, through the real dispatcher,\n"
        "  under the real guard, and then answers ok with no findings, so the\n"
        "  union with the deterministic envelope moves nothing.\n"
        "\n"
        "That is stated in the README in the same sentence as the claim, which is\n"
        "what this check exists to force. The model that does change an answer is\n"
        "the deployed one, and that evidence is a recorded run rather than this.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

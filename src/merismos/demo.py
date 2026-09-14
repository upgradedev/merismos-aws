"""The run a judge watches, and the run the video records.

``python -m merismos.demo`` walks the three offers in the corpus and prints what
the fleet decided about each, then prints the comparison that decides whether
this is an agent or a rules engine.

**It says which path it took, on the first line, every time.** A demo that
quietly falls back to a stub shows a stub, and nobody watching can tell. So the
banner names the ledger, the model and the scheduler, and the offline
combination is announced rather than hidden.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from . import bedrock
from .corpus import corpus_from_env
from .corpus import offers as read_offers
from .corpus import orgs as read_orgs
from .deferral import NullScheduler, scheduler_from_env
from .fleet import new_run_id, premises, run_chore, subject_for_offer
from .ledger import InMemoryLedger, Thread, ledger_from_env

NETWORK = "kypseli-network"


def _colour(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def banner(ledger: Any, analyst: Any, scheduler: Any, colour: bool) -> None:
    """Name the path this run actually took. Never the path it intended."""
    backend = getattr(ledger, "backend", "unknown")
    model = getattr(analyst, "model_id", "none, deterministic only")
    timer = "eventbridge one-shot" if getattr(scheduler, "configured", False) else "none"

    print("=" * 72)
    print("  MERISMOS, apportionment and the record of how it was decided")
    print("=" * 72)
    print(f"  ledger      {backend}")
    print(f"  model       {model}")
    print(f"  scheduler   {timer}")
    scripted = str(model).startswith("scripted-planner")
    if backend == "memory" and (analyst is None or scripted):
        print()
        print(
            _colour(
                "  OFFLINE PATH. No AWS account is in use and nothing here opens a socket.",
                "33",
                colour,
            )
        )
        if scripted:
            # Said precisely, because the difference matters to the one claim
            # this entry rests on. The agent loop, the tool dispatcher and the
            # guard are the deployed ones. Bedrock is what is absent.
            print(
                _colour(
                    "  The specialists run as real Strands agents over a scripted model:",
                    "33",
                    colour,
                )
            )
            print(
                _colour(
                    "  the same dispatcher, the same BeforeToolCallEvent guard, no Bedrock.",
                    "33",
                    colour,
                )
            )
        else:
            print(
                _colour(
                    "  The specialists are the deterministic rules alone and no model,",
                    "33",
                    colour,
                )
            )
            print(
                _colour(
                    "  and no agent, is consulted at all.", "33", colour
                )
            )
    print("=" * 72)
    print()


def analyst_reached(result: Any, analyst: Any, colour: bool) -> int:
    """Say what the specialists actually reached, and count what they did not.

    ``run_chore`` turns an unreachable analyst into a ``model-unreachable``
    finding and carries on with the deterministic answer, which is the right
    behaviour for a model outage and the wrong thing to leave unsaid. Without
    this line the screen is identical whether the SDK was there or not, and a
    swap test that removes it stays green.
    """
    if analyst is None:
        return 0

    missed = [
        e.specialist
        for e in result.envelopes
        for f in e.findings
        if f.check == "model-unreachable"
    ]
    reached = [e.specialist for e in result.envelopes if e.specialist not in missed]

    if not missed:
        print(
            f"    analyst    {getattr(analyst, 'model_id', 'unknown')}, "
            f"reached by all {len(reached)}"
        )
        return 0

    print(
        _colour(
            f"    analyst    NOT REACHED by {', '.join(missed)}. "
            f"Deterministic rules only",
            "31",
            colour,
        )
    )
    return len(missed)


def show(result: Any, colour: bool) -> None:
    """One offer's outcome, in the words a coordinator would use."""
    tint = {
        "blocked": "31",
        "refused_by_gate": "31",
        "awaiting_approval": "32",
        "approved": "32",
        "nothing_to_allocate": "33",
    }.get(result.outcome, "0")

    print(f"  offer {result.offer_id}")
    print(f"    outcome    {_colour(result.outcome, tint, colour)}")
    if result.note:
        print(f"    because    {result.note[:120]}")
    if result.draft:
        for allocation in result.draft.allocations:
            print(
                f"      -> {allocation['org']:<28} {allocation['quantity']:>8} "
                f"{result.draft.offer.get('unit', '')}"
            )
        barred = sorted(result.draft.must_not_receive)
        if barred:
            print(f"    not receiving  {', '.join(barred)}")
    if result.read_log.get("spent"):
        opened = [e["path"] for e in result.read_log.get("reads", []) if e["served"]]
        print(f"    opened     {', '.join(opened) or 'nothing'}")
    print()


def the_case_that_settles_it(corpus: Any, colour: bool) -> None:
    """Offer 4483, read both ways, side by side.

    This is the comparison ``tests/unit/test_rules_alone_are_not_enough.py``
    pins, run live rather than quoted, so a viewer sees the two answers rather
    than being told about them.
    """
    offer = next((o for o in read_offers(corpus) if o["id"] == "offer-4483"), None)
    if offer is None:
        # Another network's filing. This comparison needs the one offer built to
        # carry it, and saying so beats both a traceback and silence: a reader
        # who pointed this at their own corpus should be told what was skipped
        # and why, rather than wondering what the section was for.
        print("-" * 72)
        print("  The manifest comparison is skipped")
        print("-" * 72)
        print("  It needs offer-4483, which is the offer in this repository's own")
        print("  corpus built to carry it: declared ambient with no allergens, and a")
        print("  manifest holding wine, pork and hazelnut. This filing does not have")
        print("  it, and everything above is this filing's own offers, decided.")
        print()
        return
    orgs = read_orgs(corpus)
    manifest = corpus.read("offers/manifests/4483.md")

    print("-" * 72)
    print("  Is this a rules engine, or does reading actually change the answer")
    print("-" * 72)
    print(f"  offer-4483 declares: category {offer['category']}, allergens "
          f"{offer['allergens']}")
    print("  its manifest lists:  wine, pork salami and hazelnut, inside gift hampers")
    print()

    for label, text in (
        ("declared fields only", ""),
        ("after reading the manifest", manifest),
    ):
        envelope = premises(offer, orgs, manifest_text=text)
        excluded = envelope.meta["blocked_for"]
        tint = "31" if excluded else "33"
        print(f"  {label:<28} {envelope.status.value}")
        print(f"    findings   {len(envelope.findings)}")
        print(
            f"    excluded   {_colour(', '.join(excluded) or 'nobody', tint, colour)}"
        )
    print()
    print("  The first answer ships alcohol to a recovery shelter and a school.")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="merismos.demo", description=__doc__)
    parser.add_argument(
        "--ledger",
        choices=["memory", "dynamodb"],
        default="",
        help="memory needs no AWS account and announces itself",
    )
    parser.add_argument(
        "--model",
        default="",
        help="a Bedrock inference profile, or 'none' for the deterministic path",
    )
    parser.add_argument("--no-colour", action="store_true")
    args = parser.parse_args(argv)

    colour = not args.no_colour and sys.stdout.isatty()
    env = dict(os.environ)
    if args.ledger:
        env["MERISMOS_LEDGER"] = args.ledger
    if args.model:
        env["MERISMOS_MODEL"] = args.model

    # The offline default is explicit here rather than implicit. A judge running
    # this with no AWS account gets the offline path and is told so.
    offline_ledger = env.get("MERISMOS_LEDGER", "memory") == "memory"
    ledger = InMemoryLedger() if offline_ledger else ledger_from_env(env)
    # The offline default is the **scripted** analyst rather than no analyst.
    #
    # It was no analyst, and a swap test caught what that cost. A stub `strands`
    # that imports and refuses when used left the whole demo path green, 53 tests
    # across the judge's journey and every screen, because with no analyst no
    # Agent is ever constructed and the SDK is not on the path a stranger runs.
    # The entry's flagship claim was true of the deployed fleet and false of the
    # thirty second quickstart.
    #
    # `MERISMOS_MODEL=none` still means what it always meant, the rules alone,
    # and the tests that ask what the rules do still use it.
    env.setdefault("MERISMOS_MODEL", "scripted")
    analyst = bedrock.analyst_from_env(env)
    scheduler = (
        scheduler_from_env(env) if env.get("MERISMOS_WAKE_TARGET_ARN") else NullScheduler()
    )
    # Always through corpus_from_env, so MERISMOS_CORPUS_ROOT works here exactly
    # as it works in the deployed handler. It read LocalCorpus() directly when no
    # bucket was set, which pinned the demo to the corpus inside this repository:
    # point it at another network's filing and it silently showed you ours.
    # Persona 09 asks for the quickstart to be run against a substitute fixture
    # and calls identical output the harder failure, because it means the fixture
    # is never read. It was identical.
    corpus = corpus_from_env(env)

    banner(ledger, analyst, scheduler, colour)
    unreachable = 0

    for offer in read_offers(corpus):
        thread = Thread(
            ledger=ledger,
            subject=subject_for_offer(NETWORK, offer),
            run_id=new_run_id(),
        )
        result = run_chore(
            corpus, offer, thread, analyst=analyst, scheduler=scheduler, network=NETWORK
        )
        show(result, colour)
        unreachable += analyst_reached(result, analyst, colour)

    the_case_that_settles_it(corpus, colour)

    print("-" * 72)
    print("  Nothing above published anything. Every run stops at a card a person")
    print("  reads, and the publish is the writer's, behind an approval bound to")
    print("  the exact bytes.")
    print("-" * 72)

    if unreachable:
        print()
        print(
            _colour(
                f"  THE ANALYST WAS NOT REACHED, on {unreachable} specialist reads.",
                "31",
                colour,
            )
        )
        print(
            _colour(
                "  Everything above is the deterministic rules alone. The banner named",
                "31",
                colour,
            )
            )
        print(
            _colour(
                "  a path this run did not take, and this line is how you know.",
                "31",
                colour,
            )
        )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

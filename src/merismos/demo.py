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
from .corpus import LocalCorpus, corpus_from_env
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
    if backend == "memory" and analyst is None:
        print()
        print(
            _colour(
                "  OFFLINE PATH. No AWS account is in use. The specialists are the",
                "33",
                colour,
            )
        )
        print(
            _colour(
                "  deterministic rules alone and no model is consulted.", "33", colour
            )
        )
    print("=" * 72)
    print()


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

    This is the comparison the README reports, run live rather than quoted, so a
    viewer sees the two answers rather than being told about them.
    """
    offer = next(o for o in read_offers(corpus) if o["id"] == "offer-4483")
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
    # this with no AWS account gets the deterministic path and is told so.
    offline_ledger = env.get("MERISMOS_LEDGER", "memory") == "memory"
    ledger = InMemoryLedger() if offline_ledger else ledger_from_env(env)
    analyst = bedrock.analyst_from_env(env) if env.get("MERISMOS_MODEL") else None
    scheduler = (
        scheduler_from_env(env) if env.get("MERISMOS_WAKE_TARGET_ARN") else NullScheduler()
    )
    corpus = corpus_from_env(env) if env.get("MERISMOS_CORPUS_BUCKET") else LocalCorpus()

    banner(ledger, analyst, scheduler, colour)

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

    the_case_that_settles_it(corpus, colour)

    print("-" * 72)
    print("  Nothing above published anything. Every run stops at a card a person")
    print("  reads, and the publish is the writer's, behind an approval bound to")
    print("  the exact bytes.")
    print("-" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

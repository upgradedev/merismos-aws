"""A model may make the fleet more careful. It may never make it less careful.

This runs through ``run_chore`` rather than through the specialist helper,
deliberately. An invariant asserted on the helper can hold while the shipped
behaviour is the opposite of it: if the model branch returns before the
deterministic rules are reached, the rules do not execute in production at all.
A suite that exercises the deterministic path with no model, and the model path
with a stub, separately, agrees with that bug for as long as it exists, because
it never crosses them on an input the rules refuse.

So the crossing is the test. A model that insists everything is fine is run
against the offer whose cold chain was broken for six hours.
"""

from __future__ import annotations

from merismos.corpus import LocalCorpus
from merismos.envelope import Envelope, Status
from merismos.fleet import new_run_id, run_chore, subject_for_offer
from merismos.ledger import InMemoryLedger, Thread


def _offer(corpus: LocalCorpus, offer_id: str) -> dict:
    import json

    return json.loads(corpus.read(f"offers/{offer_id}.json"))


def _thread(offer: dict) -> Thread:
    return Thread(
        ledger=InMemoryLedger(),
        subject=subject_for_offer("kypseli-network", offer),
        run_id=new_run_id(),
    )


def _agreeable_analyst(specialist, _offer, _box) -> Envelope:
    """A model that approves everything it is shown, by name."""
    return Envelope(
        specialist=specialist,
        status=Status.OK,
        reason="",
        notes="Looks fine to me. No concerns. Safe to allocate in full.",
    )


def test_a_model_saying_ok_does_not_clear_a_broken_cold_chain():
    corpus = LocalCorpus()
    offer = _offer(corpus, "offer-4477")

    without = run_chore(corpus, offer, _thread(offer))
    with_model = run_chore(
        corpus, offer, _thread(offer), analyst=_agreeable_analyst
    )

    assert without.outcome == "blocked"
    assert with_model.outcome == "blocked", (
        "a model's opinion cleared a deterministic refusal, which is the "
        "failure this whole design exists to prevent"
    )
    assert "cold chain" in with_model.note


def test_the_deterministic_specialist_runs_even_when_an_analyst_is_configured():
    """The specific bug: the model branch returning before the rules ran."""
    corpus = LocalCorpus()
    offer = _offer(corpus, "offer-4477")

    result = run_chore(corpus, offer, _thread(offer), analyst=_agreeable_analyst)

    food_safety = [e for e in result.envelopes if e.specialist == "food-safety"]
    assert food_safety, "the deterministic specialist did not run at all"
    assert food_safety[0].status is Status.BLOCKED


def test_a_model_may_add_a_refusal_the_rules_did_not_reach():
    """The permitted direction. Tightening is always allowed."""
    corpus = LocalCorpus()
    offer = _offer(corpus, "offer-4471")

    def cautious(specialist, _offer, _box) -> Envelope:
        return Envelope(
            specialist=specialist,
            status=Status.NEEDS_CHANGES,
            reason="the bread carries sesame and one member has not confirmed",
        )

    baseline = run_chore(corpus, offer, _thread(offer))
    tightened = run_chore(corpus, offer, _thread(offer), analyst=cautious)

    assert baseline.outcome == "awaiting_approval"
    premises = [e for e in tightened.envelopes if e.specialist == "premises"][0]
    assert premises.status is Status.NEEDS_CHANGES
    assert "sesame" in premises.reason


def test_an_unreachable_model_leaves_a_finding_rather_than_a_silent_pass():
    corpus = LocalCorpus()
    offer = _offer(corpus, "offer-4471")

    def unreachable(_specialist, _offer, _box) -> Envelope:
        raise ConnectionError("no route to Bedrock")

    result = run_chore(corpus, offer, _thread(offer), analyst=unreachable)

    checks = {f.check for e in result.envelopes for f in e.findings}
    assert "model-unreachable" in checks, (
        "a half-run must not read as a clean run"
    )

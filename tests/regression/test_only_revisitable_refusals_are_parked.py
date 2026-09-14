"""A cold chain refusal was scheduled for another look in two days.

``_defer`` parked every blocked specialist, unconditionally. The feature is for
an unknown which resolves: a shelter cannot confirm fridge space until Thursday,
so the decision is parked.

Six hours above eight degrees is not an unknown. It is a fact about the past, and
the register's answer is "refused in full. Not reduced, not allocated to whoever
can collect fastest." The only thing two days changes is that the food is worse.

Nothing broke when this was fixed, which is the part worth recording: **no test
asserted what a blocked chore produces.** The feature's end to end behaviour was
uncovered, which is how the wrong version survived being read several times.
"""

from __future__ import annotations

import json

import pytest

from merismos.corpus import LocalCorpus
from merismos.envelope import Status
from merismos.fleet import capacity, food_safety, new_run_id, run_chore, subject_for_offer
from merismos.ledger import InMemoryLedger, Thread

NETWORK = "kypseli-network"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_MODEL", "none")


def chore(offer_id: str):
    corpus = LocalCorpus()
    offer = json.loads(corpus.read(f"offers/{offer_id}.json"))
    thread = Thread(
        ledger=InMemoryLedger(),
        subject=subject_for_offer(NETWORK, offer),
        run_id=new_run_id(),
    )
    return run_chore(corpus, offer, thread, network=NETWORK)


# --------------------------------------------------------------------------
# Facts about the past are final.
# --------------------------------------------------------------------------


def test_a_broken_cold_chain_is_refused_and_not_parked_for_another_look():
    """offer-4477 spent six hours above eight degrees. That does not improve."""
    result = chore("offer-4477")

    assert result.outcome == "blocked"
    assert result.deferrals == [], (
        "a cold chain refusal was scheduled for review. Waking somebody to look "
        "again at food that is now two days older is asking for their judgement "
        "where the register has already given the answer"
    )


@pytest.mark.parametrize(
    ("offer", "why"),
    [
        (
            {"category": "chilled", "hours_unrefrigerated": 6, "quantity": 10, "unit": "kg"},
            "the cold chain was broken",
        ),
        (
            {
                "category": "ambient",
                "quantity": 10,
                "unit": "kg",
                "collection_date": "2026-09-14",
                "use_by": "2026-09-13",
            },
            "the use by is before collection",
        ),
        (
            {"category": "chilled", "quantity": 10, "unit": "kg"},
            "a chilled offer that never recorded its hours",
        ),
    ],
)
def test_no_food_safety_refusal_offers_a_reason_to_look_again(offer, why):
    """None of these turn on something that can change, so none may be parked."""
    envelope = food_safety(offer, [{"name": "A", "same_day_service": True}])

    assert envelope.status is Status.BLOCKED, why
    assert not envelope.meta.get("revisit_because"), (
        f"{why}, and the fleet is offering to reconsider it"
    )


def test_silence_is_read_as_final_rather_than_as_revisitable():
    """The default has to fall on the safe side.

    A specialist that says nothing about whether waiting helps is a specialist
    that has not thought about it, and the answer to "should somebody be woken
    about this" is then no.
    """
    from merismos.envelope import Envelope
    from merismos.fleet import _defer

    silent = Envelope(specialist="premises", status=Status.BLOCKED, reason="absolute")
    thread = Thread(ledger=InMemoryLedger(), subject="s", run_id="r")

    assert _defer(silent, thread, None, None) is None
    assert not thread.ledger.recall("s", "finding.deferred"), (
        "a deferral was written to the thread for a refusal that was never parked"
    )


# --------------------------------------------------------------------------
# The case the feature is for still works.
# --------------------------------------------------------------------------


def test_a_block_that_turns_on_something_changeable_is_parked_and_says_why():
    """Cold storage is a fact about the members, not about the offer."""
    nobody_can_store = capacity(
        {"category": "chilled", "quantity": 10, "unit": "kg"},
        [{"name": "A", "cold_storage_litres": 0, "has_van": True, "premises_constraints": []}],
    )

    assert nobody_can_store.status is Status.BLOCKED
    assert "worth asking again" in nobody_can_store.meta.get("revisit_because", "")


def test_the_parked_reason_is_why_it_is_worth_asking_again_not_why_it_failed():
    """A wake that repeats the refusal tells the reader nothing new.

    The deferral carries the reason to look again, which is a different sentence
    from the reason it was refused, and it is the one somebody woken in two days
    needs.
    """
    from merismos.deferral import NullScheduler
    from merismos.fleet import _defer

    blocked = capacity(
        {"category": "chilled", "quantity": 10, "unit": "kg"},
        [{"name": "A", "cold_storage_litres": 0, "has_van": True, "premises_constraints": []}],
    )
    thread = Thread(ledger=InMemoryLedger(), subject="s", run_id="r")

    deferral = _defer(blocked, thread, NullScheduler(), None)

    assert deferral is not None
    assert "worth asking again" in deferral.reason
    assert "spoils" not in deferral.reason, (
        "the deferral is repeating the refusal rather than saying what changed"
    )

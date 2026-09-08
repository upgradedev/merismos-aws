"""A published record is not a collection, and the gap is where this fails.

Until somebody has said "we will take the shelter's twenty kilos, Thursday at
six", the network has a decision and no van. The phone calls this product exists
to remove start again, around the decision instead of around the split.

These pin the three facts that close a share, the two ways it silently does not,
and the rule that an agreement does not survive a change to what was agreed.
"""

from __future__ import annotations

import pytest

from merismos import pickup

SHARES = [
    {"org": "Omonoia Soup Kitchen", "quantity": 96.0},
    {"org": "Elpida Night Shelter", "quantity": 20.0},
]
DIGEST = "sha256:abc123"


def a_claim(org="Elpida Night Shelter", role="duty manager", **kw):
    return pickup.claim(
        offer_id="offer-4471",
        org=org,
        role=role,
        allocations=SHARES,
        plan_digest=DIGEST,
        unit="kg",
        **kw,
    )


# --------------------------------------------------------------------------
# The three facts.
# --------------------------------------------------------------------------


def test_a_claim_names_an_organisation_and_a_role_and_never_a_person():
    claimed = a_claim()

    assert claimed.org == "Elpida Night Shelter"
    assert claimed.role == "duty manager"
    assert "name" not in claimed.as_dict()
    assert "phone" not in claimed.as_dict()


def test_a_role_outside_the_fixed_set_is_refused_because_that_is_where_a_name_lands():
    """Free text here is where "ring Maria on 694..." arrives, and it is published."""
    with pytest.raises(pickup.NotClaimable) as caught:
        a_claim(role="Maria, 6944 123 456")

    assert "does not go here" in str(caught.value)


def test_the_quantity_comes_from_the_plan_and_not_from_whoever_is_asking():
    """A van saying how much it is owed is the failure this exists to prevent."""
    assert a_claim().quantity == 20.0
    assert a_claim(org="Omonoia Soup Kitchen", role="kitchen lead").quantity == 96.0


def test_an_organisation_with_no_share_cannot_claim_one():
    with pytest.raises(pickup.NotClaimable) as caught:
        a_claim(org="Kypseli Food Pantry")

    assert "has no share" in str(caught.value)


def test_an_agreed_time_is_recorded_and_is_not_required_to_claim():
    """Somebody taking it is worth recording before the time is settled."""
    assert a_claim().state == "claimed"
    assert a_claim(agreed_at="2026-09-08 18:00").state == "agreed"


# --------------------------------------------------------------------------
# Confirmation, and the pending state that must stay visible.
# --------------------------------------------------------------------------


def test_a_collection_is_never_confirmed_by_default():
    """The whole point. Assuming it happened is how a network stops noticing."""
    assert a_claim().confirmed_at is None
    assert a_claim().state != "confirmed"


def test_confirming_is_explicit_and_idempotent():
    once = pickup.confirm(a_claim(), at=1000.0)
    twice = pickup.confirm(once, at=2000.0)

    assert once.state == "confirmed"
    assert twice.confirmed_at == 1000.0, "a second confirmation moved the record of the first"


def test_the_two_ways_a_decision_fails_to_become_food_are_shown_together():
    """Unclaimed and unconfirmed are different problems and both are invisible
    in a record that only says who was allocated what."""
    claims = [pickup.confirm(a_claim(org="Omonoia Soup Kitchen", role="kitchen lead"))]

    state = pickup.outstanding(SHARES, claims, DIGEST)

    assert [u["org"] for u in state["unclaimed"]] == ["Elpida Night Shelter"]
    assert [c["org"] for c in state["confirmed"]] == ["Omonoia Soup Kitchen"]
    assert state["unconfirmed"] == []


def test_a_claim_nobody_confirmed_is_outstanding_rather_than_finished():
    state = pickup.outstanding(SHARES, [a_claim()], DIGEST)

    assert [c["org"] for c in state["unconfirmed"]] == ["Elpida Night Shelter"]
    assert [u["org"] for u in state["unclaimed"]] == ["Omonoia Soup Kitchen"]


# --------------------------------------------------------------------------
# An agreement is about specific bytes.
# --------------------------------------------------------------------------


def test_a_recomputed_plan_voids_the_claims_against_the_old_one():
    """Same rule as the approval nonce, and for the same reason.

    offer-4471 needed exactly this: its plan was wrong and was recomputed, and a
    standing agreement to collect 96 kg that nobody is allocated any more would
    have sent a van for food that was never going to be there.
    """
    claimed = a_claim()

    assert pickup.still_valid(claimed, DIGEST)
    assert not pickup.still_valid(claimed, "sha256:recomputed")

    state = pickup.outstanding(SHARES, [claimed], "sha256:recomputed")
    assert [c["org"] for c in state["void"]] == ["Elpida Night Shelter"]
    assert [u["org"] for u in state["unclaimed"]] == [
        "Omonoia Soup Kitchen",
        "Elpida Night Shelter",
    ]


def test_a_claim_has_to_name_the_plan_it_is_against():
    with pytest.raises(pickup.NotClaimable) as caught:
        pickup.claim(
            offer_id="offer-4471",
            org="Elpida Night Shelter",
            role="duty manager",
            allocations=SHARES,
            plan_digest="",
            unit="kg",
        )

    assert "name the plan" in str(caught.value)


def test_an_unconfirmed_claim_ages_out_rather_than_standing_for_ever():
    """A collection agreed a fortnight ago and never confirmed is not a plan."""
    stale = a_claim()
    fortnight = pickup.CLAIM_VALID_FOR_DAYS * 86400

    assert pickup.still_valid(stale, DIGEST, now=stale.claimed_at + fortnight - 1)
    assert not pickup.still_valid(stale, DIGEST, now=stale.claimed_at + fortnight + 1)

"""A typed offer travels the same road as the flagship one, or it is a toy.

Two fields were missing and each was missing in a different way.

``use_by`` did not exist at all, so the register's same-day rule, which turns on
the gap between collection and use by, could never fire on anything a
coordinator filed. The one condition that produced this network's worst
published record was not expressible through the product's own front door.

``allergens`` was worse, because it was present and wrong. It was hardcoded to
``[]``, and ``[]`` does not mean "nobody checked". It means "checked, and there
are none", which is exactly how ``premises`` reads it. A form nobody could put an
allergen into was clearing offers for a library that is nut free because a child
who eats there has a severe nut allergy.

The brief that prompted this said it in one line: do not turn unknowns into safe
defaults. These pin both halves, because recording an unknown honestly and then
reading it as a pass would be worse than not asking. The record would carry a
field saying nobody checked, beside a verdict that reads as though somebody had.
"""

from __future__ import annotations

import pytest

from merismos import intake
from merismos.envelope import Status
from merismos.fleet import food_safety, premises

BASE = {
    "title": "End of day bread and vegetables",
    "donor": "Neighbourhood bakery",
    "quantity": "240",
    "unit": "kg",
    "category": "ambient",
    "collection_date": "2026-09-14",
}

LIBRARY = {
    "name": "Anemos Community Library",
    "premises_constraints": ["alcohol_free_premises", "nut_free"],
}


def offer(**extra) -> dict:
    return intake.offer_from_form({**BASE, **extra}, "offer-9001")


# --------------------------------------------------------------------------
# use_by: the field that did not exist
# --------------------------------------------------------------------------


def test_a_coordinator_can_say_when_it_stops_being_good():
    assert offer(use_by="2026-09-15")["use_by"] == "2026-09-15"


def test_a_typed_offer_can_now_trigger_the_rule_that_broke_offer_4471():
    """The whole point. Collected the 14th, gone by the 15th, same-day members only."""
    envelope = food_safety(
        offer(use_by="2026-09-15"),
        [
            {"name": "Omonoia Soup Kitchen", "same_day_service": True},
            {"name": "Kypseli Food Pantry", "same_day_service": False},
        ],
    )

    assert envelope.meta.get("eligible") == ["Omonoia Soup Kitchen"], (
        "a typed offer that has to be gone the next day did not constrain who "
        "may receive it, which is the defect this field exists to make reachable"
    )


def test_an_unknown_use_by_is_recorded_as_unknown_and_raised():
    """Not a refusal. A donor who did not say is ordinary; a silent long date is not."""
    typed = offer()
    assert typed["use_by"] == ""

    envelope = food_safety(typed, [{"name": "Omonoia Soup Kitchen", "same_day_service": True}])
    checks = {f.check for f in envelope.findings}

    assert "use-by-not-established" in checks
    assert envelope.status is Status.NEEDS_CHANGES
    assert envelope.meta.get("eligible") is None, (
        "an unknown shelf life must not bar anybody, or the honest answer costs "
        "the coordinator more than the careless one and they stop being honest"
    )


def test_a_use_by_before_the_collection_date_is_refused_rather_than_reconciled():
    with pytest.raises(intake.Rejected) as caught:
        offer(use_by="2026-09-10")

    assert "before the collection date" in str(caught.value)


# --------------------------------------------------------------------------
# allergens: the field that was present and wrong
# --------------------------------------------------------------------------


def test_what_the_donor_said_is_carried_rather_than_discarded():
    assert offer(allergens="gluten, sesame")["allergens"] == ["gluten", "sesame"]
    assert offer(allergens="Nuts; Gluten")["allergens"] == ["gluten", "nuts"]


def test_nothing_typed_means_nobody_established_it_and_not_that_there_are_none():
    assert offer()["allergens"] is None, (
        "an empty list here is a claim that somebody checked. Nobody did"
    )
    assert offer(allergens="   ")["allergens"] is None


def test_an_unestablished_offer_is_raised_against_a_premises_constraint():
    """The library's constraint is absolute and this is the case that used to pass."""
    envelope = premises(offer(), [LIBRARY])
    checks = {f.check for f in envelope.findings}

    assert "allergens-not-established" in checks, (
        "an offer nobody has opened was cleared for a building that is nut free "
        "because a child who eats there has a severe nut allergy"
    )
    assert any(f.severity == "high" for f in envelope.findings)


def test_a_declared_allergen_still_bars_the_member_it_always_barred():
    """The new path must not have moved the old one."""
    envelope = premises(offer(allergens="nuts"), [LIBRARY])

    assert LIBRARY["name"] in envelope.meta.get("blocked_for", [])


def test_a_declared_none_is_still_available_to_anything_that_actually_checked():
    """``[]`` keeps its meaning: checked, and there are none.

    The corpus offers carry it and they are right to. Collapsing the two would
    have fixed the form by breaking the register.
    """
    checked = {**offer(), "allergens": []}
    envelope = premises(checked, [LIBRARY])
    checks = {f.check for f in envelope.findings}

    assert "allergens-not-established" not in checks
    assert not envelope.meta.get("blocked_for")

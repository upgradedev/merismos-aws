"""An IBAN was refused as "what reads as a phone number".

Caught, which is the safe direction, and caught **by accident**: ``_PHONE``
matches any run of nine or more digits, so an IBAN and a sixteen digit card
number both trip it.

Two things follow and the second is the one that matters. The message is wrong: a
coordinator told their note contains a phone number when they pasted a bank
account has been told to look for something that is not there, and the register's
position is that a refusal names a reason somebody can act on.

And the control works by luck. Tighten ``_PHONE`` to a plausible phone length,
which is the obvious future edit, and card numbers stop being caught at all, in a
record that is published and permanent.
"""

from __future__ import annotations

import pytest

from merismos import gate, intake
from merismos.corpus import LocalCorpus, org_names

BASE = {
    "title": "End of day bread",
    "donor": "A bakery",
    "quantity": "10",
    "unit": "kg",
    "category": "ambient",
    "collection_date": "2026-09-14",
}
IBAN = "GR16 0110 1250 0000 0001 2300 695"
CARD = "4111 1111 1111 1111"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")


def checks(body: str) -> set[str]:
    draft = gate.Draft(
        body=body,
        allocations=[{"org": "Omonoia Soup Kitchen", "quantity": 10.0, "reason": "x"}],
        offer={"id": "offer-x", "quantity": 100, "unit": "kg"},
        known_orgs=org_names(LocalCorpus()),
    )
    return {f.check for f in gate.check_personal_data(draft)}


def test_a_bank_account_is_named_a_bank_account():
    assert "no-bank-account" in checks(f"Pay to {IBAN}")


def test_a_card_number_is_named_a_card_number():
    assert "no-card-number" in checks(f"Card {CARD}")


def test_the_message_a_person_reads_says_what_to_remove():
    """"Remove the phone number" is not actionable when it is an account."""
    with pytest.raises(intake.Rejected) as caught:
        intake.offer_from_form({**BASE, "note": f"Pay to {IBAN}"}, "offer-9001")

    assert "bank account" in str(caught.value)
    assert "phone" not in str(caught.value)


def test_the_door_refuses_both_as_well_as_the_gate():
    for value in (IBAN, CARD):
        with pytest.raises(intake.Rejected):
            intake.offer_from_form({**BASE, "note": value}, "offer-9001")


def test_a_phone_number_is_still_a_phone_number():
    """The specific checks must not have swallowed the general one."""
    assert checks("Ring 694 412 3456") == {"no-phone-number"}


@pytest.mark.parametrize(
    "body",
    [
        "240 kg of bread, 96 kg allocated under the 40% cap",
        "collected 2026-09-14, use by 2026-09-15",
        "run-f2b3b0f80810 finished in 214 seconds",
        "41 households served weekly",
    ],
)
def test_ordinary_record_text_is_not_a_payment_instrument(body):
    assert not checks(body)


def test_the_protection_no_longer_depends_on_the_phone_pattern():
    """The point of the fix, asserted directly.

    If ``_PHONE`` were narrowed to a plausible phone length tomorrow, a card
    number must still be refused. Checked against the pattern itself rather than
    through the gate, so it holds whatever else changes.
    """
    assert gate._CARD.search(CARD)
    assert gate._IBAN.search(IBAN)

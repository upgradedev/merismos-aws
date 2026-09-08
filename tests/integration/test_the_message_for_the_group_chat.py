"""The one part of this product that belongs somewhere we do not own.

An investor persona's first criterion: **no surface the buyer already opens.** It
fails when everything underlined belongs to us, our app, our dashboard, our URL,
and its two passing examples both work for one reason, that the answer showed up
somewhere the buyer was already looking.

Every surface here was ours. The offers list, the decision screen, the card, the
published record. A volunteer coordinator who lives in a group chat had to open a
website to tell four other people what happened, which is the twelfth tab written
as a product.

This is the honest small version of the fix. The decision is written out as a
message in the words a coordinator would use, ready to select and send in the
chat that is already open on their phone. **Not sent by us**: sending would mean
holding a token for somebody's messaging account and posting under their name,
which is a different product and a conversation to have with a coordinator first.

What these pin is the part that would rot: that it carries the exclusions and
their reasons, which is the whole point, and that it never carries a person.
"""

from __future__ import annotations

import pytest

from merismos import handler
from merismos.corpus import LocalCorpus, offers


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()


def decision_screen(offer_id: str) -> str:
    from merismos.fleet import new_run_id, subject_for_offer
    from merismos.ledger import Thread, ledger_from_env

    offer = next(o for o in offers(LocalCorpus()) if o["id"] == offer_id)
    run = new_run_id()
    Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(handler.NETWORK, offer),
        run_id=run,
    ).append("run.started", offer_id=offer_id)
    handler._run_in_background(
        {
            "source": "merismos.background",
            "offer_id": offer_id,
            "run_id": run,
            "network": handler.NETWORK,
        }
    )
    reply = handler.handler(
        {
            "requestContext": {"http": {"method": "GET", "path": f"/offer/{offer_id}"}},
            "headers": {"content-type": "application/json"},
            "body": "{}",
            "queryStringParameters": {"run": run},
        }
    )
    assert reply["statusCode"] == 200
    return reply["body"]


def the_message(page: str) -> str:
    start = page.index("To send in the group chat")
    block = page[page.index("<pre", start) : page.index("</pre>", start)]
    return block[block.index(">") + 1 :]


def test_the_decision_comes_with_a_message_for_a_surface_we_do_not_own():
    page = decision_screen("offer-4471")

    assert "To send in the group chat" in page
    assert "belongs where you already are" in page


def test_the_message_carries_the_shares():
    text = the_message(decision_screen("offer-4471"))

    # These two lines asserted the defect. Until 2026-09-08 this said the pantry
    # received 96 kg, and the pantry does not serve same day, and this offer has
    # to be gone the next day. The test was green and the product was wrong,
    # which is the worst combination available and the reason the regression
    # suite now pins the rule rather than the numbers.
    assert "Omonoia Soup Kitchen: 96.0 kg" in text
    assert "Elpida Night Shelter: 20.0 kg" in text
    assert "Kypseli Food Pantry: 96.0 kg" not in text


def test_the_message_carries_who_was_skipped_and_why_which_is_the_whole_point():
    """A message listing only the winners is the group chat with extra steps.

    The reason somebody was skipped is the thing that stops the phone call, and a
    coordinator who has to open a website to find it has not been helped.
    """
    text = the_message(decision_screen("offer-4471"))

    assert "Not this time, and why:" in text
    # Elpida is off this list on purpose now. It serves same day, so it is one
    # of the two organisations this offer may go to, and it receives 20 kg. The
    # previous version of this test asserted it was skipped and passed anyway
    # once it started receiving, because the assertion was "the name appears
    # somewhere in the message" and the name appears in the shares.
    for name in ("Anemos Community Library", "Kypseli Food Pantry", "Second Chance School"):
        assert name in text, f"{name} was skipped and the message does not say so"
    assert "same day" in text, (
        "a name with no reason beside it is the phone call again, and the reason "
        "these three are skipped is the same-day rule"
    )


def test_the_message_says_nothing_is_published_yet():
    """Otherwise it reads as a decision taken rather than one waiting on a person."""
    text = the_message(decision_screen("offer-4471"))

    assert "Nobody has published anything yet" in text
    assert "read it and approve" in text


def test_the_message_never_carries_a_person():
    """It leaves this product for a chat we do not control, so it is a record too.

    The gate refuses a published record carrying a person. A message that leaves
    by a different door has to clear the same bar, and this asserts it with the
    gate's own patterns rather than a second set that could drift.
    """
    from merismos.gate import _EMAIL, _NATIONAL_ID, _PHONE, _STREET

    text = the_message(decision_screen("offer-4471"))

    for pattern, what in (
        (_EMAIL, "an email address"),
        (_PHONE, "a phone number"),
        (_STREET, "a street address"),
        (_NATIONAL_ID, "a national identifier"),
    ):
        match = pattern.search(text)
        assert match is None, f"the message carries {what}: {match.group(0)!r}"


def test_a_refused_offer_offers_no_message_because_there_is_nothing_to_send():
    page = decision_screen("offer-4477")

    assert "Refused, and here is why" in page
    assert "To send in the group chat" not in page


def test_the_screen_still_loads_no_script():
    """The reason there is no copy button. The guarantee is worth more."""
    page = decision_screen("offer-4471")

    for forbidden in ("<script", "onclick", "navigator.clipboard"):
        assert forbidden not in page

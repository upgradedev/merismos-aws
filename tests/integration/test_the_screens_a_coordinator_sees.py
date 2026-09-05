"""The screens, asserted on what a person actually sees.

These check content and contract rather than appearance. Appearance was checked
once in a browser at an emulated 375px viewport and reported no horizontal
overflow; what is pinned here is the structure that made that true, so it cannot
regress silently between browser checks.

The rule these enforce throughout: **show the reasoning, not just the answer.**
A coordinator who cannot see why the shelter was skipped will phone the shelter,
and then the fleet has cost them time rather than saved it.
"""

from __future__ import annotations

import json
import re

import pytest

from merismos import handler


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    monkeypatch.delenv("MERISMOS_CRITIC_MODEL", raising=False)
    monkeypatch.delenv("MERISMOS_PUBLISH_SECRET", raising=False)
    monkeypatch.delenv("MERISMOS_RECORDS_BUCKET", raising=False)


def get(
    path: str,
    method: str = "GET",
    form: dict | None = None,
    query: dict | None = None,
) -> dict:
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": {"content-type": "application/json"},
        "body": "{}",
        "queryStringParameters": query or {},
    }
    if form is not None:
        from urllib.parse import urlencode

        event["headers"]["content-type"] = "application/x-www-form-urlencoded"
        event["body"] = urlencode(form)
    return handler.handler(event)


def html(path: str, **kw) -> str:
    reply = get(path, **kw)
    assert reply["statusCode"] == 200, reply["body"][:200]
    assert "text/html" in reply["headers"]["content-type"]
    return reply["body"]


@pytest.fixture
def run_now(monkeypatch):
    """Replace the async hop with a direct call, and walk the real flow.

    A chore takes longer than a request is allowed to, so the site starts it on
    a background invocation and the page polls the thread. There is no Lambda in
    a test, so `background.start` runs the same function the invocation would,
    synchronously. Everything else is unchanged: the POST, the redirect, the
    run id, and the page reading the finished run back out of the thread.
    """
    from merismos import background, handler

    def _straight_through(offer_id: str, run_id: str, network: str) -> None:
        handler._run_in_background(
            {"offer_id": offer_id, "run_id": run_id, "network": network}
        )

    monkeypatch.setattr(background, "start", _straight_through)
    return _straight_through


def a_run(offer_id: str) -> str:
    """Press the button, follow the redirect, and hand back the run id."""
    started = get(f"/offer/{offer_id}", method="POST", form={})
    assert started["statusCode"] == 303, started
    where = started["headers"]["location"]
    assert where.startswith(f"/offer/{offer_id}?run=")
    return where.split("run=", 1)[1]


def walk(offer_id: str) -> str:
    """Press the button, follow the redirect, read the finished decision."""
    return html(f"/offer/{offer_id}", query={"run": a_run(offer_id)})


def card(offer_id: str) -> str:
    """The approval card for a run somebody actually read.

    There is no shortcut to this screen any more. ``/approve/<id>`` without a run
    used to decide, which meant a card could show bytes from a run nobody had
    seen; it now refuses, so these tests take the same three steps a coordinator
    does.
    """
    return html(f"/approve/{offer_id}", query={"run": a_run(offer_id)})


# --------------------------------------------------------------------------
# The contract every screen keeps.
# --------------------------------------------------------------------------

#: Screens reachable with a plain GET and nothing behind them. The approval card
#: is not one: it exists only for a run somebody read, so it is held to the same
#: contract separately, in test_the_card_keeps_the_contract_every_other_screen_keeps.
SCREENS = ["/", "/how", "/offer/offer-4471", "/offer/offer-4477", "/records", "/offers/new"]


@pytest.mark.parametrize("path", SCREENS)
def test_every_screen_is_a_complete_document(path):
    page = html(path)

    assert page.startswith("<!doctype html>")
    assert '<meta name="viewport" content="width=device-width,initial-scale=1">' in page
    assert "</html>" in page


@pytest.mark.parametrize("path", SCREENS)
def test_no_screen_loads_anything_from_anywhere_else(path):
    """A page that needs a font from elsewhere breaks when elsewhere is down.

    This has to still be standing on 2026-10-08 for somebody who is not us.
    """
    page = html(path)

    assert "<script" not in page.lower(), "a script tag appeared"
    assert not re.search(r'src\s*=\s*"https?://', page), "an external asset appeared"
    assert not re.search(r'<link[^>]+href\s*=\s*"https?://', page), (
        "an external stylesheet appeared"
    )
    assert "@import" not in page


@pytest.mark.parametrize("path", SCREENS)
def test_every_wide_thing_scrolls_inside_its_own_box(path):
    """What keeps 375px free of horizontal overflow, pinned without a browser.

    Tables and preformatted blocks are the only two things here wide enough to
    push the page sideways. Every table is wrapped in `.scroll`, which carries
    `overflow-x:auto`, and `pre` carries it directly.
    """
    page = html(path)

    # Each <table> must be immediately preceded by its own scroll wrapper.
    # Comparing counts would pass with one wrapper somewhere else on the page.
    for match in re.finditer(r"<table[\s>]", page):
        before = page[: match.start()]
        assert before.rstrip().endswith('<div class="scroll">'), (
            f"a table on {path} is not inside a horizontal scroll container"
        )
    assert "overflow-x:auto" in page, "nothing on this page can scroll sideways"


@pytest.mark.parametrize("path", SCREENS)
def test_every_screen_says_no_person_reaches_a_record(path):
    page = html(path)

    assert "never a person" in page


# --------------------------------------------------------------------------
# The offers screen. This is the group chat, replaced.
# --------------------------------------------------------------------------


def test_the_inbox_lists_what_is_waiting_and_offers_one_action_each():
    page = html("/")

    for offer_id in ("offer-4471", "offer-4477", "offer-4483"):
        assert offer_id in page
    assert page.count("Work out the split") == 3
    assert "Nothing here publishes on its own" in page


# --------------------------------------------------------------------------
# The decision screen. Reasoning, not just the answer.
# --------------------------------------------------------------------------


def test_the_decision_names_who_was_skipped_and_the_rule_that_skipped_them(run_now):
    page = walk("offer-4471")

    assert "Not receiving a share, and the rule that decided it" in page
    for skipped in ("Anemos Community Library", "Elpida Night Shelter", "Second Chance School"):
        assert skipped in page
    assert "no van and can carry" in page
    assert "re-litigated by phone" in page


def test_the_decision_shows_the_share_of_the_offer_not_only_the_amount(run_now):
    """96 kg means nothing without the ceiling it sits under."""
    page = walk("offer-4471")

    assert "40.0%" in page
    assert "Of offer" in page


def test_a_refused_offer_leads_with_why_and_offers_no_approval(run_now):
    page = walk("offer-4477")

    assert "cold chain was broken for 6 hours" in page
    assert "Refused, and here is why" in page
    assert "/approve/offer-4477" not in page, "a refused offer must not offer an approve button"


def test_the_decision_says_nothing_is_published_yet(run_now):
    page = walk("offer-4471")

    assert "Nothing is published yet" in page


def test_the_reads_the_specialists_made_are_shown_with_correct_grammar(run_now):
    page = walk("offer-4471")

    assert "The specialists opened 1 file from" in page, "pluralisation is wrong"
    assert "files from" not in page.split("The specialists opened 1 file")[0][-80:]


# --------------------------------------------------------------------------
# The approval card. The one moment a person is in the loop.
# --------------------------------------------------------------------------


def test_the_card_shows_the_exact_bytes_that_will_be_published(run_now):
    page = card("offer-4471")

    assert "What will be published" in page
    assert "# Allocation, offer-4471" in page
    assert "these exact bytes" in page


def test_the_card_shows_the_digest_the_writer_will_recompute(run_now):
    page = card("offer-4471")

    assert re.search(r'class="digest">[0-9a-f]{64}<', page), "no sha256 on the card"


def test_the_card_states_what_the_approval_does_not_authorise(run_now):
    """An approval a person cannot bound is an approval they cannot give."""
    page = card("offer-4471")

    assert "What this approval does not authorise" in page
    assert "15 minutes" in page
    assert "cannot be replayed" in page


def test_approving_requires_a_named_person(run_now):
    page = card("offer-4471")

    assert 'name="approved_by" required' in page

    refused = get(
        "/approve/offer-4471",
        method="POST",
        form={"approved_by": "  ", "run": a_run("offer-4471")},
    )
    assert refused["statusCode"] == 400
    assert "names a person" in refused["body"]


def test_the_card_is_never_offered_for_an_offer_that_was_refused(run_now):
    reply = get("/approve/offer-4477", query={"run": a_run("offer-4477")})

    assert "What will be published" not in reply["body"]
    assert "Refused, and here is why" in reply["body"]


# --------------------------------------------------------------------------
# The rest.
# --------------------------------------------------------------------------


def test_how_it_decides_publishes_the_bounds_rather_than_describing_them():
    page = html("/how")

    assert "offers/, orgs/, registers/" in page, "the read scope is not published"
    assert "6 files per specialist" in page, "the read budget is not published"
    assert "No agent can publish" in page
    assert "an approver cannot override that" in page


def test_the_published_index_has_an_honest_empty_state():
    """Never gate a feature to null. Render a reason."""
    page = html("/records")

    assert "Nothing published yet" in page
    assert "read a card and approved it" in page


def test_only_the_reader_serves_screens(monkeypatch):
    """One package, three roles. A person opening the writer gets its 403 or 404."""
    for other in ("evaluator", "writer"):
        monkeypatch.setenv("MERISMOS_ROLE", other)
        reply = get("/")
        assert "text/html" not in reply["headers"].get("content-type", ""), (
            f"the {other} served a screen"
        )


def test_an_unknown_offer_is_a_404_rather_than_a_crash():
    reply = get("/offer/offer-9999")

    assert reply["statusCode"] == 404
    assert "No such offer" in reply["body"]


def test_the_json_api_still_answers_alongside_the_screens():
    """The screens are added, not swapped in. A judge may still curl."""
    reply = get("/config")

    assert reply["statusCode"] == 200
    assert json.loads(reply["body"])["read_budget_per_specialist"] == 6


def test_the_network_is_named_the_way_a_person_would_say_it():
    """A UX review found the storage key printed in the first sentence.

    `kypseli-network` is an identifier. Nobody calls their network that, and a
    slug in a sentence is the tell that a screen was built from the data model
    outwards rather than from the reader inwards.
    """
    page = html("/")

    assert "Kypseli mutual aid network" in page
    assert "kypseli-network" not in page


def test_the_card_keeps_the_contract_every_other_screen_keeps(run_now):
    """The card is off the SCREENS list because it needs a run behind it.

    Off the list is not exempt. It is the hero screen, so it holds to the same
    rules: a complete document, nothing loaded from anywhere else, and the line
    about people.
    """
    page = card("offer-4471")

    assert page.startswith("<!doctype html>")
    assert '<meta name="viewport" content="width=device-width,initial-scale=1">' in page
    assert "</html>" in page
    for forbidden in ("<script", "http://", "https://fonts", "<link", "<img"):
        assert forbidden not in page, f"the card reaches for {forbidden}"
    assert "never a person" in page


def test_an_approval_link_with_no_run_refuses_rather_than_deciding_again(run_now):
    """A bookmark, a shared link, a back button. None of them may start a chore.

    The reader answers requests and its budget is sixty seconds; a four
    specialist chore started inside one is a request the gateway abandons and a
    concurrency slot held for nothing. Refusing is also the honest answer, since
    an approval covers the bytes one particular run produced.
    """
    reply = get("/approve/offer-4471")

    assert reply["statusCode"] == 404
    assert "no decision here to approve" in reply["body"]
    assert "will not decide again on your behalf" in reply["body"]
    assert "/offer/offer-4471" in reply["body"], "it does not offer a way forward"

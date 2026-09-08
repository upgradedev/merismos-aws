"""A published record that turns out to be wrong is corrected, not overwritten.

offer-4471 was published on 2026-09-05 giving 96 kg to an organisation a
food-safety rule forbade, and it is still at a public address. The repair for
that is not to write the right bytes to the same key. Somebody has read the old
one. Somebody may have driven a van because of it. A coordinator who acted on it
has to be able to see what they acted on, and a funder auditing the network in
March has to be able to see that the network noticed and said so.

So a correction takes the next key in the series, opens by naming what it
replaces, and leaves the original exactly where it is.
"""

from __future__ import annotations

import pytest

from merismos.fleet import record_key, superseded_by_this_run


def _published(*keys: str) -> list[dict]:
    return [{"key": k} for k in keys]


def test_the_first_record_for_an_offer_takes_the_plain_key():
    assert record_key("offer-4471", []) == "records/offer-4471.md"


def test_a_second_record_for_the_same_offer_never_reuses_the_key():
    key = record_key("offer-4471", _published("records/offer-4471.md"))

    assert key == "records/offer-4471-c2.md"
    assert key != "records/offer-4471.md", (
        "a correction published to the same address destroys the evidence of "
        "what the network told people the first time"
    )


def test_corrections_keep_counting_rather_than_colliding():
    published = _published("records/offer-4471.md", "records/offer-4471-c2.md")

    assert record_key("offer-4471", published) == "records/offer-4471-c3.md"


def test_another_offer_is_unaffected_by_this_offers_corrections():
    """The series is per offer, and a shared counter would be a silent bug."""
    published = _published("records/offer-4471.md", "records/offer-4471-c2.md")

    assert record_key("offer-4483", published) == "records/offer-4483.md"


def test_the_record_being_corrected_is_named_rather_than_implied():
    published = _published("records/offer-4471.md", "records/offer-4471-c2.md")

    assert superseded_by_this_run("offer-4471", published) == "records/offer-4471-c2.md"
    assert superseded_by_this_run("offer-4483", published) == ""


@pytest.mark.parametrize("prior", [(), ("records/offer-4471.md",)])
def test_a_correction_says_so_at_the_top_and_a_first_record_does_not(prior, monkeypatch):
    """The banner is the first thing on the page or it is not there at all.

    Somebody arriving from a link to the superseded record needs to know before
    they read a table of shares.
    """
    import json

    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_MODEL", "none")

    from merismos.corpus import LocalCorpus
    from merismos.corpus import orgs as load_orgs
    from merismos.fleet import _draft

    corpus = LocalCorpus()
    offer = json.loads(corpus.read("offers/offer-4471.json"))
    orgs = load_orgs(corpus)
    draft = _draft(offer, orgs, [], corpus, published=_published(*prior))

    banner = "This corrects an earlier record"
    if prior:
        assert banner in draft.body
        assert "records/offer-4471.md" in draft.body
        assert draft.body.index(banner) < draft.body.index("## Shares"), (
            "the correction notice is below the shares, so a reader can act on "
            "the table before learning the record replaces another one"
        )
    else:
        assert banner not in draft.body, (
            "a first record claiming to correct something would make every "
            "record look like a repair"
        )

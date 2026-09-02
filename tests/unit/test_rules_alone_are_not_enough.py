"""The case that decides whether this is agentic or a rules engine with a model.

Offer 4483 is a wholesaler clearance. Its declared fields say category
``ambient``, ``allergens: []``, long dated, nothing unusual. Every deterministic
pattern in this repository passes it, and it is correct to: the donor described
the pallet honestly and has no idea which member of this network runs a recovery
programme.

The manifest says each of the forty gift hampers holds a small pork salami and a
375ml bottle of red wine, and that some biscuit lines contain hazelnut. Three of
the five members cannot accept that, absolutely, for reasons about the people
they serve.

Both halves are asserted here, and neither needs a credential. If the pattern
half ever starts catching it, the README's comparison stops being true and this
test says so before a judge does.
"""

from __future__ import annotations

import pytest

from merismos.corpus import LocalCorpus
from merismos.corpus import orgs as read_orgs
from merismos.fleet import premises


@pytest.fixture(scope="module")
def corpus() -> LocalCorpus:
    return LocalCorpus()


@pytest.fixture(scope="module")
def offer_4483(corpus: LocalCorpus) -> dict:
    import json

    return json.loads(corpus.read("offers/offer-4483.json"))


def test_the_offer_declares_nothing_that_would_exclude_anyone(offer_4483):
    """The premise of the comparison, checked rather than assumed.

    If somebody later adds ``alcohol`` to the offer's allergens, the comparison
    below becomes trivially true and stops being evidence. So the fixture's own
    innocence is asserted first.
    """
    assert offer_4483["allergens"] == []
    assert offer_4483["category"] == "ambient"
    text = " ".join(str(v).lower() for v in offer_4483.values())
    for word in ("wine", "alcohol", "pork", "salami", "hazelnut", "nut"):
        assert word not in text, (
            f"the offer's own fields mention {word!r}, so a pattern could catch "
            f"it and this comparison would prove nothing"
        )


def test_reading_only_the_declared_fields_excludes_nobody(offer_4483, corpus):
    """The deterministic answer, and it ships alcohol to a recovery shelter."""
    envelope = premises(offer_4483, read_orgs(corpus), manifest_text="")

    assert envelope.status.value == "ok"
    assert envelope.findings == ()
    assert envelope.meta["blocked_for"] == []


def test_reading_the_manifest_excludes_the_three_who_cannot_accept_it(
    offer_4483, corpus
):
    """The answer an agent that chose to open the manifest reaches."""
    manifest = corpus.read("offers/manifests/4483.md")

    envelope = premises(offer_4483, read_orgs(corpus), manifest_text=manifest)

    assert envelope.status.value == "needs_changes"
    assert envelope.meta["blocked_for"] == [
        "Anemos Community Library",
        "Elpida Night Shelter",
        "Second Chance School",
    ]
    raised = {f.evidence for f in envelope.findings}
    assert raised == {"wine", "pork", "hazelnut"}
    assert all(f.severity == "high" for f in envelope.findings)


def test_the_three_excluded_are_excluded_for_stated_reasons(corpus):
    """Each exclusion traces to a constraint in that organisation's own record."""
    by_name = {o["name"]: o for o in read_orgs(corpus)}

    assert "alcohol_free_premises" in by_name["Elpida Night Shelter"]["premises_constraints"]
    assert "alcohol_free_premises" in by_name["Second Chance School"]["premises_constraints"]
    assert "no_pork" in by_name["Second Chance School"]["premises_constraints"]
    assert "nut_free" in by_name["Anemos Community Library"]["premises_constraints"]

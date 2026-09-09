"""The manifest floor matched inside other words, and a gift hamper was pork.

`_MANIFEST_TOKENS["pork"]` contains "ham", and the match was a substring, so
**every manifest mentioning a gift hamper was flagged as pork.** `offer-4483`,
the example this project uses to argue that rules alone are not enough, is about
seasonal gift hampers. Its real pork salami masked the false positive by firing
for the right organisation for the wrong reason.

The other half of this file is a fix that was **reverted**, and it is kept here
because the reason is worth more than the change would have been.

"Contains alcohol" in as many words blocks nobody: the category lists do not
contain the words they are named after. Adding them was tried. `offer-4471`'s
manifest reads "nothing here is alcohol", a bare category word matches the
sentence that denies it, and the floor excluded Elpida Night Shelter from an
offer it was one of only two organisations allowed to receive.

Prose about a category is mostly prose denying it. Negation handling would close
the gap and is the beginning of the rules engine this list exists not to be.
"""

from __future__ import annotations

import pytest

from merismos.corpus import LocalCorpus
from merismos.corpus import orgs as load_orgs
from merismos.fleet import _MANIFEST_TOKENS, premises


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")


def blocked(manifest: str) -> list[str]:
    envelope = premises({"allergens": [], "title": "x"}, load_orgs(LocalCorpus()), manifest)
    return sorted(envelope.meta.get("blocked_for", []))


# --------------------------------------------------------------------------
# The fix that stays.
# --------------------------------------------------------------------------


def test_a_gift_hamper_is_not_pork():
    """"ham" is inside "hamper", and the flagship offer is about hampers."""
    assert blocked("Each seasonal gift hamper is boxed.") == []


@pytest.mark.parametrize(
    "manifest", ["Donated by a Birmingham supplier.", "Shampoo and soap, non-food."]
)
def test_other_words_containing_a_token_do_not_fire(manifest):
    assert blocked(manifest) == []


def test_a_hamper_that_really_does_contain_pork_still_fires():
    """The boundary fix must not cost the true positive it sits next to."""
    assert "Second Chance School" in blocked("Gift hamper with pork salami.")


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ("A bottle of wine.", 3),
        ("Two wines per crate.", 3),
        ("Contains almonds.", 1),
        ("Hazelnut praline.", 1),
    ],
)
def test_the_tokens_still_match_including_their_plurals(manifest, expected):
    assert len(blocked(manifest)) == expected


# --------------------------------------------------------------------------
# The fix that was reverted, and why.
# --------------------------------------------------------------------------


def test_the_bare_category_words_are_deliberately_absent():
    """A gap, recorded on purpose, with the reason in the next test."""
    assert "alcohol" not in _MANIFEST_TOKENS["alcohol"]
    assert "nut" not in _MANIFEST_TOKENS["nut"]
    assert "pork" in _MANIFEST_TOKENS["pork"], (
        "pork names itself and can, because nobody writes 'no pork' in a manifest "
        "the way they write 'nothing here is alcohol'"
    )


def test_a_manifest_denying_a_category_does_not_trigger_it():
    """The reason the bare word was reverted, pinned so it is not re-added.

    offer-4471's own manifest says "nothing here is alcohol". With "alcohol" in
    its own token list this excluded Elpida Night Shelter, one of only two
    organisations allowed to receive that offer.
    """
    assert blocked("Nothing here needs a fridge and nothing here is alcohol.") == []
    assert blocked("Nut free premises. Contains no nuts.") == []


def test_the_flagship_offers_manifest_still_excludes_nobody_on_this_floor():
    """Read from the corpus rather than retyped, so it moves when the file does."""
    manifest = LocalCorpus().read("offers/manifests/4471.md")

    assert blocked(manifest) == []

"""The catalogue said what each specialist "may read". Nothing enforced it.

`/how` headed that column "What they may read", which is the language of
permission. ``DEFAULT_SCOPE`` is ``("offers/", "orgs/", "registers/")`` and every
specialist holds all of it: the bound is per run, not per specialist.

**Enforcing the declared lists would be wrong as well as risky.** They are
narrower than what a specialist legitimately opens. On the live run watched on
2026-09-09 the premises specialist opened ``offers/offer-4471.json``, which is
not in its list, and refusing that read would have broken a correct run in order
to make a sentence true.

So the sentence was corrected rather than the mechanism. The distinction between
a bound that is enforced and a description that reads like one is this project's
whole argument, and the page making that argument was making it wrong.
"""

from __future__ import annotations

import re

import pytest

from merismos import handler
from merismos.fleet import catalogue
from merismos.tools import DEFAULT_SCOPE


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_MODEL", "none")


def how_page() -> str:
    reply = handler.handler(
        {
            "requestContext": {"http": {"method": "GET", "path": "/how"}},
            "headers": {"content-type": "application/json"},
            "body": "{}",
            "queryStringParameters": {},
        }
    )
    assert reply["statusCode"] == 200
    body = reply["body"]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body[body.index("</style>") :]))


def test_the_page_does_not_describe_the_expectation_as_a_permission():
    text = how_page()

    assert "expected to open" in text
    assert "may read" not in text, (
        "the column reads as a grant, and every specialist holds the whole scope"
    )


def test_the_page_says_the_enforced_bound_is_per_run_not_per_specialist():
    text = how_page()

    assert "per run, not per specialist" in text
    assert "refused by the tool rather than discouraged by a prompt" in text


def test_the_catalogue_says_so_too_for_anybody_reading_the_json():
    """A judge reading /catalog should not have to open /how to learn this."""
    note = catalogue()["reads_is_expected_not_enforced"]

    assert "expected to consult" in note
    assert "per run rather than per specialist" in note
    for prefix in DEFAULT_SCOPE:
        assert prefix in note, f"the enforced bound does not name {prefix}"


def test_the_specialist_entries_are_unchanged():
    """Correcting the claim must not remove the useful information."""
    specialists = catalogue()["specialists"]

    assert set(specialists) == {"food-safety", "capacity", "equity", "premises"}
    for name, spec in specialists.items():
        assert spec["reads"], f"{name} lost the list of what it consults"
        assert spec["why"], f"{name} lost its reason"


def test_the_enforced_scope_really_is_shared_by_every_specialist():
    """The fact the wording now admits, asserted rather than taken on trust."""
    from merismos.corpus import LocalCorpus
    from merismos.tools import Toolbox

    boxes = [Toolbox(corpus=LocalCorpus()) for _ in range(4)]

    assert {tuple(b.log.scope) for b in boxes} == {tuple(DEFAULT_SCOPE)}, (
        "the scopes differ per specialist, which would make the old wording true "
        "and this correction wrong"
    )

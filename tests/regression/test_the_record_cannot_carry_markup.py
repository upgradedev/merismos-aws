"""A typed offer title became markup in a permanent public record.

`<img src=x onerror=alert(1)>` typed into the intake form's title arrived in the
published record verbatim.

**This was not a live XSS and calling it one would be the overstatement this
project refuses.** Our own surfaces were checked first and are safe: the approval
card renders the bytes as ``<pre>{_e(...)}</pre>``, the record screen does the
same, and S3 serves the object as ``text/markdown``, which a browser displays
rather than executes.

What is true is that a coordinator's typed text became markup in a permanent
public document, and anything that renders that markdown renders it as markup.
The register says the record carries organisation names, categories, quantities
and the reason for each share. It does not say "and whatever HTML was in the
title".
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile

import pytest

from merismos import intake
from merismos.corpus import LocalCorpus
from merismos.fleet import new_run_id, run_chore, subject_for_offer
from merismos.ledger import InMemoryLedger, Thread

TAG = "<img src=x onerror=alert(1)>"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_MODEL", "none")


@pytest.fixture
def corpus() -> LocalCorpus:
    root = pathlib.Path(tempfile.mkdtemp()) / "corpus"
    shutil.copytree("corpus", root)
    return LocalCorpus(root)


def record_for(corpus: LocalCorpus, **fields) -> str:
    form = {
        "title": "End of day bread",
        "donor": "A bakery",
        "quantity": "10",
        "unit": "kg",
        "category": "ambient",
        "collection_date": "2026-09-14",
        "note": "Collect by 19:00",
        **fields,
    }
    offer = intake.offer_from_form(form, "offer-9001")
    thread = Thread(
        ledger=InMemoryLedger(),
        subject=subject_for_offer("kypseli-network", offer),
        run_id=new_run_id(),
    )
    return run_chore(corpus, offer, thread, network="kypseli-network").draft.body


@pytest.mark.parametrize("field", ["title", "donor"])
def test_a_tag_typed_into_the_form_does_not_reach_the_record_as_a_tag(corpus, field):
    body = record_for(corpus, **{field: TAG})

    assert TAG not in body, f"{field} carried raw markup into a permanent public record"
    assert "&lt;img" in body, "the value was dropped rather than made inert"


def test_the_text_is_still_readable_rather_than_removed(corpus):
    """Neutralising is not censoring. A reader must still see what was typed."""
    body = record_for(corpus, title=TAG)

    assert "img src=x onerror=alert(1)" in body
    assert "&lt;img src=x onerror=alert(1)&gt;" in body


def test_an_ordinary_title_is_untouched(corpus):
    body = record_for(corpus, title="End of day bread and vegetables")

    assert "End of day bread and vegetables" in body
    assert "&lt;" not in body.split("## Shares")[0]


def test_the_organisation_names_and_reasons_are_inert_too(corpus):
    """A reason can carry a model's own words, and an org edits its own record."""
    from merismos.fleet import _inert

    assert _inert("<b>Omonoia</b>") == "&lt;b&gt;Omonoia&lt;/b&gt;"
    assert _inert(None) == ""
    assert _inert(240) == "240"


def test_our_own_screens_were_never_the_problem_and_still_are_not(corpus):
    """Stated as a test so the scope of the fix cannot drift in the retelling."""
    from merismos import web

    page = web.one_record("records/offer-9001.md", TAG, {"approved_by": "a person"})

    assert TAG not in page
    assert "&lt;img" in page

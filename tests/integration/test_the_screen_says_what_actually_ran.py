"""A failed model must not read as a normal agentic run.

The demo gained this a day ago: a banner naming the path, and a red NOT REACHED
when the specialists could not reach their analyst. The web screens, which are
what a judge and a coordinator actually open, showed the same page either way.

``run_chore`` degrades to the deterministic rules when an analyst is unreachable
and records a ``model-unreachable`` finding. That is the right behaviour and it
is not the same as telling anybody: one finding among twenty in a details list is
not a statement on the page.

The second half these pin is the scope of the credit. The cold chain arithmetic,
the date comparison, the ceiling and the premises matching were deterministic
before any model existed here, and presenting them as an agent's reasoning is the
easiest available lie in a product like this one.
"""

from __future__ import annotations

import pytest

from merismos import web
from merismos.envelope import Envelope, Finding, Status


class FakeDraft:
    body = "# Allocation"
    allocations = [{"org": "Omonoia Soup Kitchen", "quantity": 96.0, "reason": "x"}]
    must_not_receive: frozenset[str] = frozenset()
    barred_because: dict[str, str] = {}


class FakeResult:
    outcome = "awaiting_approval"
    note = "waiting"
    draft = FakeDraft()
    verdict = None
    run_id = "run-1"
    read_log: dict = {"scope": [], "budget": 6, "spent": 0, "remaining": 6, "reads": []}
    deferrals: list = []
    woken: list = ["premises"]
    skipped: list = []
    approval = None

    def __init__(self, envelopes):
        self.envelopes = envelopes


OFFER = {"id": "offer-4471", "title": "Bread", "donor": "A bakery", "quantity": 240, "unit": "kg"}


def screen(envelopes) -> str:
    return web.decision(FakeResult(envelopes), OFFER, "kypseli-network")


def an_envelope(**meta) -> Envelope:
    return Envelope(specialist="premises", status=Status.OK, meta=meta)


def test_a_run_the_model_never_reached_says_so_on_the_page():
    unreachable = Envelope(
        specialist="premises",
        status=Status.NEEDS_CHANGES,
        reason="the model read did not complete",
        findings=(
            Finding(
                check="model-unreachable",
                severity="medium",
                detail="premises could not be widened by a model read",
                evidence="",
            ),
        ),
    )

    html = screen([unreachable])

    assert "No model read this offer" in html
    assert "note stop" in html, "the notice is not styled as a stop, so it reads as a detail"
    assert "deterministic rules alone" in html


def test_the_page_says_what_a_deterministic_run_could_not_have_caught():
    """Naming the loss is the difference between a notice and an excuse."""
    unreachable = Envelope(
        specialist="premises",
        status=Status.NEEDS_CHANGES,
        reason="the model read did not complete",
        findings=(
            Finding(check="model-unreachable", severity="medium", detail="x", evidence=""),
        ),
    )

    html = screen([unreachable])

    assert "opened the manifest" in html


def test_a_run_with_no_model_configured_is_distinguished_from_a_failed_one():
    """Three paths, three sentences. Two of them are not the same thing."""
    html = screen([an_envelope()])

    assert "Deterministic rules only" in html
    assert "No model read this offer" not in html
    assert "note stop" not in html, "no model configured is not a failure"


def test_a_real_run_names_the_model_and_what_it_chose_to_open():
    html = screen(
        [an_envelope(model="eu.anthropic.claude-opus-5", paths_opened=["offers/manifests/4471.md"])]
    )

    assert "eu.anthropic.claude-opus-5" in html
    assert "offers/manifests/4471.md" in html
    assert "chose to open" in html


@pytest.mark.parametrize(
    "envelopes",
    [
        [an_envelope(model="eu.anthropic.claude-opus-5")],
        [an_envelope()],
    ],
)
def test_the_deterministic_rules_are_never_credited_to_the_model(envelopes):
    """Whatever ran, the ceiling and the cold chain are rules and say so."""
    html = screen(envelopes)

    assert "deterministic" in html.lower()
    assert "40% ceiling" in html


def test_a_model_that_opened_nothing_does_not_imply_it_read_the_filing():
    html = screen([an_envelope(model="eu.anthropic.claude-opus-5", paths_opened=[])])

    assert "opened nothing beyond the declared fields" in html

"""The live waiting screen said "6 of 4 answered", then "8 of 4".

Found by watching the first real model run on the deployed fleet, twenty minutes
after the runner was given a model for the first time. It is the screen a judge
watches for the whole four minutes a chore takes, and it was counting to eight
out of four.

``progress`` counted ``specialist.answered`` entries. With a model configured
each specialist appends twice: its deterministic answer, and a second entry from
``_union_model`` recording what the model chose to open. Both are worth keeping
and only one of them is a specialist.

**This could not appear before today.** The deployed runner had
``MERISMOS_MODEL=none``, so every specialist produced exactly one entry, and the
offline suite runs the same way by default. Fixing the model wiring is what
surfaced it, which is the ordinary way a latent defect arrives.
"""

from __future__ import annotations

import pytest

from merismos.background import progress

SPECIALISTS = ("food-safety", "capacity", "equity", "premises")


class Entry:
    def __init__(self, kind: str, body: dict | None = None):
        self.kind = kind
        self.body = body or {}


def deterministic_run() -> list[Entry]:
    return [Entry("run.started"), Entry("fleet.dispatch")] + [
        Entry("specialist.answered", {"specialist": name}) for name in SPECIALISTS
    ]


def model_run() -> list[Entry]:
    """What a run with an analyst actually writes: two entries per specialist."""
    return deterministic_run() + [
        Entry("specialist.answered", {"specialist": name, "source": "model"})
        for name in SPECIALISTS
    ]


def test_a_model_run_does_not_report_more_specialists_than_there_are():
    """The defect, in the shape it appeared on screen."""
    assert progress(model_run())["specialists_answered"] == 4, (
        "the second entry each specialist writes when a model reads for it is "
        "being counted as another specialist, so the screen a judge watches for "
        "four minutes counts to eight out of four"
    )


def test_the_deterministic_run_is_unchanged():
    assert progress(deterministic_run())["specialists_answered"] == 4


def test_a_half_finished_model_run_counts_the_specialists_that_answered():
    """Mid-run is the whole point: the bar has to move, and move truthfully."""
    partial = [Entry("run.started")] + [
        Entry("specialist.answered", {"specialist": "food-safety"}),
        Entry("specialist.answered", {"specialist": "food-safety", "source": "model"}),
        Entry("specialist.answered", {"specialist": "capacity"}),
    ]

    assert progress(partial)["specialists_answered"] == 2


def test_an_entry_with_no_specialist_name_still_moves_the_bar():
    """A thread written by an older build must not freeze the screen at zero."""
    older = [Entry("run.started")] + [Entry("specialist.answered") for _ in range(3)]

    assert progress(older)["specialists_answered"] == 3


def test_names_and_anonymous_entries_are_added_rather_than_one_hiding_the_other():
    mixed = [
        Entry("specialist.answered", {"specialist": "premises"}),
        Entry("specialist.answered", {"specialist": "premises", "source": "model"}),
        Entry("specialist.answered"),
    ]

    assert progress(mixed)["specialists_answered"] == 2


@pytest.mark.parametrize("entries", [deterministic_run(), model_run()])
def test_the_rest_of_the_progress_report_is_untouched(entries):
    reported = progress(entries)

    assert reported["done"] is False
    assert reported["failed"] is False
    assert reported["stage"] == "the specialists are reading the filing"
    assert reported["entries"] == len(entries)

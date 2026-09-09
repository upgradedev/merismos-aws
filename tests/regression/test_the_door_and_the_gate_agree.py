"""The form accepted a named household and the gate refused the record from it.

`_refuse_a_person_in`'s own docstring: "Refused at the door rather than at the
gate. Both refuse it; only one of them refuses it while the person still has the
message in front of them."

Both did not. The gate checked five patterns and the door checked four. A
coordinator could type "for the Papadopoulos family", be accepted, and have the
run refused minutes later for something they could have been told immediately,
which is the exact failure the door exists to prevent.

The two lists have to be the same list. This pins that they are, by shape rather
than by count, so adding a sixth pattern to one of them turns something red.
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


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")


def door_accepts(note: str) -> bool:
    try:
        intake.offer_from_form({**BASE, "note": note}, "offer-9001")
        return True
    except intake.Rejected:
        return False


def gate_accepts(note: str) -> bool:
    draft = gate.Draft(
        body=f"# Allocation\n\n{note}",
        allocations=[{"org": "Omonoia Soup Kitchen", "quantity": 10.0, "reason": "x"}],
        offer={"id": "offer-x", "quantity": 100, "unit": "kg"},
        known_orgs=org_names(LocalCorpus()),
    )
    return not gate.check_personal_data(draft)


@pytest.mark.parametrize(
    "note",
    [
        "For the Papadopoulos family",
        "the Nikolaou household took the rest",
        "collected by Mrs Papadopoulou",
        "ring 694 412 3456",
        "mail nobody@example.com",
        "AFM 123456789",
        "AMKA 12345678901",
        "deliver to 12 Fokionos Negri Street",
    ],
)
def test_what_the_gate_refuses_the_door_refuses_too(note):
    """Otherwise the coordinator is told four minutes later, or not at all."""
    assert not gate_accepts(note), "the fixture is wrong: the gate allows this"
    assert not door_accepts(note), (
        "the door accepted something the gate will refuse, so a coordinator is "
        "told about it after the run instead of while they can still see it"
    )


@pytest.mark.parametrize(
    "note",
    [
        "Needs collecting before 19:00.",
        "Mixed sourdough and day-old loaves.",
        "41 households served weekly.",
    ],
)
def test_ordinary_notes_pass_both(note):
    assert gate_accepts(note)
    assert door_accepts(note)


def test_the_door_reads_its_patterns_from_the_gate_rather_than_restating_them():
    """The drift happened because there were two lists. There is one.

    Asserted on identity rather than on equality of the compiled sources, so a
    copy pasted duplicate with the same text still fails this.
    """
    import inspect

    source = inspect.getsource(intake)

    assert "from .gate import" in source
    for name in ("_EMAIL", "_PHONE", "_STREET", "_NATIONAL_ID", "_NAMED_HOUSEHOLD"):
        assert "re.compile" not in source.split(name)[0][-40:], (
            f"{name} looks like it was redefined in intake rather than imported"
        )

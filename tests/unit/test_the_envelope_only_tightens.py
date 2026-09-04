"""The envelope's construction rules, and the union that cannot loosen.

``union`` is where ADR-002 stops being a paragraph and becomes a function. A
model contributing through it can make the fleet more careful and cannot make it
less careful, and there is no branch to argue with because there is no branch.

The parametrised case below is the whole invariant: for every ordered pair of
statuses, the union is the stricter one. Asserting it pairwise rather than on
the three cases somebody thought of is what makes it an invariant.
"""

from __future__ import annotations

import itertools
import json

import pytest

from merismos.envelope import (
    Envelope,
    Finding,
    RefusalWithoutReason,
    Status,
    worst,
)

STRICTNESS = [Status.OK, Status.NEEDS_CHANGES, Status.ERROR, Status.BLOCKED]


def _envelope(status: Status, name: str = "premises", **kwargs) -> Envelope:
    reason = kwargs.pop("reason", "" if status is Status.OK else "a stated reason")
    return Envelope(specialist=name, status=status, reason=reason, **kwargs)


@pytest.mark.parametrize(("left", "right"), itertools.product(STRICTNESS, STRICTNESS))
def test_the_union_of_any_two_statuses_is_the_stricter_one(left, right):
    result = _envelope(left).union(_envelope(right))

    expected = max(left, right, key=STRICTNESS.index)
    assert result.status is expected


def test_findings_are_added_and_never_removed():
    first = _envelope(
        Status.NEEDS_CHANGES,
        findings=(Finding(check="rota", severity="medium", detail="went last time"),),
    )
    second = _envelope(
        Status.OK,
        reason="",
        findings=(Finding(check="transport", severity="medium", detail="no van"),),
    )

    merged = first.union(second)

    assert {f.check for f in merged.findings} == {"rota", "transport"}


def test_an_identical_finding_from_both_sides_is_not_duplicated():
    finding = Finding(check="rota", severity="medium", detail="went last time")
    merged = _envelope(Status.NEEDS_CHANGES, findings=(finding,)).union(
        _envelope(Status.NEEDS_CHANGES, findings=(finding,))
    )

    assert len(merged.findings) == 1


def test_two_specialists_agreeing_on_different_evidence_stay_two_findings():
    """Collapsing them would hide the corroboration, which is the useful part."""
    merged = _envelope(
        Status.NEEDS_CHANGES,
        findings=(Finding(check="rota", severity="medium", detail="d", evidence="a"),),
    ).union(
        _envelope(
            Status.NEEDS_CHANGES,
            findings=(Finding(check="rota", severity="medium", detail="d", evidence="b"),),
        )
    )

    assert len(merged.findings) == 2


def test_a_reason_that_exists_is_never_replaced_by_one_that_does_not():
    merged = _envelope(Status.BLOCKED, reason="the cold chain broke").union(
        _envelope(Status.OK, reason="")
    )

    assert merged.reason == "the cold chain broke"


def test_a_union_that_becomes_a_refusal_must_carry_a_reason():
    """Otherwise a model could refuse and name nothing, which stops work blindly."""
    with pytest.raises(RefusalWithoutReason):
        Envelope(specialist="premises", status=Status.OK).union(
            Envelope(specialist="premises", status=Status.BLOCKED, reason="   ")
        )


def test_two_different_specialists_cannot_be_unioned():
    with pytest.raises(ValueError):
        _envelope(Status.OK, name="capacity").union(_envelope(Status.OK, name="equity"))


def test_notes_and_meta_are_carried_across():
    merged = _envelope(Status.OK, reason="", notes="first", meta={"a": 1}).union(
        _envelope(Status.OK, reason="", notes="second", meta={"b": 2})
    )

    assert merged.notes == "first\nsecond"
    assert merged.meta == {"a": 1, "b": 2}


@pytest.mark.parametrize("status", [Status.NEEDS_CHANGES, Status.BLOCKED, Status.ERROR])
def test_a_refusal_without_a_reason_raises_at_construction(status):
    with pytest.raises(RefusalWithoutReason) as raised:
        Envelope(specialist="premises", status=status, reason="  ")

    assert "premises" in str(raised.value)


def test_an_ok_envelope_needs_no_reason():
    assert Envelope(specialist="premises", status=Status.OK).reason == ""


def test_an_envelope_names_the_specialist_that_produced_it():
    with pytest.raises(ValueError):
        Envelope(specialist="  ", status=Status.OK)


@pytest.mark.parametrize(
    ("check", "severity", "detail"),
    [
        ("  ", "high", "detail"),
        ("rota", "catastrophic", "detail"),
        ("rota", "high", "   "),
    ],
)
def test_a_malformed_finding_raises_rather_than_reaching_the_record(check, severity, detail):
    with pytest.raises(ValueError):
        Finding(check=check, severity=severity, detail=detail)


def test_only_blocked_stops_the_run_on_its_own():
    assert _envelope(Status.BLOCKED).blocks is True
    for status in (Status.OK, Status.NEEDS_CHANGES, Status.ERROR):
        assert _envelope(status).blocks is False


@pytest.mark.parametrize(
    "status", [Status.NEEDS_CHANGES, Status.BLOCKED, Status.ERROR]
)
def test_every_refusing_status_says_it_refuses(status):
    assert status.is_refusal is True


def test_ok_is_not_a_refusal():
    assert Status.OK.is_refusal is False


def test_the_worst_of_no_envelopes_is_ok():
    """An empty fleet is OK here, and the caller decides whether that was right.

    That decision lives in ``fleet.run_chore``: a run with nothing to allocate
    says so and stops, rather than manufacturing an empty draft for the gate.
    """
    assert worst([]) is Status.OK


def test_the_worst_of_several_is_the_strictest():
    assert worst([_envelope(Status.OK), _envelope(Status.BLOCKED)]) is Status.BLOCKED
    assert (
        worst([_envelope(Status.OK), _envelope(Status.NEEDS_CHANGES)])
        is Status.NEEDS_CHANGES
    )


def test_an_envelope_exports_as_readable_json():
    exported = _envelope(
        Status.BLOCKED,
        findings=(Finding(check="cold-chain", severity="high", detail="six hours"),),
    ).as_json()

    assert json.loads(exported)["status"] == "blocked"
    assert json.loads(exported)["findings"][0]["check"] == "cold-chain"
    assert "\n  " in exported

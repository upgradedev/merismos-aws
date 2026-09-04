"""What an unattended wake is allowed to do, and it is only one thing.

Waking is cheap and nobody is watching. So the wake path appends an escalation
to the thread and holds no credential that can publish, and this is asserted
against the whole set of entry kinds rather than against the two somebody
thought of. If a future change makes a wake propose a plan or mint an approval,
the assertion fails on the kind it wrote.
"""

from __future__ import annotations

import datetime as dt

import pytest

from merismos.deferral import (
    Deferral,
    NullScheduler,
    escalate,
    scheduler_from_env,
)
from merismos.ledger import InMemoryLedger, Thread

#: Kinds that mean something was published, proposed or authorised. A wake may
#: write none of them.
FORBIDDEN_TO_A_WAKE = {
    "plan.proposed",
    "approval.granted",
    "record.published",
}


@pytest.fixture
def thread() -> Thread:
    return Thread(ledger=InMemoryLedger(), subject="net:offers/ambient", run_id="run-1")


def test_a_wake_appends_an_escalation_and_nothing_else(thread):
    escalate(thread, deferral_id="d1", reason="the shelter never came back")

    kinds = {e.kind for e in thread.walk()}

    assert kinds == {"deferral.escalated"}
    assert not kinds & FORBIDDEN_TO_A_WAKE


def test_the_escalation_names_the_deferral_and_who_fired_it(thread):
    result = escalate(thread, deferral_id="d1", reason="expired", fired_by="schedule")

    entry = thread.walk()[0]
    assert entry.body["deferral_id"] == "d1"
    assert entry.body["fired_by"] == "schedule"
    assert result["escalated"] == "d1"
    assert "cannot publish" in result["note"]


def test_escalating_closes_the_deferral_so_it_does_not_fire_forever(thread):
    ledger = thread.ledger
    deferral_entry = thread.append("finding.deferred", reason="waiting on the shelter")

    assert len(ledger.open_deferrals("net:offers/ambient")) == 1

    escalate(thread, deferral_id=deferral_entry.entry_id, reason="expired")

    assert ledger.open_deferrals("net:offers/ambient") == []


# --------------------------------------------------------------------------
# The deferral itself.
# --------------------------------------------------------------------------


def _deferral(until: dt.datetime, scheduled: bool = False) -> Deferral:
    return Deferral(
        deferral_id="d1",
        subject="net:offers/ambient",
        run_id="run-1",
        reason="the shelter cannot confirm fridge space until Thursday",
        until=until,
        scheduled=scheduled,
    )


def test_a_deferral_reports_whether_a_timer_actually_backs_it():
    """``scheduled`` is the honest field. False means the calendar will not wake it."""
    parked = _deferral(dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc))

    assert parked.as_dict()["scheduled"] is False
    assert parked.as_dict()["until"].startswith("2026-09-10")


@pytest.mark.parametrize("naive", [True, False])
def test_expiry_compares_correctly_whether_or_not_a_timezone_is_carried(naive):
    """A naive value read back from a store must not compare as if it were local."""
    until = dt.datetime(2026, 9, 10, 6, 0, 0)
    if not naive:
        until = until.replace(tzinfo=dt.timezone.utc)
    parked = _deferral(until)

    before = dt.datetime(2026, 9, 9, 6, 0, 0, tzinfo=dt.timezone.utc)
    after = dt.datetime(2026, 9, 11, 6, 0, 0, tzinfo=dt.timezone.utc)

    assert parked.has_expired(before) is False
    assert parked.has_expired(after) is True


def test_expiry_against_a_naive_now_is_read_as_utc_rather_than_local():
    parked = _deferral(dt.datetime(2026, 9, 10, 6, 0, 0, tzinfo=dt.timezone.utc))

    assert parked.has_expired(dt.datetime(2026, 9, 11, 6, 0, 0)) is True


def test_the_offline_scheduler_never_claims_a_timer():
    result = NullScheduler().defer(
        _deferral(dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc))
    )

    assert result.scheduled is False
    assert result.schedule_name == ""
    assert NullScheduler().configured is False


def test_an_unconfigured_environment_falls_back_to_the_null_scheduler():
    """Silently, and safely: the deferral is still recorded, the wake is not claimed."""
    assert scheduler_from_env({}).configured is False
    assert scheduler_from_env({"MERISMOS_SCHEDULER": "none"}).configured is False


def test_a_configured_environment_produces_a_real_scheduler():
    scheduler = scheduler_from_env(
        {
            "MERISMOS_WAKE_TARGET_ARN": "arn:aws:lambda:eu-west-1:1:function:merismos-reader",
            "MERISMOS_SCHEDULER_ROLE_ARN": "arn:aws:iam::1:role/merismos-scheduler",
            "MERISMOS_SCHEDULE_GROUP": "merismos",
        }
    )

    assert scheduler.configured is True
    assert scheduler.group_name == "merismos"


def test_half_a_configuration_is_not_a_scheduler():
    """A target with no role is a schedule that cannot be created. Fail closed."""
    assert (
        scheduler_from_env(
            {"MERISMOS_WAKE_TARGET_ARN": "arn:aws:lambda:eu-west-1:1:function:x"}
        ).configured
        is False
    )

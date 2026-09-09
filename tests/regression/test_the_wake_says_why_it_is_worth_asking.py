"""A wake escalated with the one sentence its reader already knew.

``_wake`` used a fixed reason: "the deferral reached its date and nobody had come
back". True, and it is exactly what somebody reading an escalation has already
worked out from the fact that they are reading one.

The useful sentence was recorded when the decision was parked. A deferral carries
**why it is worth asking again**, which is a different sentence from why it was
refused: "no member could store it today. Cold storage is a fact about the
members rather than about the offer, so this is worth asking again while the food
is still good." The schedule payload never carried it, so the wake could not say
it.

The wake's authority is unchanged and that is asserted here too. It appends an
escalation and nothing else, and carrying a better sentence must not quietly
carry anything else with it.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from merismos import handler
from merismos.deferral import Deferral, Scheduler


class FakeScheduler:
    """Records the payload EventBridge would have been given."""

    def __init__(self):
        self.payloads: list[dict] = []

    def create_schedule(self, **kwargs):
        self.payloads.append(json.loads(kwargs["Target"]["Input"]))
        return {"ScheduleArn": "arn:aws:scheduler:eu-west-1:1:schedule/g/n"}


@pytest.fixture
def scheduled(monkeypatch):
    client = FakeScheduler()
    scheduler = Scheduler(
        target_arn="arn:aws:lambda:eu-west-1:1:function:merismos-runner",
        role_arn="arn:aws:iam::1:role/merismos-scheduler",
        group_name="wakes",
        dead_letter_arn="arn:aws:sqs:eu-west-1:1:merismos-wake-dlq",
        client=client,
    )
    scheduler.defer(
        Deferral(
            deferral_id="def-1",
            subject="kypseli-network:offers/chilled",
            run_id="run-1",
            reason="no member could store it today, so this is worth asking again",
            until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2),
        )
    )
    return client


def test_the_schedule_carries_why_it_is_worth_asking_again(scheduled):
    payload = scheduled.payloads[0]

    assert payload["reason"] == "no member could store it today, so this is worth asking again"


def test_the_wake_escalates_with_that_reason_rather_than_a_generic_one(scheduled, monkeypatch):
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()

    handler._wake({**scheduled.payloads[0], "source": "merismos.deferral"})

    entries = handler.ledger_from_env().thread("run-1")
    escalations = [e for e in entries if e.kind == "deferral.escalated"]

    assert escalations, "the wake appended nothing"
    assert "worth asking again" in escalations[0].body["reason"]
    assert "reached its date" not in escalations[0].body["reason"]


def test_a_schedule_made_before_this_change_still_escalates(monkeypatch):
    """Schedules created by the old build are in flight when this ships."""
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()

    handler._wake(
        {
            "source": "merismos.deferral",
            "deferral_id": "def-old",
            "subject": "kypseli-network",
            "run_id": "run-old",
        }
    )

    entries = handler.ledger_from_env().thread("run-old")
    escalated = [e for e in entries if e.kind == "deferral.escalated"]

    assert escalated, "an older schedule fired and produced nothing at all"
    assert "reached its date" in escalated[0].body["reason"]


def test_a_wake_still_cannot_do_anything_but_append_an_escalation(scheduled, monkeypatch):
    """Carrying a better sentence must not carry anything else with it."""
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()

    handler._wake({**scheduled.payloads[0], "source": "merismos.deferral"})

    kinds = {e.kind for e in handler.ledger_from_env().thread("run-1")}

    assert kinds == {"deferral.escalated"}
    for forbidden in ("plan.proposed", "approval.granted", "record.published"):
        assert forbidden not in kinds


def test_the_escalation_lands_on_the_run_the_deferral_named(scheduled, monkeypatch):
    """An escalation on the wrong thread is an escalation nobody finds."""
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()

    handler._wake({**scheduled.payloads[0], "source": "merismos.deferral"})
    ledger = handler.ledger_from_env()

    assert [e.kind for e in ledger.thread("run-1")] == ["deferral.escalated"]
    assert ledger.thread("run-2") == [], "the escalation reached a run nobody deferred"

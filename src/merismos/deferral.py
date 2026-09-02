"""A deferral until Thursday actually wakes the fleet on Thursday.

The shelter cannot confirm fridge space until Thursday, so the decision is
parked. The question this module answers is what happens on Thursday, and the
usual answer is worse than it sounds.

The common way to build this is a subscription to a standing query: hold an open
subscription to *every finding whose deferral is still open* and act when that
set changes. It is a good design and it has one hole, which is easy to miss
because nothing reports it. **The query carries no date.** A deferral reaching
its expiry writes nothing, changes no result set, and produces no event. So the
expiry is noticed the next time the set changes for some unrelated reason, which
might be Friday, or next week, or after the food has gone. The calendar alone
wakes nothing.

Closing that needs a durable timer: something that fires at a wall-clock moment,
authenticates its callback, and is idempotent under retry. On AWS that is one
API call rather than a subsystem. ``CreateSchedule`` with a one-shot ``at(...)``
expression, a target that is this fleet's Lambda, a role the scheduler assumes,
a ``ClientToken`` for idempotency, a dead-letter queue for the delivery that
fails, and ``ActionAfterCompletion=DELETE`` so a fired schedule removes itself
instead of accumulating against an account quota.

So the fleet wakes when the open set changes **and** when the calendar reaches
the date, because here the date is itself a scheduled call.

What this does **not** buy is any additional authority. An unattended wake may
append an escalation to the thread and may do nothing else. Waking is cheap and
nobody is watching, so the wake path holds no credential that can publish.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

#: EventBridge Scheduler names allow letters, digits, hyphens, underscores and
#: dots, up to 64 characters. A name derived from a finding id has to be forced
#: into that shape, and the forcing has to be collision resistant or two
#: deferrals silently become one.
_NAME_SAFE = re.compile(r"[^A-Za-z0-9._-]")

MAX_NAME = 64


class DeferralRefused(ValueError):
    """Raised when a deferral cannot be scheduled as asked."""


def schedule_name(prefix: str, deferral_id: str) -> str:
    """A stable, legal, collision-resistant schedule name.

    The digest tail is not decoration. Two deferral ids that differ only past
    the truncation point would otherwise produce the same schedule name, and
    ``CreateSchedule`` would reject the second as a duplicate, so one of two
    findings would silently never wake.
    """
    tail = hashlib.sha256(deferral_id.encode("utf-8")).hexdigest()[:12]
    stem = _NAME_SAFE.sub("-", f"{prefix}-{deferral_id}")
    room = MAX_NAME - len(tail) - 1
    return f"{stem[:room]}-{tail}"


def at_expression(when: dt.datetime) -> str:
    """Render a one-shot schedule expression.

    EventBridge Scheduler takes ``at(yyyy-mm-ddThh:mm:ss)`` with **no** offset
    and no trailing ``Z``, and reads it in the schedule's timezone. So a
    timezone-aware value is converted to UTC and then stripped, and a naive one
    is taken as UTC already. Getting this wrong is a schedule that fires hours
    late and a test that passes because it built its fixture from the same
    function.
    """
    if when.tzinfo is not None:
        when = when.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return f"at({when.strftime('%Y-%m-%dT%H:%M:%S')})"


@dataclass(frozen=True)
class Deferral:
    """A decision parked until a date, and the wake that will unpark it."""

    deferral_id: str
    subject: str
    run_id: str
    reason: str
    until: dt.datetime
    schedule_name: str = ""
    scheduled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "deferral_id": self.deferral_id,
            "subject": self.subject,
            "run_id": self.run_id,
            "reason": self.reason,
            "until": self.until.isoformat(),
            "schedule_name": self.schedule_name,
            "scheduled": self.scheduled,
        }

    def has_expired(self, now: dt.datetime | None = None) -> bool:
        moment = now or dt.datetime.now(dt.timezone.utc)
        until = self.until
        if until.tzinfo is None:
            until = until.replace(tzinfo=dt.timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=dt.timezone.utc)
        return moment >= until


class Scheduler:
    """Creates the one-shot schedule that wakes the fleet on the day.

    Every argument that names an AWS resource is read from the environment
    rather than defaulted, because a scheduler that silently targets the wrong
    Lambda is a deferral that fires into nothing and is never noticed.
    """

    def __init__(
        self,
        target_arn: str = "",
        role_arn: str = "",
        group_name: str = "",
        dead_letter_arn: str = "",
        client: Any = None,
    ) -> None:
        self.target_arn = target_arn or os.environ.get("MERISMOS_WAKE_TARGET_ARN", "")
        self.role_arn = role_arn or os.environ.get("MERISMOS_SCHEDULER_ROLE_ARN", "")
        self.group_name = group_name or os.environ.get(
            "MERISMOS_SCHEDULE_GROUP", "default"
        )
        self.dead_letter_arn = dead_letter_arn or os.environ.get("MERISMOS_WAKE_DLQ_ARN", "")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("scheduler")
        return self._client

    @property
    def configured(self) -> bool:
        return bool(self.target_arn and self.role_arn)

    def defer(self, deferral: Deferral) -> Deferral:
        """Create the schedule, or say plainly that there is none.

        A deferral whose schedule could not be created is still a deferral: it
        is written to the thread and the open set still holds it, so the
        set-changed path still escalates it eventually. What is lost is the
        calendar wake, and ``scheduled=False`` says so rather than letting the
        product claim a timer it does not have for that item.
        """
        if not self.configured:
            raise DeferralRefused(
                "no wake target or scheduler role is configured, so this "
                "deferral would never fire. Set MERISMOS_WAKE_TARGET_ARN and "
                "MERISMOS_SCHEDULER_ROLE_ARN"
            )
        name = deferral.schedule_name or schedule_name("merismos-wake", deferral.deferral_id)
        payload = json.dumps(
            {
                "source": "merismos.deferral",
                "deferral_id": deferral.deferral_id,
                "subject": deferral.subject,
                "run_id": deferral.run_id,
            },
            sort_keys=True,
        )
        target: dict[str, Any] = {
            "Arn": self.target_arn,
            "RoleArn": self.role_arn,
            "Input": payload,
            "RetryPolicy": {
                "MaximumRetryAttempts": 3,
                "MaximumEventAgeInSeconds": 3600,
            },
        }
        if self.dead_letter_arn:
            target["DeadLetterConfig"] = {"Arn": self.dead_letter_arn}

        self.client.create_schedule(
            Name=name,
            GroupName=self.group_name,
            ScheduleExpression=at_expression(deferral.until),
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            # A fired one-shot schedule deletes itself. Without this, a fleet
            # that defers a hundred findings a month accumulates a hundred dead
            # schedules a month and eventually meets the account quota, which is
            # a failure that arrives as "deferrals stopped working" long after
            # the cause.
            ActionAfterCompletion="DELETE",
            # Idempotency. A retried create for the same deferral is the same
            # schedule, not a second wake for the same finding.
            ClientToken=hashlib.sha256(name.encode("utf-8")).hexdigest()[:64],
            Description=f"Merismos deferral {deferral.deferral_id}: {deferral.reason[:180]}",
            Target=target,
        )
        return Deferral(
            deferral_id=deferral.deferral_id,
            subject=deferral.subject,
            run_id=deferral.run_id,
            reason=deferral.reason,
            until=deferral.until,
            schedule_name=name,
            scheduled=True,
        )


class NullScheduler:
    """The offline stand-in. It refuses rather than pretending to schedule.

    A no-op that returned ``scheduled=True`` would make the offline demo show a
    capability that is not there, which is exactly the failure mode this project
    argues against. So the offline path records the deferral and reports that no
    timer backs it.
    """

    configured = False

    def defer(self, deferral: Deferral) -> Deferral:
        return Deferral(
            deferral_id=deferral.deferral_id,
            subject=deferral.subject,
            run_id=deferral.run_id,
            reason=deferral.reason,
            until=deferral.until,
            schedule_name="",
            scheduled=False,
        )


def escalate(
    thread: Any,
    deferral_id: str,
    reason: str,
    fired_by: str = "schedule",
) -> dict[str, Any]:
    """What an unattended wake is allowed to do, and it is only this.

    Appending to the thread, and nothing else. There is no branch in this
    function that proposes a plan, mints an approval or reaches the writer, and
    ``tests/unit/test_a_wake_cannot_publish.py`` asserts that no such entry can
    result from a wake.
    """
    entry = thread.append(
        "deferral.escalated",
        deferral_id=deferral_id,
        reason=reason,
        fired_by=fired_by,
    )
    return {
        "escalated": deferral_id,
        "entry_id": entry.entry_id,
        "note": (
            "an unattended wake appends an escalation and cannot publish. "
            "A person still has to look"
        ),
    }


def scheduler_from_env(env: dict[str, str] | None = None) -> Any:
    """Pick a scheduler, defaulting to the real one."""
    env = dict(os.environ) if env is None else env
    if env.get("MERISMOS_SCHEDULER", "eventbridge").strip().lower() == "none":
        return NullScheduler()
    scheduler = Scheduler(
        target_arn=env.get("MERISMOS_WAKE_TARGET_ARN", ""),
        role_arn=env.get("MERISMOS_SCHEDULER_ROLE_ARN", ""),
        group_name=env.get("MERISMOS_SCHEDULE_GROUP", "default"),
        dead_letter_arn=env.get("MERISMOS_WAKE_DLQ_ARN", ""),
    )
    return scheduler if scheduler.configured else NullScheduler()

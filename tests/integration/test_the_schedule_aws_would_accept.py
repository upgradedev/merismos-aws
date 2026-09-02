"""The deferral is checked against the real EventBridge Scheduler API shape.

A hand-rolled mock accepts whatever you send it, so a test built on one asserts
that the code calls the mock the way the code calls the mock. ``Stubber``
validates the parameters against botocore's own service model, which is the
same model the SDK validates against on a real call. A misspelled key or a
wrongly typed member fails here rather than in a deployment.

It needs no credentials and no network, so it runs in the offline suite.
"""

from __future__ import annotations

import datetime as dt

import boto3
import pytest
from botocore.stub import ANY, Stubber

from mitos.deferral import Deferral, NullScheduler, Scheduler, at_expression, schedule_name


def _deferral(until: dt.datetime) -> Deferral:
    return Deferral(
        deferral_id="finding-4471-cold-chain",
        subject="kypseli-network:pantry",
        run_id="run-9",
        reason="the shelter cannot confirm fridge space until Thursday",
        until=until,
    )


def test_create_schedule_matches_the_published_api():
    client = boto3.client("scheduler", region_name="eu-west-1")
    stubber = Stubber(client)
    stubber.add_response(
        "create_schedule",
        {"ScheduleArn": "arn:aws:scheduler:eu-west-1:1:schedule/default/mitos-wake-x"},
        {
            "Name": ANY,
            "GroupName": "mitos",
            "ScheduleExpression": "at(2026-09-10T06:00:00)",
            "ScheduleExpressionTimezone": "UTC",
            "FlexibleTimeWindow": {"Mode": "OFF"},
            "ActionAfterCompletion": "DELETE",
            "ClientToken": ANY,
            "Description": ANY,
            "Target": {
                "Arn": "arn:aws:lambda:eu-west-1:1:function:mitos-reader",
                "RoleArn": "arn:aws:iam::1:role/mitos-scheduler",
                "Input": ANY,
                "RetryPolicy": {
                    "MaximumRetryAttempts": 3,
                    "MaximumEventAgeInSeconds": 3600,
                },
                "DeadLetterConfig": {"Arn": "arn:aws:sqs:eu-west-1:1:mitos-wake-dlq"},
            },
        },
    )
    scheduler = Scheduler(
        target_arn="arn:aws:lambda:eu-west-1:1:function:mitos-reader",
        role_arn="arn:aws:iam::1:role/mitos-scheduler",
        group_name="mitos",
        dead_letter_arn="arn:aws:sqs:eu-west-1:1:mitos-wake-dlq",
        client=client,
    )

    with stubber:
        result = scheduler.defer(
            _deferral(dt.datetime(2026, 9, 10, 6, 0, 0, tzinfo=dt.timezone.utc))
        )

    stubber.assert_no_pending_responses()
    assert result.scheduled is True
    assert result.schedule_name


def test_an_offset_aware_time_is_converted_to_utc_and_stripped():
    """The expression carries no offset, so a naive render would fire late.

    Athens in September is UTC+3, so 09:00 local is 06:00 UTC. A fixture built
    by calling the function under test could not catch this, so the expected
    string is written out by hand.
    """
    athens = dt.timezone(dt.timedelta(hours=3))
    when = dt.datetime(2026, 9, 10, 9, 0, 0, tzinfo=athens)

    assert at_expression(when) == "at(2026-09-10T06:00:00)"


def test_a_naive_time_is_taken_as_utc():
    assert at_expression(dt.datetime(2026, 9, 10, 6, 0, 0)) == "at(2026-09-10T06:00:00)"


def test_two_long_deferral_ids_do_not_collide_on_one_schedule_name():
    """Truncation without a digest would silently drop one of two wakes."""
    stem = "finding-" + "a" * 90
    first = schedule_name("mitos-wake", stem + "-one")
    second = schedule_name("mitos-wake", stem + "-two")

    assert first != second
    assert len(first) <= 64 and len(second) <= 64


def test_an_unconfigured_scheduler_refuses_rather_than_pretending():
    scheduler = Scheduler(target_arn="", role_arn="", client=object())

    with pytest.raises(Exception) as raised:
        scheduler.defer(_deferral(dt.datetime(2026, 9, 10, 6, 0, 0)))

    assert "never fire" in str(raised.value)


def test_the_offline_scheduler_reports_that_no_timer_backs_the_deferral():
    result = NullScheduler().defer(_deferral(dt.datetime(2026, 9, 10, 6, 0, 0)))

    assert result.scheduled is False, "the offline path must not claim a timer"

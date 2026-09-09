"""124 kg of a 240 kg donation had no recipient and the screen did not say so.

The register says it plainly: "the quantity left over is published with the
shares rather than left for a reader to work out by subtraction. A coordinator
seeing '124 kg still needs a home' can ring a sixth organisation. A coordinator
seeing three shares that do not add up assumes the arithmetic is theirs to
check."

The published record did that. The decision screen, which is the one a
coordinator reads and the only one they see before approving, did not. Checked
against the live site on the real offer-4471 run: 96 and 20 in the table, and
nothing anywhere saying where the other 124 kg went.

It is the most actionable fact on the page. It is the one that means pick up the
phone.
"""

from __future__ import annotations

import re

import pytest

from merismos import handler
from merismos.fleet import new_run_id, subject_for_offer
from merismos.ledger import Thread, ledger_from_env


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()


def decision(offer_id: str) -> str:
    offer = handler._offer(offer_id)
    run = new_run_id()
    Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(handler.NETWORK, offer),
        run_id=run,
    ).append("run.started", offer_id=offer_id)
    handler._run_in_background(
        {
            "source": "merismos.background",
            "offer_id": offer_id,
            "run_id": run,
            "network": handler.NETWORK,
        }
    )
    reply = handler.handler(
        {
            "requestContext": {"http": {"method": "GET", "path": f"/offer/{offer_id}"}},
            "headers": {"content-type": "application/json"},
            "body": "{}",
            "queryStringParameters": {"run": run},
        }
    )
    assert reply["statusCode"] == 200
    return reply["body"]


def as_text(html: str) -> str:
    body = html[html.index("</style>") :]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def test_the_leftover_is_on_the_screen_and_not_left_to_subtraction():
    """offer-4471: 240 kg offered, 96 and 20 allocated, 124 with nowhere to go."""
    text = as_text(decision("offer-4471"))

    assert "Still without a recipient: 124 kg" in text
    assert "Offered 240 kg, allocated 116 kg" in text


def test_it_says_the_leftover_is_the_rules_working_rather_than_a_fault():
    """A number with no explanation reads as a bug and gets re-litigated."""
    text = as_text(decision("offer-4471"))

    assert "not an error and not an oversight" in text
    assert "ring an organisation outside this network" in text, (
        "it states the number without saying what a person can do about it"
    )


def test_it_reads_correctly_for_an_offer_counted_in_units():
    """The unit is sometimes "units", and the sentence must not agree with it.

    "36 units still needs a home" was the first wording. Leading with the state
    rather than the quantity avoids agreeing with a noun the code does not know.
    """
    text = as_text(decision("offer-4483"))

    assert "Still without a recipient: 36 units" in text
    assert "units still needs" not in text


def test_a_blocked_offer_shows_no_arithmetic_because_there_is_no_split():
    """offer-4477 is refused in full. A leftover line would imply a partial one."""
    text = as_text(decision("offer-4477"))

    assert "Still without a recipient" not in text
    assert "Refused" in text

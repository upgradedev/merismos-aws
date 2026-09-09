"""The decision screen counted read events and called them files.

"The specialists opened 25 files from the network's own filing:
`offers/manifests/4471.md, offers/manifests/4471.md, offers/offer-4471.json`..."
That is the live run's own sentence, listing one file twice inside a count of
files.

**Third instance of the same shape in one day**, after the waiting screen that
counted to eight out of four and the read budget published in files and counted
in reads. Something is counted in events and published in a different unit, and
the published word is the only one a reader can check against.
"""

from __future__ import annotations

import re

import pytest

from merismos import handler
from merismos.envelope import Envelope, Status
from merismos.fleet import new_run_id, subject_for_offer
from merismos.ledger import Thread, ledger_from_env


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()


class Recorded:
    """A finished run whose read log opened one file three times."""

    outcome = "awaiting_approval"
    note = ""
    verdict = None
    run_id = "run-1"
    deferrals: list = []
    woken = ["premises"]
    skipped: list = []
    approval = None
    # ``_specialists`` returns nothing without one, and an empty section
    # would make every assertion below pass by vacuum.
    envelopes = [Envelope(specialist="premises", status=Status.OK)]
    draft = None
    read_log = {
        "scope": ["offers/"],
        "budget": 6,
        "spent": 1,
        "remaining": 5,
        "reads": [
            {"path": "offers/manifests/4471.md", "served": True},
            {"path": "offers/manifests/4471.md", "served": True},
            {"path": "offers/offer-4471.json", "served": True},
            {"path": "orgs/nope.json", "served": False},
        ],
    }


def test_a_file_opened_twice_is_one_file():
    from merismos import web

    note = web._specialists(Recorded())

    assert "opened 2 files" in note, "read events are being counted as files"
    assert note.count("offers/manifests/4471.md") == 1, "the list repeats a file"


def test_a_refused_read_is_not_counted_as_a_file_opened():
    from merismos import web

    assert "orgs/nope.json" not in web._specialists(Recorded())


def test_one_file_is_singular():
    from merismos import web

    class One(Recorded):
        read_log = {
            **Recorded.read_log,
            "reads": [{"path": "offers/offer-4471.json", "served": True}] * 3,
        }

    note = web._specialists(One())
    assert "opened 1 file from" in note


def test_the_live_shape_reads_correctly_end_to_end():
    """Through the handler, so the fix is on the screen and not only in a helper."""
    offer = handler._offer("offer-4471")
    run = new_run_id()
    Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(handler.NETWORK, offer),
        run_id=run,
    ).append("run.started", offer_id="offer-4471")
    handler._run_in_background(
        {
            "source": "merismos.background",
            "offer_id": "offer-4471",
            "run_id": run,
            "network": handler.NETWORK,
        }
    )
    reply = handler.handler(
        {
            "requestContext": {"http": {"method": "GET", "path": "/offer/offer-4471"}},
            "headers": {"content-type": "application/json"},
            "body": "{}",
            "queryStringParameters": {"run": run},
        }
    )
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", reply["body"]))

    found = re.search(r"opened (\d+) files? from the network's own filing: ([^.]+)", text)
    assert found, "the read note is gone"
    listed = [p.strip() for p in found.group(2).split(",")]
    assert len(listed) == len(set(listed)), f"the list repeats a file: {listed}"
    assert int(found.group(1)) == len(set(listed))

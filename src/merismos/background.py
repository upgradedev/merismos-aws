"""Running a chore that takes longer than a web request is allowed to.

An API Gateway integration times out at 30 seconds and that ceiling cannot be
raised. A specialist reading a repository with a model takes about 100 seconds,
and a run wakes four of them. So a synchronous page **cannot** use a model, and
the first deployed version of this site did not: it ran the deterministic rules
and a persona review caught exactly that, because the entry's whole argument is
that the SDK is load-bearing and the deployed path was not touching it.

The work does not have to fit in the request. It has to fit in the **reader's
own** timeout, which is 900 seconds.

So a run is started, not awaited. The page asks the reader to invoke itself with
``InvocationType="Event"``, gets a run id back immediately, and then polls the
provenance thread, which is already the place every step of a chore records
itself. Nothing new stores state: the thread was always the memory and the audit
trail, and here it is also the progress bar.

**Polling is a meta refresh, not a script.** Every screen in this product loads
no JavaScript and no external asset, which is asserted per screen, and that
guarantee is worth more than a smoother spinner.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

#: The payload shape that tells a reader invocation it is a background chore
#: rather than an HTTP event.
SOURCE = "merismos.background"


def start(offer_id: str, run_id: str, network: str) -> None:
    """Ask the reader to run this chore in the background.

    Raises rather than returning a flag if the invoke fails. A run that was
    never started, shown as a run in progress, is a page that spins for ever.
    """
    import boto3

    function = os.environ.get("MERISMOS_READER_FUNCTION", "")
    if not function:
        raise RuntimeError("MERISMOS_READER_FUNCTION is not set, so no chore can be started")

    boto3.client("lambda").invoke(
        FunctionName=function,
        InvocationType="Event",
        Payload=json.dumps(
            {"source": SOURCE, "offer_id": offer_id, "run_id": run_id, "network": network}
        ),
    )


def is_background(event: Any) -> bool:
    return isinstance(event, dict) and event.get("source") == SOURCE


#: The order a run reaches these, so a page can say what is happening rather
#: than only that something is.
STAGES = (
    ("run.started", "starting"),
    ("offer.received", "reading the offer"),
    ("fleet.dispatch", "deciding who wakes"),
    ("specialist.answered", "the specialists are reading the filing"),
    ("read.performed", "gathering what they opened"),
    ("gate.verdict", "the gate is checking the draft"),
    ("run.completed", "done"),
)


def progress(entries) -> dict[str, Any]:
    """Turn a thread into something a person can watch.

    ``specialist.answered`` is counted rather than flagged, because four
    specialists reading for a minute each is the part somebody is actually
    waiting through, and a bar that sits on one label for four minutes tells
    them nothing.
    """
    kinds = [e.kind for e in entries]
    answered = sum(1 for k in kinds if k == "specialist.answered")
    done = "run.completed" in kinds
    failed = "run.failed" in kinds

    reached = "starting"
    for kind, label in STAGES:
        if kind in kinds:
            reached = label

    return {
        "done": done,
        "failed": failed,
        "specialists_answered": answered,
        "stage": reached,
        "entries": len(entries),
    }


def completed_result(entries) -> Mapping[str, Any] | None:
    """The finished chore, as it was recorded, or None if it is still running."""
    for entry in entries:
        if entry.kind == "run.completed":
            return entry.body
    return None


def failure(entries) -> str:
    for entry in entries:
        if entry.kind == "run.failed":
            return str(entry.body.get("detail", "the run failed"))
    return ""

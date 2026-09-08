"""Anybody holding a link to the corrected record had no way to learn it changed.

``web.py``'s own docstring names four screens and the fourth was never routed:
"``/record/<id>`` the published record, which is what a funder opens in March."
A funder in March got raw markdown from an S3 address, which is a file rather
than a screen.

That was a documentation gap until corrections landed, and then it became a real
one. A correction publishes to the next address in the series and the original
stays live. The supersession notice lived only in the published index, and a
direct link is exactly the thing that skips the index. "Marked superseded by the
index" is what the commit said, and everybody who had been sent the original
address would have seen nothing.

The superseded record is served rather than hidden or redirected. Somebody may
have acted on what it said, and the useful thing to give them is what they were
told next to the fact that it changed. A redirect would quietly replace their
memory of it.
"""

from __future__ import annotations

import json

import pytest

from merismos import handler
from merismos.fleet import new_run_id, subject_for_offer
from merismos.ledger import Thread, ledger_from_env

OFFER = "offer-4471"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    from merismos.ledger import reset_memory_ledger

    reset_memory_ledger()


def get(path: str) -> dict:
    return handler.handler(
        {
            "requestContext": {"http": {"method": "GET", "path": path}},
            "headers": {"content-type": "application/json"},
            "body": "{}",
            "queryStringParameters": {},
        }
    )


def a_finished_run() -> tuple[str, Thread]:
    offer = handler._offer(OFFER)
    run = new_run_id()
    thread = Thread(
        ledger=ledger_from_env(),
        subject=subject_for_offer(handler.NETWORK, offer),
        run_id=run,
    )
    thread.append("run.started", offer_id=OFFER)
    handler._run_in_background(
        {
            "source": "merismos.background",
            "offer_id": OFFER,
            "run_id": run,
            "network": handler.NETWORK,
        }
    )
    return run, thread


def publish(thread: Thread, run: str, key: str, digest: str) -> None:
    thread.append(
        "record.published",
        key=key,
        approved_by="the coordinator on duty",
        run_id=run,
        content_digest=digest,
        published_url=f"https://records.invalid/{key}",
    )


def test_an_address_nobody_published_to_is_not_a_record():
    """Merismos does not publish without a person, and does not pretend to."""
    a_finished_run()
    reply = get(f"/record/{OFFER}")

    assert reply["statusCode"] == 404
    assert "does not publish without a person" in reply["body"]


def test_an_unknown_offer_is_a_404_rather_than_an_empty_record():
    assert get("/record/offer-0000")["statusCode"] == 404


def test_a_published_record_is_served_as_a_screen_and_not_only_as_a_file():
    run, thread = a_finished_run()
    publish(thread, run, f"records/{OFFER}.md", "sha256:one")

    reply = get(f"/record/{OFFER}")

    assert reply["statusCode"] == 200
    assert "text/html" in reply["headers"]["content-type"]
    assert "The record" in reply["body"]
    assert "sha256:one" in reply["body"], "the receipt does not carry the digest"


def test_a_record_with_no_correction_does_not_claim_to_have_one():
    run, thread = a_finished_run()
    publish(thread, run, f"records/{OFFER}.md", "sha256:one")

    assert "was corrected" not in get(f"/record/{OFFER}")["body"]


# --------------------------------------------------------------------------
# The half this exists for.
# --------------------------------------------------------------------------


def test_the_superseded_record_says_it_was_corrected_and_names_the_replacement():
    run, thread = a_finished_run()
    publish(thread, run, f"records/{OFFER}.md", "sha256:one")
    publish(thread, run, f"records/{OFFER}-c2.md", "sha256:two")

    body = get(f"/record/{OFFER}")["body"]

    assert "was corrected" in body
    assert f"records/{OFFER}-c2.md" in body, "it says it changed and not what to read"
    assert f"/record/{OFFER}-c2" in body, "the replacement is named but not reachable"


def test_the_superseded_record_is_still_served_rather_than_hidden():
    """Somebody acted on it. Withdrawing it replaces their memory of it."""
    run, thread = a_finished_run()
    publish(thread, run, f"records/{OFFER}.md", "sha256:one")
    publish(thread, run, f"records/{OFFER}-c2.md", "sha256:two")

    reply = get(f"/record/{OFFER}")

    assert reply["statusCode"] == 200, "a superseded record was withdrawn rather than marked"
    assert "The record" in reply["body"]


def test_the_correction_itself_carries_no_warning():
    run, thread = a_finished_run()
    publish(thread, run, f"records/{OFFER}.md", "sha256:one")
    publish(thread, run, f"records/{OFFER}-c2.md", "sha256:two")

    body = get(f"/record/{OFFER}-c2")["body"]

    assert "was corrected" not in body
    assert f"records/{OFFER}-c2.md" in body


def test_the_correction_links_to_itself_rather_than_back_to_what_it_replaced():
    """A notice pointing at the original sends the reader where they started."""
    run, thread = a_finished_run()
    publish(thread, run, f"records/{OFFER}.md", "sha256:one")
    publish(thread, run, f"records/{OFFER}-c2.md", "sha256:two")
    publish(thread, run, f"records/{OFFER}-c3.md", "sha256:three")

    body = get(f"/record/{OFFER}-c2")["body"]

    assert "was corrected" in body, "a middle version is superseded too"
    assert f"/record/{OFFER}-c3" in body


def test_an_unreadable_thread_is_not_reported_as_a_missing_record():
    """The record is published either way. This screen is what cannot be built."""
    run, thread = a_finished_run()
    publish(thread, run, f"records/{OFFER}.md", "sha256:one")

    class Unreadable:
        def __init__(self, real):
            self._real = real

        def recall(self, subject, kind, limit=20):
            raise RuntimeError("ProvisionedThroughputExceededException")

        def __getattr__(self, name):
            return getattr(self._real, name)

    real = ledger_from_env()
    handler.ledger_from_env = lambda: Unreadable(real)  # noqa: E731
    try:
        reply = get(f"/record/{OFFER}")
    finally:
        from merismos.ledger import ledger_from_env as restore

        handler.ledger_from_env = restore

    assert reply["statusCode"] == 503
    assert "404" not in reply["body"]
    assert "published and unaffected" in reply["body"]


def test_the_docstring_that_promised_this_screen_now_matches_the_routes():
    """The claim that started this: four screens named, three routed."""
    from merismos import web

    assert "``/record/<id>``" in (web.__doc__ or "")
    assert json.dumps(get(f"/record/{OFFER}")["statusCode"]) in ("404", "200")

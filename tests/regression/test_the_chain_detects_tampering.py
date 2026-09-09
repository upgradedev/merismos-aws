"""The custody chain verified a thread that had been edited, reordered and cut.

``custody.py``'s own docstring said: "A hash chain is what closes some of that
gap, because a row edited from outside our code no longer verifies."

Probed with a five entry thread. Edit a middle entry's body: ``verified: True``.
Swap two entries: ``verified: True``. Delete one: ``verified: True``. All three
at once, on the claim the module is named for.

``chain_for`` **rebuilds** the chain from whatever entries it is handed and
``verify_integrity`` then checks those hashes against each other. A tampered
thread does not fail; it produces a different chain that is internally
consistent. Altering an entry does change every hash after it, which is what the
README says and is true, and there was no stored baseline for the new hashes to
disagree with, which is what made the property useless.

Two things close it. ``parent_id`` was already stored on every entry and was
never read, and reading it catches a deletion or a reorder with no schema change
at all. And a digest is now written when an entry is written, which catches an
edit.

**The digest is stamped on the way in and never on construction.** Filling it in
``__post_init__`` would also fill it for a row read back from the store,
computing it from whatever that row currently says and certifying an edited row
as intact. That is worse than having no digest, because it turns unknown into
verified, and it was the first version of this fix.
"""

from __future__ import annotations

import dataclasses

import pytest

from merismos import custody
from merismos.ledger import Entry, InMemoryLedger, Thread

KINDS = ("run.started", "offer.received", "specialist.answered", "gate.verdict", "plan.proposed")


@pytest.fixture
def entries() -> list[Entry]:
    thread = Thread(ledger=InMemoryLedger(), subject="kypseli-network", run_id="run-1")
    for kind in KINDS:
        thread.append(kind, note=kind)
    return thread.ledger.thread("run-1")


def verdict(rows) -> dict:
    return custody.summary("offer-4471", rows)


# --------------------------------------------------------------------------
# The three tampering modes, each of which used to pass.
# --------------------------------------------------------------------------


def test_an_untouched_thread_verifies(entries):
    """The control. Without it the rest could pass by always failing."""
    reported = verdict(entries)

    assert reported["verified"] is True
    assert reported["unchecked_entries"] == 0


def test_an_edited_body_no_longer_verifies(entries):
    tampered = [
        dataclasses.replace(e, body={"note": "EDITED"}) if i == 2 else e
        for i, e in enumerate(entries)
    ]

    reported = verdict(tampered)

    assert reported["verified"] is False
    assert "does not match the digest" in reported["detail"]


def test_two_reordered_entries_no_longer_verify(entries):
    swapped = list(entries)
    swapped[1], swapped[2] = swapped[2], swapped[1]

    reported = verdict(swapped)

    assert reported["verified"] is False
    assert "removed, reordered or inserted" in reported["detail"]


def test_a_deleted_entry_no_longer_verifies(entries):
    reported = verdict([e for i, e in enumerate(entries) if i != 2])

    assert reported["verified"] is False
    assert "removed, reordered or inserted" in reported["detail"]


# --------------------------------------------------------------------------
# What it must not do, which is invent certainty.
# --------------------------------------------------------------------------


def test_a_row_written_before_the_digest_existed_is_counted_as_unchecked(entries):
    """Not failed. A row that predates the digest is not evidence of tampering.

    It is not evidence of anything else either, so it is counted and named
    rather than folded into the verified total.
    """
    legacy = [
        Entry(
            kind=e.kind,
            subject=e.subject,
            run_id=e.run_id,
            body=dict(e.body),
            entry_id=e.entry_id,
            parent_id=e.parent_id,
            at=e.at,
        )
        for e in entries
    ]

    reported = verdict(legacy)

    assert reported["unchecked_entries"] == len(legacy)
    assert "not evidence of tampering" in reported["what_this_cannot_see"]


def test_reading_an_entry_back_never_invents_its_digest():
    """The first version of this fix did exactly that, and it is the worst case.

    ``__post_init__`` filling the digest means a row read from the store is
    hashed from whatever it currently says, so an edited row verifies. Unknown
    becomes verified, which is worse than having no digest at all.
    """
    read_back = Entry(kind="run.started", subject="s", run_id="r", body={"note": "whatever"})

    assert read_back.body_sha == "", "constructing an entry stamped it"


def test_a_digest_is_written_when_an_entry_is_appended():
    thread = Thread(ledger=InMemoryLedger(), subject="s", run_id="r")

    appended = thread.append("run.started", note="x")

    assert appended.body_sha, "an appended entry carries no digest"
    assert appended.body_sha == appended.digest()


def test_the_digest_covers_what_the_entry_asserts_and_not_its_shelf(entries):
    """``scope`` moves when a run is archived, by this code, legitimately."""
    archived = dataclasses.replace(entries[0], scope="archived")

    assert archived.digest() == entries[0].digest()

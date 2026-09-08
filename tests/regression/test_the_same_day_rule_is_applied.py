"""offer-4471 published a share to an organisation the same rule forbade.

Reported by a second agent on 2026-09-08 and reproduced here before anything was
changed. The published record for offer-4471 gave 96 kg to Kypseli Food Pantry
while the same document said, in its own words, that only organisations serving
same day may take a share, and named Omonoia Soup Kitchen and Elpida Night
Shelter as those organisations. The pantry is not one of them. The record then
said every constraint was satisfied.

**This is the failure this whole project argues against.** The rule was present
as prose and absent from the mechanism. ``food_safety`` appended a ``medium``
finding and returned an envelope carrying no ``meta``, and the solver reads
eligibility out of ``meta['eligible']`` and ``meta['blocked_for']``. So the
sentence reached the reader and never reached the solver.

Two separate defects are pinned here, because fixing one would leave a record
that is still wrong:

1. an organisation with ``same_day_service: false`` receives a share;
2. Elpida Night Shelter, which is eligible, receives nothing, because transport
   was applied as a veto on the organisation rather than as a cap on its share.

The arithmetic the record should reach: 240 kg, a 40% ceiling of 96 kg, the
kitchen taking 96 with a van, the shelter taking 20 on foot, and **124 kg with
no recipient**, which is an outcome to publish rather than an omission to hide.
"""

from __future__ import annotations

import json

import pytest

from merismos.corpus import LocalCorpus
from merismos.fleet import new_run_id, run_chore, subject_for_offer
from merismos.ledger import InMemoryLedger, Thread

NETWORK = "kypseli-network"
OFFER = "offer-4471"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_MODEL", "none")


@pytest.fixture
def run():
    corpus = LocalCorpus()
    offer = json.loads(corpus.read(f"offers/{OFFER}.json"))
    thread = Thread(
        ledger=InMemoryLedger(),
        subject=subject_for_offer(NETWORK, offer),
        run_id=new_run_id(),
    )
    return run_chore(corpus, offer, thread, network=NETWORK)


@pytest.fixture
def orgs():
    corpus = LocalCorpus()
    loaded = [
        json.loads(corpus.read(f"orgs/{name}"))
        for name in (
            "kitchen-omonoia.json",
            "library-anemos.json",
            "pantry-kypseli.json",
            "school-second-chance.json",
            "shelter-elpida.json",
        )
    ]
    return {org["name"]: org for org in loaded}


def _shares(run) -> dict[str, float]:
    return {a["org"]: float(a["quantity"]) for a in (run.draft.allocations if run.draft else [])}


def test_no_share_goes_to_an_organisation_that_does_not_serve_same_day(run, orgs):
    """The defect, stated as the rule the register already carried."""
    ineligible = {
        org: qty for org, qty in _shares(run).items() if not orgs[org].get("same_day_service")
    }
    assert not ineligible, (
        f"use-by is one day after collection, so the register allows only "
        f"organisations serving same day, and these received a share anyway: "
        f"{ineligible}"
    )


def test_an_eligible_organisation_is_capped_by_transport_not_excluded_by_it(run):
    """Elpida can carry 20 kg on foot. That is a smaller share, not no share."""
    assert _shares(run).get("Elpida Night Shelter"), (
        "the shelter serves same day and is one of only two organisations "
        "allowed to receive this offer. Transport limits the size of its share "
        "to what a volunteer carries, and it was excluded outright instead"
    )


def test_a_share_never_exceeds_what_the_organisation_can_carry(run, orgs):
    """A cap that is not enforced is worse than no cap: it reads as checked."""
    over = {
        org: (qty, orgs[org]["walk_in_limit_kg"])
        for org, qty in _shares(run).items()
        if not orgs[org].get("has_van") and qty > orgs[org]["walk_in_limit_kg"]
    }
    assert not over, f"a share exceeds what a volunteer can carry on foot: {over}"


def test_the_record_names_the_quantity_that_found_no_recipient(run):
    """240 kg in, 116 kg allocated. The rest is a number a coordinator needs."""
    body = run.draft.body if run.draft else ""
    allocated = sum(_shares(run).values())
    remainder = 240.0 - allocated

    assert remainder > 0, "this offer cannot be fully allocated under its own rules"
    assert f"{remainder:.0f}" in body, (
        f"{remainder:.0f} kg found no recipient and the record does not say so. "
        f"A coordinator reading this has to work out for themselves that more "
        f"than half the offer still needs a home"
    )


def test_the_gate_refuses_a_draft_that_breaks_the_rule_the_fleet_itself_recorded(run):
    """The gate is the backstop, and it is the half that must not be skipped.

    The solver could be corrected on its own and this would still be a system in
    which the only thing standing between a forbidden share and a published
    record is that the solver got it right. The gate re-checks the draft against
    the fleet's own exclusions, so the exclusion has to reach it.
    """
    barred = run.draft.must_not_receive if run.draft else frozenset()
    assert "Kypseli Food Pantry" in barred, (
        "the food-safety specialist found the rule and never put the "
        "organisations it excludes where the gate can see them, so the gate "
        "had nothing to check the draft against"
    )

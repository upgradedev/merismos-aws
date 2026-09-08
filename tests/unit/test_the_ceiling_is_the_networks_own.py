"""The ceiling comes out of the filing, not out of this file.

Found by persona 09's second criterion, which says to run the quickstart against
a fixture the product did not ship with and calls **identical output the harder
failure, because it means the fixture is never read.**

It was identical. A four-organisation network in Rotterdam, with its own
`registers/allocation-policy.md` saying 25%, produced Omonoia Soup Kitchen,
Kypseli Food Pantry and offer-4471, none of which exist in it. Two separate
causes sat behind that one symptom:

* the demo called ``LocalCorpus()`` with no argument whenever no S3 bucket was
  set, so ``MERISMOS_CORPUS_ROOT`` was ignored on the only path a stranger runs;
* and ``equity`` computed ``quantity * 0.40`` as a constant, while
  ``registers/allocation-policy.md`` was listed as something that specialist
  reads.

The second is the one worth a test file. This product's whole premise is that a
network points the fleet at its own filing, and a ceiling that ignores the filing
makes "reads the network's own policies" a sentence about the wrong file.
"""

from __future__ import annotations

import json

import pytest

from merismos.fleet import DEFAULT_CEILING, ceiling_share, equity

OFFER = {"id": "offer-1", "title": "Bread", "quantity": 100, "unit": "kg", "category": "ambient"}


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        ("No single organisation receives more than **40%** of one offer.", 0.40),
        ("No member may receive more than **25%** of any single offer.", 0.25),
        ("The ceiling is 12.5 percent of any one offer.", 0.125),
        ("A member may take up to 100% when nobody else can collect.", 1.0),
    ],
)
def test_the_ceiling_is_whatever_this_network_wrote_down(policy, expected):
    share, source = ceiling_share(policy)

    assert share == expected
    assert source == "registers/allocation-policy.md"


@pytest.mark.parametrize(
    "policy",
    [
        "",
        "The rota is what matters here, and the ceiling is a matter for the members.",
        "A ceiling of 250% is not a share.",
        "We allocate 0% to nobody, which is not a ceiling.",
    ],
)
def test_a_filing_with_no_usable_ceiling_gets_a_stated_default(policy):
    """A default is fine. A silent default is not.

    A network with no policy file should get a documented ceiling rather than no
    ceiling at all, and the envelope has to say which of the two happened, or a
    coordinator cannot tell whether their own policy was the one applied.
    """
    share, source = ceiling_share(policy)

    assert share == DEFAULT_CEILING
    assert "default" in source
    assert source != "registers/allocation-policy.md"


def test_the_envelope_says_which_ceiling_it_used_and_where_it_came_from():
    envelope = equity(OFFER, [], (), "No member may receive more than **25%** of any offer.")

    assert envelope.meta["ceiling"] == 25.0
    assert envelope.meta["ceiling_share"] == 0.25
    assert envelope.meta["ceiling_from"] == "registers/allocation-policy.md"


def test_with_no_policy_the_envelope_still_names_the_ceiling_as_a_default():
    envelope = equity(OFFER, [], (), "")

    assert envelope.meta["ceiling"] == 40.0
    assert "default" in envelope.meta["ceiling_from"]


def test_a_different_networks_policy_changes_the_split(tmp_path):
    """End to end, on a filing this repository does not ship.

    The assertion persona 09 actually asks for: run it on input it did not ship
    with, and fail if the output is the same. 25% of 90 is 22.5 and 40% of 90 is
    36, so the two ceilings are distinguishable in the shares themselves.
    """
    from merismos.corpus import LocalCorpus
    from merismos.fleet import new_run_id, run_chore, subject_for_offer
    from merismos.ledger import InMemoryLedger, Thread

    for sub in ("orgs", "offers", "registers"):
        (tmp_path / sub).mkdir(parents=True)

    for org in (
        {"id": "big", "name": "Big Depot", "has_van": True, "vans": 2,
         "cold_storage_litres": 5000, "walk_in_limit_kg": 200, "same_day_service": True,
         "open_days": ["Monday"], "meals_served_daily": 0, "premises_constraints": []},
        {"id": "other", "name": "Other Depot", "has_van": True, "vans": 1,
         "cold_storage_litres": 5000, "walk_in_limit_kg": 200, "same_day_service": True,
         "open_days": ["Monday"], "meals_served_daily": 0, "premises_constraints": []},
    ):
        (tmp_path / "orgs" / f"{org['id']}.json").write_text(json.dumps(org), encoding="utf-8")

    offer = {
        "id": "offer-7000", "title": "Dry goods", "donor": "A wholesaler",
        "category": "ambient", "quantity": 90, "unit": "kg",
        "collection_date": "2026-10-02", "hours_unrefrigerated": 0, "allergens": [],
        "note": "Rice and lentils.",
    }
    (tmp_path / "offers" / "offer-7000.json").write_text(json.dumps(offer), encoding="utf-8")

    def split_under(policy: str) -> list[float]:
        (tmp_path / "registers" / "allocation-policy.md").write_text(policy, encoding="utf-8")
        corpus = LocalCorpus(tmp_path)
        thread = Thread(
            ledger=InMemoryLedger(),
            subject=subject_for_offer("other-network", offer),
            run_id=new_run_id(),
        )
        result = run_chore(corpus, offer, thread, network="other-network")
        return sorted(a["quantity"] for a in (result.draft.allocations if result.draft else []))

    strict = split_under("No member may receive more than **25%** of any single offer.")
    loose = split_under("No member may receive more than **40%** of any single offer.")

    assert strict == [22.5, 22.5], strict
    assert loose == [36.0, 36.0], loose
    assert strict != loose, (
        "two different networks' policies produced the same split, so the filing "
        "is not being read and the ceiling is still compiled in"
    )

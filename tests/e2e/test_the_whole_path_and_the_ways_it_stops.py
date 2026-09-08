"""One offer from a form to a collection, and the six ways it must stop instead.

The happy path here is the product's actual claim: a coordinator types what a
donor told them, the fleet interprets it, the split respects the register, a
person approves specific bytes, those bytes are published, and somebody
undertakes to collect. Every one of those steps existed before this file and none
of them had been walked end to end in a single test, which is part of how
offer-4471 managed to publish a share its own record said was forbidden.

The negative half is the more useful half. Each scenario names where it has to
stop and asserts it stopped **there**, because a run that fails for the wrong
reason is a run that will pass again as soon as the wrong reason goes away.
"""

from __future__ import annotations

import json

import pytest

from merismos import gate, intake, pickup
from merismos.approval import (
    AlreadySpent,
    BytesChanged,
    InMemoryApprovalStore,
    authorise,
    grant,
)
from merismos.corpus import LocalCorpus
from merismos.corpus import orgs as load_orgs
from merismos.envelope import Status
from merismos.fleet import food_safety, new_run_id, record_key, run_chore, subject_for_offer
from merismos.ledger import InMemoryLedger, Thread

NETWORK = "kypseli-network"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_MODEL", "none")


def chore(offer: dict):
    thread = Thread(
        ledger=InMemoryLedger(),
        subject=subject_for_offer(NETWORK, offer),
        run_id=new_run_id(),
    )
    return run_chore(LocalCorpus(), offer, thread, network=NETWORK)


def typed(**over) -> dict:
    form = {
        "title": "End of day bread and vegetables",
        "donor": "Neighbourhood bakery",
        "quantity": "240",
        "unit": "kg",
        "category": "ambient",
        "collection_date": "2026-09-14",
        "use_by": "2026-11-01",
        "allergens": "gluten, sesame",
        **over,
    }
    return intake.offer_from_form(form, "offer-9001")


def an_offer(offer_id: str) -> dict:
    return json.loads(LocalCorpus().read(f"offers/{offer_id}.json"))


# ==========================================================================
# The whole path.
# ==========================================================================


def test_a_typed_offer_reaches_a_collection_through_every_step():
    # 1. A coordinator types what the donor told them.
    offer = typed()
    assert offer["use_by"] == "2026-11-01"
    assert offer["allergens"] == ["gluten", "sesame"]

    # 2. The fleet interprets it and proposes a split.
    result = chore(offer)
    assert result.outcome == "awaiting_approval"
    assert result.draft is not None
    assert result.verdict.passed, result.verdict.findings

    # 3. The split respects the register: nobody over the ceiling, and every
    #    member either allocated or explained. "Explained" is the half a record
    #    without it turns into a phone call.
    shares = {a["org"]: float(a["quantity"]) for a in result.draft.allocations}
    assert shares, "an ordinary offer reached nobody"
    assert max(shares.values()) <= 240 * 0.40 + 0.01
    named = set(shares) | set(result.draft.barred_because)
    assert len(named) == 5, f"a member is neither allocated nor explained: {sorted(named)}"

    # 4. A person approves these exact bytes and nothing else.
    key = record_key("offer-9001", [])
    approval = grant(
        network=NETWORK,
        key=key,
        body=result.draft.body,
        approved_by="the coordinator on duty",
        run_id=result.run_id,
    )

    # 5. The writer re-derives the digest from what actually arrived.
    store = InMemoryApprovalStore()
    store.put(approval)
    authorised = authorise(store, approval.nonce, NETWORK, key, result.draft.body)
    assert authorised.nonce == approval.nonce

    # 6. Somebody undertakes to collect, and it is not finished until they say so.
    taken = pickup.claim(
        offer_id="offer-9001",
        org=next(iter(shares)),
        role="duty manager",
        allocations=result.draft.allocations,
        plan_digest=approval.content_digest,
        unit="kg",
        agreed_at="2026-09-14 18:00",
    )
    assert taken.state == "agreed"

    waiting = pickup.outstanding(result.draft.allocations, [taken], approval.content_digest)
    assert waiting["unconfirmed"], "a claim nobody confirmed is reading as finished"

    done = pickup.confirm(taken)
    final = pickup.outstanding(result.draft.allocations, [done], approval.content_digest)
    assert [c["org"] for c in final["confirmed"]] == [taken.org]


# ==========================================================================
# The six ways it has to stop, each at its own step.
# ==========================================================================


def test_expiry_stops_it_at_food_safety_rather_than_later():
    """Past its use by is refused in full: not reduced, not left for the gate."""
    offer = {**typed(), "use_by": "2026-09-13", "collection_date": "2026-09-14"}
    envelope = food_safety(offer, [{"name": "Omonoia Soup Kitchen", "same_day_service": True}])

    assert envelope.status is Status.BLOCKED
    assert "not after the collection date" in envelope.reason


def test_insufficient_transport_caps_the_share_rather_than_stopping_anything():
    """The one scenario in this list whose right answer is a smaller share.

    It is here because it reads like a stop and is not one. A member who can
    carry twenty kilos gets twenty kilos, and treating that as a veto is what
    dropped Elpida from an offer it was one of two members allowed to receive.
    """
    result = chore(typed())
    shares = {a["org"]: float(a["quantity"]) for a in result.draft.allocations}
    register = {o["name"]: o for o in load_orgs(LocalCorpus())}

    for org, qty in shares.items():
        if not register[org].get("has_van"):
            assert qty <= register[org]["walk_in_limit_kg"], f"{org} cannot carry {qty} kg"


def test_the_share_ceiling_holds_even_when_one_member_could_take_the_lot():
    """Omonoia can take a whole pallet. That is exactly why the ceiling exists."""
    result = chore(typed())
    largest = max(float(a["quantity"]) for a in result.draft.allocations)

    assert largest <= 240 * 0.40 + 0.01, "the 40% ceiling was exceeded"


def test_an_ineligible_organisation_is_stopped_by_the_gate_and_not_only_by_the_solver():
    """Corrupting the draft is the point of this one.

    The solver could be right and the system would still be one in which the only
    thing standing between a forbidden share and a published record is that the
    solver got it right. The gate re-checks the draft against the fleet's own
    exclusions, so a share to a barred member has to fail here too.
    """
    result = chore(an_offer("offer-4471"))
    assert "Kypseli Food Pantry" in result.draft.must_not_receive

    tampered = gate.Draft(
        body=result.draft.body,
        allocations=[{"org": "Kypseli Food Pantry", "quantity": 96.0, "reason": "x"}],
        offer=result.draft.offer,
        known_orgs=result.draft.known_orgs,
        must_not_receive=result.draft.must_not_receive,
    )

    findings = gate.check_exclusions_were_applied(tampered)

    assert findings, (
        "a share to an organisation the fleet itself barred passed the check that "
        "exists to catch exactly that"
    )
    assert any("Kypseli Food Pantry" in f.detail for f in findings)


def test_an_organisation_nobody_has_heard_of_is_stopped_too():
    """The other half of eligibility: a plausible name is not a member."""
    result = chore(an_offer("offer-4471"))
    invented = gate.Draft(
        body=result.draft.body,
        allocations=[{"org": "Kypseli Community Kitchen", "quantity": 10.0, "reason": "x"}],
        offer=result.draft.offer,
        known_orgs=result.draft.known_orgs,
        must_not_receive=result.draft.must_not_receive,
    )

    findings = gate.check_orgs_exist(invented)

    assert findings, "a plausible name that is not a member was allocated a share"
    assert any("Kypseli Community Kitchen" in f.detail for f in findings)


def test_incomplete_data_is_a_finding_and_never_a_pass():
    """Three kinds of missing, and none of them resolve into a safe default."""
    # The form refuses it first, which is the better place: the coordinator is
    # standing there and can ask the donor, rather than finding out minutes
    # later from a fleet that has already filed it.
    with pytest.raises(intake.Rejected) as caught:
        typed(category="chilled")
    assert "how many hours" in str(caught.value)

    # And the specialist refuses it too, for an offer that reached the corpus by
    # any other route. Two locks, because the form is not the only door.
    smuggled = {**typed(), "category": "chilled", "hours_unrefrigerated": None}
    assert food_safety(smuggled, []).status is Status.BLOCKED

    checks = {f.check for f in food_safety(typed(use_by=""), []).findings}
    assert "use-by-not-established" in checks

    assert typed(allergens="")["allergens"] is None, (
        "an empty list here would be a claim that somebody checked"
    )


def test_a_repeated_request_cannot_publish_the_same_approval_twice():
    """The nonce is spent by a conditional write, not by a check in the handler."""
    result = chore(typed())
    key = record_key("offer-9001", [])
    approval = grant(
        network=NETWORK,
        key=key,
        body=result.draft.body,
        approved_by="the coordinator on duty",
        run_id=result.run_id,
    )
    store = InMemoryApprovalStore()
    store.put(approval)

    authorise(store, approval.nonce, NETWORK, key, result.draft.body)

    with pytest.raises(AlreadySpent):
        authorise(store, approval.nonce, NETWORK, key, result.draft.body)


def test_a_repeated_request_with_different_bytes_is_refused_before_it_is_spent():
    """Order matters: an approval must not be consumed by a doomed request."""
    result = chore(typed())
    key = record_key("offer-9001", [])
    approval = grant(
        network=NETWORK,
        key=key,
        body=result.draft.body,
        approved_by="the coordinator on duty",
        run_id=result.run_id,
    )
    store = InMemoryApprovalStore()
    store.put(approval)

    with pytest.raises(BytesChanged):
        authorise(store, approval.nonce, NETWORK, key, result.draft.body + "\nand one more line")

    # Still spendable, because the refusal happened before the spend.
    assert authorise(store, approval.nonce, NETWORK, key, result.draft.body)

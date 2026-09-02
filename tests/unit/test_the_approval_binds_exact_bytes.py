"""An approval covers these bytes, this address, this long, once.

Each of the four is refused for a different reason and with a different status,
because a coordinator who gets a 403 for an expired approval will re-approve and
get another 403, and never find out that the clock is the problem.

Every fixture is built from a different literal than the one the code under test
uses, so a test cannot pass because it agreed with itself.
"""

from __future__ import annotations

import pytest

from mitos.approval import (
    AlreadySpent,
    BytesChanged,
    Expired,
    InMemoryApprovalStore,
    NotApproved,
    authorise,
    digest,
    grant,
)

NETWORK = "kypseli-network"
KEY = "records/offer-4471.md"
BODY = "# Allocation, offer-4471\n\nKypseli Food Pantry: 96 kg\nOmonoia Soup Kitchen: 96 kg\n"


@pytest.fixture
def store() -> InMemoryApprovalStore:
    return InMemoryApprovalStore()


@pytest.fixture
def approved(store: InMemoryApprovalStore):
    approval = grant(NETWORK, KEY, BODY, approved_by="the coordinator", run_id="run-1")
    store.put(approval)
    return approval


def test_the_approved_bytes_are_authorised(store, approved):
    result = authorise(store, approved.nonce, NETWORK, KEY, BODY)

    assert result.approved_by == "the coordinator"


def test_one_changed_character_is_refused(store, approved):
    tampered = BODY.replace("96 kg", "196 kg")

    with pytest.raises(BytesChanged):
        authorise(store, approved.nonce, NETWORK, KEY, tampered)


def test_a_trailing_newline_is_a_different_document(store, approved):
    """Whitespace is bytes. An approval over bytes has to mean it."""
    with pytest.raises(BytesChanged):
        authorise(store, approved.nonce, NETWORK, KEY, BODY + "\n")


def test_the_same_bytes_at_a_different_address_are_refused(store, approved):
    with pytest.raises(BytesChanged):
        authorise(store, approved.nonce, NETWORK, "records/offer-9999.md", BODY)


def test_an_unknown_nonce_is_refused(store):
    with pytest.raises(NotApproved):
        authorise(store, "0" * 32, NETWORK, KEY, BODY)


def test_an_expired_approval_is_refused_and_says_so_distinctly(store):
    """410, not 403. The coordinator needs to know the clock is the problem."""
    approval = grant(
        NETWORK, KEY, BODY, approved_by="the coordinator", run_id="run-1", now=1000.0
    )
    store.put(approval)

    with pytest.raises(Expired) as raised:
        authorise(store, approval.nonce, NETWORK, KEY, BODY, now=1000.0 + 901)

    assert raised.value.status == 410


def test_an_approval_authorises_exactly_one_write(store, approved):
    authorise(store, approved.nonce, NETWORK, KEY, BODY)

    with pytest.raises(AlreadySpent) as raised:
        authorise(store, approved.nonce, NETWORK, KEY, BODY)

    assert raised.value.status == 409


def test_a_refused_request_does_not_consume_the_approval(store, approved):
    """The spend is last, so a request refused for another reason costs nothing."""
    with pytest.raises(BytesChanged):
        authorise(store, approved.nonce, NETWORK, KEY, BODY.replace("96", "97"))

    assert authorise(store, approved.nonce, NETWORK, KEY, BODY).run_id == "run-1"


def test_an_approval_cannot_be_granted_without_naming_a_person():
    with pytest.raises(ValueError):
        grant(NETWORK, KEY, BODY, approved_by="   ", run_id="run-1")


def test_the_digest_cannot_be_collided_by_moving_a_delimiter():
    """Length prefixing is why. Without it these two would hash the same."""
    left = digest(NETWORK, "records/a", "b" + BODY)
    right = digest(NETWORK, "records/ab", BODY)

    assert left != right

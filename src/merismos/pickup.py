"""What happens after a person approves, which is where the work actually is.

A published record is not a collection. Until somebody has said "we will take
the shelter's twenty kilos, Thursday at six", the network has a decision and no
van, and the phone calls this product exists to remove start again around the
decision rather than around the split.

**Three facts close a share, and the third is the one that has to be allowed to
stay open.** Who is taking it, when, and whether it actually happened. A
coordinator on Friday morning needs to see the shares nobody has claimed and the
collections nobody confirmed, in the same list, because those are the two ways a
decision quietly fails to become food.

**No person appears here.** The register says the published record carries
organisations and quantities and never a name, address or phone number, and a
collection is exactly where a name would be convenient to record. So a claim
names an **organisation and a role**, "Elpida Night Shelter, duty manager", and
the role is one of a fixed set rather than free text, because free text is where
"ring Maria on 694..." ends up. The person's name lives in the group chat that
is already open, which is where it should live.

**A claim does not survive a change to what was claimed.** If the offer changes
or the plan is recomputed, the shares are not the shares anybody agreed to
collect, so the claims against them are void and say so. That is the same rule
as the approval nonce and for the same reason: an agreement is about specific
bytes, and bytes that changed are a different agreement.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: Who inside an organisation can be named. A fixed set, because the field
#: exists to say which door to knock on and free text is where a person's name
#: and mobile number arrive.
ROLES = (
    "duty manager",
    "kitchen lead",
    "volunteer coordinator",
    "warehouse",
    "trustee on call",
)

#: How long a claim stands before it stops meaning anything. A collection agreed
#: three weeks ago and never confirmed is not a plan, it is a hope.
CLAIM_VALID_FOR_DAYS = 14


class NotClaimable(ValueError):
    """Raised when a claim cannot stand: unknown org, unknown role, or void."""


@dataclass(frozen=True)
class Claim:
    """One organisation undertaking to collect one share.

    ``plan_digest`` is what ties it to the split that was agreed. It is the same
    digest the approval was minted over, so a recomputed plan invalidates the
    claim without anybody having to remember to go and cancel it.
    """

    offer_id: str
    org: str
    role: str
    quantity: float
    unit: str
    plan_digest: str
    agreed_at: str = ""
    claimed_at: float = field(default_factory=time.time)
    confirmed_at: float | None = None

    @property
    def state(self) -> str:
        """``confirmed``, ``agreed`` or ``claimed``. Never ``done`` by default."""
        if self.confirmed_at is not None:
            return "confirmed"
        return "agreed" if self.agreed_at else "claimed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "org": self.org,
            "role": self.role,
            "quantity": self.quantity,
            "unit": self.unit,
            "plan_digest": self.plan_digest,
            "agreed_at": self.agreed_at,
            "claimed_at": self.claimed_at,
            "confirmed_at": self.confirmed_at,
            "state": self.state,
        }


def claim(
    *,
    offer_id: str,
    org: str,
    role: str,
    allocations: Sequence[Mapping[str, Any]],
    plan_digest: str,
    unit: str,
    agreed_at: str = "",
) -> Claim:
    """Record that an organisation will collect its share, or refuse and say why.

    The share is read from the plan rather than accepted from the caller. An
    organisation collecting a quantity nobody allocated to it is the whole
    failure mode, and taking the number from the request would be trusting the
    van to say how much it is owed.
    """
    org = str(org).strip()
    role = str(role).strip().lower()

    if role not in ROLES:
        raise NotClaimable(
            f"{role!r} is not a role this network records. Use one of: "
            f"{', '.join(ROLES)}. A person's name does not go here."
        )

    share = next((a for a in allocations if str(a.get("org", "")) == org), None)
    if share is None:
        raise NotClaimable(
            f"{org} has no share of {offer_id} to collect. A collection that "
            f"nobody was allocated is how a rule gets applied on paper and "
            f"ignored in the yard."
        )
    if not plan_digest:
        raise NotClaimable(
            "a claim has to name the plan it is against, or a recomputed plan "
            "leaves an agreement standing over shares nobody agreed to"
        )

    return Claim(
        offer_id=offer_id,
        org=org,
        role=role,
        quantity=float(share.get("quantity") or 0),
        unit=unit,
        plan_digest=plan_digest,
        agreed_at=str(agreed_at or ""),
    )


def confirm(existing: Claim, at: float | None = None) -> Claim:
    """Somebody collected it. The only place a share becomes food."""
    if existing.confirmed_at is not None:
        return existing
    return Claim(
        offer_id=existing.offer_id,
        org=existing.org,
        role=existing.role,
        quantity=existing.quantity,
        unit=existing.unit,
        plan_digest=existing.plan_digest,
        agreed_at=existing.agreed_at,
        claimed_at=existing.claimed_at,
        confirmed_at=time.time() if at is None else at,
    )


def still_valid(existing: Claim, plan_digest: str, now: float | None = None) -> bool:
    """Whether this claim still describes the plan that is current.

    Two ways it stops. The plan was recomputed, so the shares are not the shares
    anybody agreed to collect. Or it simply aged out, because an unconfirmed
    collection from a fortnight ago tells a coordinator nothing.
    """
    if existing.plan_digest != plan_digest:
        return False
    now = time.time() if now is None else now
    return (now - existing.claimed_at) <= CLAIM_VALID_FOR_DAYS * 86400


def outstanding(
    allocations: Sequence[Mapping[str, Any]],
    claims: Sequence[Claim],
    plan_digest: str,
    now: float | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """What still needs somebody, in the two ways a decision fails to become food.

    ``unclaimed`` is a share nobody has undertaken to collect. ``unconfirmed`` is
    one somebody undertook and nobody has said arrived. A coordinator wants both
    on one screen on a Friday morning, and neither is visible from a record that
    only says who was allocated what.
    """
    live = [c for c in claims if still_valid(c, plan_digest, now)]
    claimed = {c.org for c in live}

    return {
        "unclaimed": [
            {"org": str(a.get("org", "")), "quantity": a.get("quantity")}
            for a in allocations
            if str(a.get("org", "")) not in claimed
        ],
        "unconfirmed": [c.as_dict() for c in live if c.confirmed_at is None],
        "confirmed": [c.as_dict() for c in live if c.confirmed_at is not None],
        "void": [c.as_dict() for c in claims if c not in live],
    }

"""What a specialist hands back, and what it is not allowed to hand back.

A fleet whose agents can only succeed produces an answer for every item,
including the ones where the honest answer is that a person has to look. So the
status is one of four, ``blocked`` and ``needs_changes`` are first-class
outcomes rather than errors, and a refusal without a reason raises at
construction rather than reaching a coordinator that has to guess.

Nothing here imports an SDK. The domain does not know what a Bedrock is.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any


class Status(str, Enum):
    """The four things a specialist may conclude."""

    OK = "ok"
    NEEDS_CHANGES = "needs_changes"
    BLOCKED = "blocked"
    ERROR = "error"

    @property
    def is_refusal(self) -> bool:
        """True when the status is one a person has to resolve."""
        return self in (Status.NEEDS_CHANGES, Status.BLOCKED, Status.ERROR)


class RefusalWithoutReason(ValueError):
    """Raised when an envelope refuses and names nothing.

    A refusal a coordinator cannot explain to the person waiting on it is worse
    than no refusal, because it stops the work and teaches nobody anything.
    """


@dataclass(frozen=True)
class Finding:
    """One thing a specialist noticed, at one severity, about one subject."""

    check: str
    severity: str
    detail: str
    evidence: str = ""

    SEVERITIES = ("low", "medium", "high")

    def __post_init__(self) -> None:
        if not self.check.strip():
            raise ValueError("a finding names the check that produced it")
        if self.severity not in self.SEVERITIES:
            raise ValueError(
                f"severity {self.severity!r} is not one of {self.SEVERITIES}"
            )
        if not self.detail.strip():
            raise ValueError(f"finding {self.check!r} carries no detail")

    def as_dict(self) -> dict[str, str]:
        """The shape that reaches the ledger and the approval card."""
        return {
            "check": self.check,
            "severity": self.severity,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class Envelope:
    """A specialist's whole answer, including the answer that it will not answer.

    ``reason`` is required whenever ``status`` refuses. That is checked here and
    not in a review comment, because a review comment is not a control.
    """

    specialist: str
    status: Status
    reason: str = ""
    findings: tuple[Finding, ...] = ()
    notes: str = ""
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.specialist.strip():
            raise ValueError("an envelope names the specialist that produced it")
        if self.status.is_refusal and not self.reason.strip():
            raise RefusalWithoutReason(
                f"{self.specialist} returned {self.status.value} and named no reason"
            )

    @property
    def blocks(self) -> bool:
        """True when this envelope alone stops the run from proposing anything."""
        return self.status is Status.BLOCKED

    def union(self, other: Envelope) -> Envelope:
        """Combine two reads of the same subject, tightening only.

        The severity of the result is the stricter of the two and never the
        looser one, findings are added and never removed, and a reason that
        exists is never replaced by one that does not. A model contributing
        through this method can make the fleet more careful and cannot make it
        less careful. That is ADR-002 expressed as a function rather than as an
        instruction in a prompt, so there is no branch to argue with.
        """
        if other.specialist != self.specialist:
            raise ValueError(
                f"cannot union {self.specialist!r} with {other.specialist!r}"
            )
        status = _stricter(self.status, other.status)
        reason = self.reason or other.reason
        if status.is_refusal and not reason.strip():
            raise RefusalWithoutReason(
                f"{self.specialist} unioned to {status.value} and named no reason"
            )
        return replace(
            self,
            status=status,
            reason=reason,
            findings=_merge(self.findings, other.findings),
            notes="\n".join(part for part in (self.notes, other.notes) if part),
            meta={**dict(self.meta), **dict(other.meta)},
        )

    def as_dict(self) -> dict[str, Any]:
        """The shape that reaches the ledger and the approval card."""
        return {
            "specialist": self.specialist,
            "status": self.status.value,
            "reason": self.reason,
            "findings": [finding.as_dict() for finding in self.findings],
            "notes": self.notes,
            "meta": dict(self.meta),
        }

    def as_json(self) -> str:
        """Pretty-printed, because a judge reads these (STANDARDS F8)."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


# Ordered loosest to strictest. ``union`` moves right and never left.
_ORDER = (Status.OK, Status.NEEDS_CHANGES, Status.ERROR, Status.BLOCKED)


def _stricter(left: Status, right: Status) -> Status:
    """Return whichever of the two statuses stops more work."""
    return max(left, right, key=_ORDER.index)


def _merge(left: Iterable[Finding], right: Iterable[Finding]) -> tuple[Finding, ...]:
    """Concatenate findings, dropping exact repeats and keeping first order.

    Deduplicating on the whole finding rather than on ``check`` is deliberate:
    two specialists reaching the same conclusion about different evidence is two
    findings, and collapsing them would hide the corroboration.
    """
    seen: set[tuple[str, str, str, str]] = set()
    out: list[Finding] = []
    for finding in (*left, *right):
        key = (finding.check, finding.severity, finding.detail, finding.evidence)
        if key not in seen:
            seen.add(key)
            out.append(finding)
    return tuple(out)


def worst(envelopes: Iterable[Envelope]) -> Status:
    """The status of a run, which is the strictest status any specialist reached.

    An empty fleet is ``OK``, and the caller decides whether an empty fleet was
    the right answer. That decision is in ``fleet.py`` and it is a real one: a
    run with nothing to govern says so rather than manufacturing an empty draft.
    """
    statuses = [envelope.status for envelope in envelopes]
    if not statuses:
        return Status.OK
    return max(statuses, key=_ORDER.index)

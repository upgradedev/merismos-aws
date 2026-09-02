"""The deterministic gate. Regular expressions and arithmetic, never a judgement.

Two reasons it is not a model.

The first is that the record this fleet publishes is **public**, and the thing
that must never reach it is a beneficiary's name, phone number or address. A
detector that is right most of the time is not a control over a permanent public
write.

The second is that the demo has to reject on every take. A rejection that
depends on the model misbehaving is a demo that works until the one recording
you keep. So the poison is planted in the corpus instead, a faithful generator
carries it forward, and this catches it every time with no credential.

The order in ``judge`` is load bearing and is the correction mitos-gcp shipped
too late. The deterministic verdict runs **first, always**. A refusal returns
without consulting the model at all, because asking and discarding the answer
costs a request and invites a later edit that uses it. Where the rules pass, a
model's opinion is unioned in and can only add. There is no branch here that
clears a finding.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .envelope import Finding

# --------------------------------------------------------------------------
# Personal data. The record is published to a public address, so this is the
# detector that guards the irreversible thing.
# --------------------------------------------------------------------------

# Greek and international mobile shapes, and a generic long digit run that
# would be a phone number or a case reference either way.
_PHONE = re.compile(r"(?:(?:\+|00)\d{1,3}[\s.-]?)?(?:\d[\s.-]?){9,14}\d")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A street line: a number attached to a word that looks like a thoroughfare.
_STREET = re.compile(
    r"\b\d{1,4}[A-Za-z]?\s+[A-Z][A-Za-z'-]+\s+"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Odos|Leoforos)\b",
    re.IGNORECASE,
)
# A national identifier: the Greek AMKA is 11 digits, a UK NI number has a
# distinctive shape. Both are things a volunteer might paste into a note.
_NATIONAL_ID = re.compile(
    r"\b(?:AMKA|A\.M\.K\.A\.?|NI(?:NO)?)\s*[:#]?\s*[A-Z0-9]{8,12}\b", re.IGNORECASE
)
# A household named as a recipient rather than counted.
_NAMED_HOUSEHOLD = re.compile(
    r"\b(?:for|to|deliver(?:ed)?\s+to|collected\s+by)\s+"
    r"(?:Mr|Mrs|Ms|Miss|Dr|Kyria|Kyrios)\.?\s+[A-Z][A-Za-z'-]+",
)

# --------------------------------------------------------------------------
# Instructions aimed at the fleet rather than at a person. A donor's note is
# untrusted text: it arrives from outside and is read by an agent.
# --------------------------------------------------------------------------

_INJECTION = re.compile(
    r"(?:"
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous\s+|prior\s+|above\s+)?"
    r"(?:instruction|rule|polic|direction)"
    r"|disregard\s+(?:the\s+)?(?:rule|polic|instruction|guidance)"
    r"|you\s+are\s+now\s+(?:a|an|the)\b"
    r"|system\s*(?:prompt|message)\s*[:=]"
    r"|new\s+instructions?\s*[:=]"
    r"|as\s+an\s+ai\b"
    r")",
    re.IGNORECASE,
)

_BYPASS = re.compile(
    r"(?:"
    r"(?:skip|bypass|disable|turn\s+off|override|suppress)\s+"
    r"(?:the\s+)?(?:gate|guard|check|review|approval|evaluat|safeguard)"
    r"|(?:no|without)\s+(?:human\s+)?(?:approval|review|sign[\s-]?off)\s+"
    r"(?:is\s+)?(?:needed|required|necessary)"
    r"|auto[\s-]?approve"
    r"|mark\s+(?:this\s+)?as\s+approved"
    r")",
    re.IGNORECASE,
)

_CREDENTIAL = re.compile(
    r"(?:"
    r"AKIA[0-9A-Z]{16}"
    r"|ASIA[0-9A-Z]{16}"
    r"|aws_secret_access_key\s*[:=]"
    r"|-{5}BEGIN\s+(?:RSA\s+|EC\s+|OPENSSH\s+)?PRIVATE\s+KEY-{5}"
    r"|xox[baprs]-[0-9A-Za-z-]{10,}"
    r"|gh[pousr]_[0-9A-Za-z]{30,}"
    r")",
)


@dataclass(frozen=True)
class Verdict:
    """What the gate concluded, and whether anything may be proposed."""

    passed: bool
    findings: tuple[Finding, ...] = ()
    injection_detected: bool = False
    advisories: tuple[str, ...] = ()
    critic_model: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "findings": [finding.as_dict() for finding in self.findings],
            "injection_detected": self.injection_detected,
            "advisories": list(self.advisories),
            "critic_model": self.critic_model,
        }

    @property
    def blocking(self) -> tuple[Finding, ...]:
        """The findings that are the reason ``passed`` is false."""
        return tuple(f for f in self.findings if f.severity == "high")


@dataclass
class Draft:
    """What the fleet proposes to publish, before anyone has approved it.

    ``must_not_receive`` is the union of every exclusion the specialists
    computed. It is carried separately from the body rather than trusted to have
    been applied, so that the gate can check the draft against the fleet's own
    reasoning instead of against its own prose.
    """

    body: str
    allocations: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    offer: Mapping[str, Any] = field(default_factory=dict)
    known_orgs: frozenset[str] = frozenset()
    must_not_receive: frozenset[str] = frozenset()

    @property
    def untrusted_text(self) -> str:
        """Every string that came from outside the fleet.

        The donor's note is the obvious one. The organisation names travel with
        it because an org record is edited by the org, not by us.
        """
        parts = [str(self.offer.get("note", "")), str(self.offer.get("title", ""))]
        for allocation in self.allocations:
            parts.append(str(allocation.get("note", "")))
        return "\n".join(parts)


def check_personal_data(draft: Draft) -> list[Finding]:
    """Refuse anything that would put a person into a permanent public record."""
    findings: list[Finding] = []
    body = draft.body
    probes = (
        ("no-email", _EMAIL, "an email address"),
        ("no-street-address", _STREET, "a street address"),
        ("no-national-id", _NATIONAL_ID, "a national identifier"),
        ("no-named-household", _NAMED_HOUSEHOLD, "a named household"),
    )
    for check, pattern, what in probes:
        match = pattern.search(body)
        if match:
            findings.append(
                Finding(
                    check=check,
                    severity="high",
                    detail=(
                        f"the record carries {what}, and the record is published "
                        f"to a public address where it cannot be recalled"
                    ),
                    evidence=_redact(match.group(0)),
                )
            )
    # Phone numbers are checked separately because quantities and dates produce
    # long digit runs, so the match has to survive a look at what it caught.
    for match in _PHONE.finditer(body):
        candidate = match.group(0)
        if _is_probably_a_phone_number(candidate, body, match.start()):
            findings.append(
                Finding(
                    check="no-phone-number",
                    severity="high",
                    detail=(
                        "the record carries what reads as a phone number, and the "
                        "record is published to a public address"
                    ),
                    evidence=_redact(candidate),
                )
            )
            break
    return findings


def _is_probably_a_phone_number(candidate: str, body: str, at: int) -> bool:
    """Reject the digit runs that are quantities, dates or identifiers.

    A false positive here blocks a legitimate publish, which is the safe
    direction but is still a cost, so the cheap disqualifiers are applied.
    """
    digits = re.sub(r"\D", "", candidate)
    if not 10 <= len(digits) <= 15:
        return False
    if "-" in candidate and re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", candidate.strip()):
        return False  # an ISO date
    preceding = body[max(0, at - 24) : at].lower()
    quantity_word = re.compile(r"\b(?:kg|kilo|units?|portions?|meals?|ref|id|qty)\b\W*$")
    return not quantity_word.search(preceding)


def check_untrusted_instructions(draft: Draft) -> list[Finding]:
    """Find text that is talking to the fleet instead of describing the goods."""
    findings: list[Finding] = []
    text = draft.untrusted_text
    match = _INJECTION.search(text)
    if match:
        findings.append(
            Finding(
                check="no-injected-instruction",
                severity="high",
                detail=(
                    "the offer text contains an instruction aimed at the fleet "
                    "rather than a description of the goods"
                ),
                evidence=_redact(match.group(0)),
            )
        )
    for source, label in ((text, "the offer text"), (draft.body, "the draft record")):
        match = _BYPASS.search(source)
        if match:
            findings.append(
                Finding(
                    check="no-guardrail-bypass",
                    severity="high",
                    detail=f"{label} asks for a control to be skipped",
                    evidence=_redact(match.group(0)),
                )
            )
    return findings


def check_credentials(draft: Draft) -> list[Finding]:
    """A credential in a record that is about to be published in public."""
    match = _CREDENTIAL.search(draft.body)
    if not match:
        return []
    return [
        Finding(
            check="no-credential",
            severity="high",
            detail="the draft record carries something shaped like a credential",
            evidence="[redacted, matched " + _CREDENTIAL.pattern[:12] + "...]",
        )
    ]


def check_arithmetic(draft: Draft) -> list[Finding]:
    """Refuse an allocation that promises more than the offer holds.

    Arithmetic rather than judgement, and it is the check that stops two vans
    being sent for one pallet. A model asked to be fair will happily allocate
    120% of a pallet across four organisations and describe it warmly.
    """
    findings: list[Finding] = []
    offered = _number(draft.offer.get("quantity"))
    if offered is None:
        return findings
    total = 0.0
    for allocation in draft.allocations:
        share = _number(allocation.get("quantity"))
        if share is None:
            findings.append(
                Finding(
                    check="allocation-has-a-quantity",
                    severity="high",
                    detail=(
                        f"the share for {allocation.get('org', 'an organisation')} "
                        f"carries no quantity, so nobody knows what was promised"
                    ),
                )
            )
            continue
        if share <= 0:
            findings.append(
                Finding(
                    check="allocation-is-positive",
                    severity="high",
                    detail=(
                        f"the share for {allocation.get('org', 'an organisation')} "
                        f"is {share}, which is not something anyone can collect"
                    ),
                )
            )
        total += share
    if total > offered + 1e-9:
        findings.append(
            Finding(
                check="allocation-fits-the-offer",
                severity="high",
                detail=(
                    f"the shares total {_pretty(total)} against an offer of "
                    f"{_pretty(offered)}. Somebody would drive to an empty bay"
                ),
                evidence=f"{_pretty(total)} > {_pretty(offered)}",
            )
        )
    return findings


def check_orgs_exist(draft: Draft) -> list[Finding]:
    """Refuse a share allocated to an organisation nobody has heard of.

    The equivalent of mitos-gcp's hallucinated-path check, and it matters more
    here: a plausible name for a charity that does not exist is much easier to
    produce than a plausible file path, and much harder for a tired coordinator
    to notice at 22:00.
    """
    if not draft.known_orgs:
        return []
    findings: list[Finding] = []
    for allocation in draft.allocations:
        org = str(allocation.get("org", "")).strip()
        if org and org not in draft.known_orgs:
            findings.append(
                Finding(
                    check="org-is-on-the-register",
                    severity="high",
                    detail=(
                        f"{org!r} is not an organisation in this network's "
                        f"register, so no share may be allocated to it"
                    ),
                    evidence=org,
                )
            )
    return findings


def check_exclusions_were_applied(draft: Draft) -> list[Finding]:
    """Refuse a draft that gives a share to somebody the fleet already excluded.

    This check exists because the fleet failed it. On offer-4483 the premises
    specialist read the manifest, found wine, pork and hazelnut inside a gift
    hamper, and raised three high findings. The draft then allocated a share to
    all five members, including the three whose premises exclude alcohol. Every
    other check passed, because nothing in the record's text was wrong: the
    prose was accurate and the allocation was not.

    So the gate compares the draft against the fleet's own conclusions rather
    than against its own prose. Computing an exclusion and not applying it is
    now a refusal instead of a silence, and it is caught here even if the code
    that builds the draft is changed later by somebody who does not know why.
    """
    if not draft.must_not_receive:
        return []
    findings: list[Finding] = []
    for allocation in draft.allocations:
        org = str(allocation.get("org", "")).strip()
        if org in draft.must_not_receive:
            findings.append(
                Finding(
                    check="exclusion-was-applied",
                    severity="high",
                    detail=(
                        f"{org} was excluded by a specialist and is still "
                        f"receiving a share. The fleet reached the right "
                        f"conclusion and the draft does not carry it"
                    ),
                    evidence=org,
                )
            )
    return findings


def check_non_empty(draft: Draft) -> list[Finding]:
    """An empty record is refused.

    ``fleet.py`` is responsible for never manufacturing an empty draft out of a
    run that had nothing to allocate. That run says so and stops before it
    reaches here. This check stays strict rather than being widened to tolerate
    the empty case, because widening a gate to make it pass is how a gate stops
    meaning anything.
    """
    if draft.body.strip() and draft.allocations:
        return []
    return [
        Finding(
            check="non-empty",
            severity="high",
            detail="the draft record allocates nothing and says nothing",
        )
    ]


#: Every deterministic check, run in this order. A check is added here or it
#: does not run; there is no registration by decoration, because a decorator
#: that silently fails to import is a check that silently stops existing.
CHECKS: tuple[Callable[[Draft], list[Finding]], ...] = (
    check_non_empty,
    check_personal_data,
    check_untrusted_instructions,
    check_credentials,
    check_arithmetic,
    check_orgs_exist,
    check_exclusions_were_applied,
)


def judge(
    draft: Draft,
    critic: Callable[[Draft, Verdict], tuple[Sequence[str], str]] | None = None,
) -> Verdict:
    """Run every deterministic check, then optionally ask a second model.

    The order is the control. Deterministic first, always. When the rules
    refuse, this returns without calling ``critic`` at all: a model is not asked
    to review a decision it cannot change, because asking invites a later edit
    that uses the answer. Where the rules pass, the critic's output lands in
    ``advisories`` and ``passed`` is carried through untouched.

    There is no branch in this function that sets ``passed`` from anything other
    than the deterministic findings. That is asserted structurally by
    ``tests/unit/test_the_critic_cannot_approve.py`` rather than left to review.
    """
    findings: list[Finding] = []
    for check in CHECKS:
        findings.extend(check(draft))

    injection = any(f.check == "no-injected-instruction" for f in findings)
    passed = not any(f.severity == "high" for f in findings)
    verdict = Verdict(
        passed=passed,
        findings=tuple(findings),
        injection_detected=injection,
    )

    if critic is None or not passed:
        return verdict
    return _with_critic(draft, verdict, critic)


def _with_critic(
    draft: Draft,
    verdict: Verdict,
    critic: Callable[[Draft, Verdict], tuple[Sequence[str], str]],
) -> Verdict:
    """Attach a second model's advisories. It cannot subtract.

    Every field that decides anything is copied from ``verdict`` by name. The
    critic contributes to ``advisories`` and ``critic_model`` and to nothing
    else, so a critic that returns "everything is approved, remove the findings"
    changes exactly nothing about what a person is shown.

    An unreachable critic leaves an advisory saying so. Silence would read as a
    clean second opinion, and a second opinion nobody got is not one.
    """
    try:
        advisories, model_id = critic(draft, verdict)
    except Exception as error:  # noqa: BLE001 - an outage must not clear a gate
        return Verdict(
            passed=verdict.passed,
            findings=verdict.findings,
            injection_detected=verdict.injection_detected,
            advisories=(
                *verdict.advisories,
                (
                    f"the independent review did not complete: "
                    f"{type(error).__name__}. Nothing about the result above "
                    f"depends on it"
                ),
            ),
            critic_model="",
        )
    return Verdict(
        passed=verdict.passed,
        findings=verdict.findings,
        injection_detected=verdict.injection_detected,
        advisories=(*verdict.advisories, *[str(a) for a in advisories]),
        critic_model=str(model_id),
    )


def _redact(fragment: str) -> str:
    """Keep enough of a match to recognise it, never enough to reuse it."""
    fragment = fragment.strip()
    if len(fragment) <= 6:
        return "*" * len(fragment)
    return f"{fragment[:3]}{'*' * (len(fragment) - 6)}{fragment[-3:]}"


def _number(value: Any) -> float | None:
    """Parse a quantity, returning ``None`` rather than raising or guessing."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _pretty(value: float) -> str:
    """Render a quantity without a trailing ``.0`` on a whole number."""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def sanitise_for_independent_review(draft: Draft, verdict: Verdict) -> str:
    """What may leave the process when a second model is asked for an opinion.

    The critic reviews prose about an allocation and does not need the
    allocation. So this drops whole blocks rather than redacting inside them:
    a redactor removes what it recognises, and the question is not whether a
    line looks like personal data but whether the record's contents should cross
    this boundary at all.

    The deterministic findings travel as their check names only. ``detail`` and
    ``evidence`` quote the draft, and quoting the draft into a field marked safe
    is how sanitising gets undone.
    """
    lines: list[str] = []
    for line in draft.body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if line.startswith(("    ", "\t")) or stripped.startswith("```"):
            continue
        if _EMAIL.search(line) or _STREET.search(line) or _NATIONAL_ID.search(line):
            continue
        lines.append(stripped)
    summary = "\n".join(lines)[:2000]
    checks = ", ".join(sorted({f.check for f in verdict.findings})) or "none"
    return (
        f"An allocation of donated surplus across community organisations.\n"
        f"Deterministic checks already raised: {checks}\n"
        f"Shares proposed: {len(draft.allocations)}\n\n"
        f"{summary}"
    )

"""The router, the specialists, and the chore that runs them.

The deterministic verdict is the floor. It runs first, always, for each woken
specialist. Where a specialist's rules refuse, that specialist is **not sent to
a model**, because asking and discarding the answer costs a request and invites
a later edit that uses it. The other woken specialists are still sent when a
model is configured, and a run with any refusal then stops before the draft
gate. Where a specialist's rules pass, a model's answer is unioned in through
``Envelope.union``, which tightens and cannot loosen.

This ordering is easy to get backwards and the failure is silent. Write it as
"run the deterministic rules unless an analyst is configured" and the model
branch returns before the rules are ever reached, so in production the rules do
not execute at all and the model's answer is the whole answer. What is lost is
exactly the set of refusals that exist because a model's opinion is not good
enough: here, an irreversible cold-chain break and an absolute premises
constraint.

A suite can agree with that bug indefinitely. Exercise the deterministic path
with no model, and the model path with a stub, and both pass; the two are never
crossed on an input the rules refuse.
``test_the_model_cannot_clear_a_refusal.py`` crosses them, through ``run_chore``
rather than through the helper, because a helper can look correct in isolation
and the chore is what the handler actually calls.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from . import gate
from .approval import Approval, grant
from .corpus import Corpus, org_names
from .deferral import Deferral, NullScheduler
from .envelope import Envelope, Finding, Status, worst
from .ledger import Thread
from .solver import AllocationSolution, solve_allocation
from .tools import READ_BUDGET, ReadLog, Toolbox, bounded_read

#: Which specialist cares about which category of offer. The router reads this
#: rather than a chain of conditionals, so adding a specialist changes behaviour
#: rather than requiring an edit to the router.
CATALOGUE: dict[str, dict[str, Any]] = {
    "food-safety": {
        "wakes_for": ("chilled", "frozen", "produce", "ambient"),
        "reads": ("registers/food-safety.md",),
        "why": "cold chain and use-by are arithmetic, and the failure makes someone ill",
    },
    "capacity": {
        "wakes_for": ("chilled", "frozen", "produce", "ambient", "non-food"),
        "reads": ("orgs/",),
        "why": "a share nobody can store or carry is a share that rots in a doorway",
    },
    "equity": {
        "wakes_for": ("chilled", "frozen", "produce", "ambient", "non-food"),
        "reads": ("registers/allocation-policy.md",),
        "why": "the ceiling and the rota are what stop the largest member taking everything",
    },
    "premises": {
        "wakes_for": ("ambient", "non-food", "chilled", "frozen", "produce"),
        "reads": ("orgs/", "offers/manifests/"),
        "why": (
            "premises constraints are absolute and cannot be read off an offer "
            "title. This is the specialist that has to open the manifest"
        ),
    },
}


def catalogue() -> dict[str, Any]:
    """What ``GET /catalog`` serves. A queried structure, not a table in a doc.

    ``reads`` is what a specialist is **expected** to consult. It is not a
    permission and was described as one until 2026-09-09: the enforced bound is
    ``tools.DEFAULT_SCOPE``, which is per run rather than per specialist, and
    every specialist holds all of it.

    Enforcing these lists would be wrong as well as narrower. On a live run the
    premises specialist opened ``offers/offer-4471.json``, which is not in its
    list, and refusing that read would have broken a correct run in order to make
    a sentence true.
    """
    from .tools import DEFAULT_SCOPE

    return {
        "reads_is_expected_not_enforced": (
            f"each specialist's `reads` is what it is expected to consult. The "
            f"enforced bound is {list(DEFAULT_SCOPE)}, and it is per run rather "
            f"than per specialist"
        ),
        "specialists": {
            name: {
                "wakes_for": list(spec["wakes_for"]),
                "reads": list(spec["reads"]),
                "why": spec["why"],
            }
            for name, spec in CATALOGUE.items()
        }
    }


def route(offer: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Decide who wakes and who is skipped, and be able to say why for both.

    Returns ``(woken, skipped)``. A skipped specialist is named in the published
    record, because a decision nobody can see is a decision that gets
    re-litigated by phone.
    """
    category = str(offer.get("category", "")).strip().lower()
    woken = [n for n, s in CATALOGUE.items() if category in s["wakes_for"]]
    skipped = [n for n in CATALOGUE if n not in woken]
    return sorted(woken), sorted(skipped)


# --------------------------------------------------------------------------
# The deterministic specialists. Each returns an Envelope and each may refuse.
# --------------------------------------------------------------------------


def _finding(check: str, severity: str, detail: str, evidence: str = "") -> Finding:
    return Finding(check=check, severity=severity, detail=detail, evidence=evidence)


def food_safety(offer: Mapping[str, Any], orgs: Sequence[Mapping[str, Any]]) -> Envelope:
    """Cold chain and dates. Refuses in full rather than reducing a share."""
    findings: list[Finding] = []
    category = str(offer.get("category", "")).lower()
    hours = offer.get("hours_unrefrigerated")

    if category in ("chilled", "frozen"):
        if hours is None:
            return Envelope(
                specialist="food-safety",
                status=Status.BLOCKED,
                reason=(
                    "a chilled or frozen offer that does not record how long it "
                    "was unrefrigerated cannot be assessed. Absent evidence is a "
                    "finding, never a pass"
                ),
                findings=(
                    _finding(
                        "cold-chain-evidence",
                        "high",
                        "hours_unrefrigerated is missing on a chilled offer",
                    ),
                ),
            )
        if float(hours) > 4:
            return Envelope(
                specialist="food-safety",
                status=Status.BLOCKED,
                reason=(
                    f"the cold chain was broken for {hours} hours, and the rule "
                    f"is four. This is refused in full, not reduced"
                ),
                findings=(
                    _finding(
                        "cold-chain",
                        "high",
                        f"{hours} hours above 8 degrees against a limit of 4",
                        evidence=f"hours_unrefrigerated={hours}",
                    ),
                ),
            )

    use_by = str(offer.get("use_by", ""))
    collection = str(offer.get("collection_date", ""))
    if use_by and collection and use_by <= collection:
        return Envelope(
            specialist="food-safety",
            status=Status.BLOCKED,
            reason=f"the use-by date {use_by} is not after the collection date {collection}",
            findings=(
                _finding("use-by", "high", f"use_by {use_by} <= collection {collection}"),
            ),
        )

    eligible: list[str] | None = None
    if not use_by:
        # Not a refusal. A donor who did not say is ordinary, and a fleet that
        # refused every offer without a use by would be a fleet coordinators
        # learn to type a date into. It is a finding, so the gap is on the card
        # and in the record rather than resolved into a long shelf life by a
        # comparison that never ran.
        findings.append(
            _finding(
                "use-by-not-established",
                "medium",
                (
                    "no use by date was recorded, so the same day rule could not "
                    "be applied. Confirm with the donor before this is collected: "
                    "an offer that has to be gone tomorrow may only go to members "
                    "that serve same day"
                ),
                evidence="use_by=",
            )
        )
    if use_by and collection:
        margin = _days_between(collection, use_by)
        if margin is not None and margin <= 1:
            same_day = [o["name"] for o in orgs if o.get("same_day_service")]
            # **This is the exclusion, not the sentence below it.** Until
            # 2026-09-08 this branch appended the finding and returned an
            # envelope carrying no meta at all, so the rule reached the reader
            # of the record and never reached the solver, which takes
            # eligibility from meta. offer-4471 published 96 kg to an
            # organisation this rule forbids, in a document that quoted the rule
            # two paragraphs above the table. A control that is prose on one
            # page and absent from the mechanism is the failure this whole
            # system exists to prevent, and it was sitting in the flagship
            # example.
            eligible = same_day
            findings.append(
                _finding(
                    "same-day-only",
                    "high",
                    (
                        f"use-by is {margin} day after collection, so only "
                        f"organisations that serve same day may take a share: "
                        f"{', '.join(same_day) or 'none in this network'}"
                    ),
                    evidence=f"use_by={use_by} collection_date={collection}",
                )
            )
    if eligible is not None and not eligible:
        return Envelope(
            specialist="food-safety",
            status=Status.BLOCKED,
            reason=(
                "this has to be collected and served on the same day and no "
                "member of this network serves same day. Tell the donor now"
            ),
            findings=tuple(findings),
        )
    return Envelope(
        specialist="food-safety",
        status=Status.NEEDS_CHANGES if findings else Status.OK,
        reason="dates constrain who may take a share" if findings else "",
        findings=tuple(findings),
        meta={"eligible": eligible} if eligible is not None else {},
    )


def capacity(offer: Mapping[str, Any], orgs: Sequence[Mapping[str, Any]]) -> Envelope:
    """Who can physically store and move this. A veto, not a preference."""
    category = str(offer.get("category", "")).lower()
    findings: list[Finding] = []
    eligible: list[str] = []
    # An even split across every member is the largest share any one of them
    # could be asked to move. Checking against that rather than against the
    # eventual share is deliberate: the share is not known until the draft is
    # built, and a member told at that point that it cannot carry its share
    # would have to be removed and the whole split recomputed.
    even_share = float(offer.get("quantity") or 0) / max(len(orgs), 1)
    # ``walk_in_limit_kg`` is a mass. An offer counted in units carries no mass,
    # so the comparison cannot be made and must not be faked. Comparing 36 units
    # against a 15 kg limit is not a conservative approximation, it is a
    # different dimension, and it silently barred three members of this network
    # from an offer they could have carried.
    unit_name = str(offer.get("unit", "")).strip().lower()
    weighable = unit_name in ("kg", "kilogram", "kilograms")

    for org in orgs:
        name = str(org.get("name", ""))
        if category in ("chilled", "frozen") and not org.get("cold_storage_litres"):
            findings.append(
                _finding(
                    "cold-storage",
                    "medium",
                    f"{name} has no cold storage and may not take a {category} share",
                )
            )
            continue
        limit = float(org.get("walk_in_limit_kg") or 0)
        if not org.get("has_van"):
            if not weighable:
                # Absent evidence is a finding, never a pass, and never a bar
                # either. The member stays eligible and the coordinator is told
                # that the one thing nobody can check is whether they can lift it.
                findings.append(
                    _finding(
                        "transport-not-determined",
                        "medium",
                        (
                            f"{name} has no van, and this offer is counted in "
                            f"{offer.get('unit')} rather than kg, so whether the "
                            f"share can be carried on foot could not be determined. "
                            f"Confirm the weight before collection"
                        ),
                    )
                )
            elif even_share > limit:
                # **A cap, and no longer a bar.** The register says the share
                # "has to be within what a volunteer carries", which constrains
                # the share and not the membership, and ``_capacities`` already
                # passes that limit to the solver. Excluding here as well meant
                # the two mechanisms disagreed and the exclusion won: Elpida
                # Night Shelter, one of only two organisations allowed to take
                # offer-4471, was dropped from it entirely for want of a van it
                # did not need to carry twenty kilos of bread.
                findings.append(
                    _finding(
                        "transport-capped",
                        "medium",
                        (
                            f"{name} has no van and can carry {limit:g} kg on foot, "
                            f"against an even split of about {even_share:.0f} kg, so "
                            f"its share is capped at {limit:g} kg rather than skipped"
                        ),
                        evidence=f"walk_in_limit_kg={limit:g}",
                    )
                )
        eligible.append(name)
    if not eligible:
        return Envelope(
            specialist="capacity",
            status=Status.BLOCKED,
            reason=(
                f"no member of this network can store a {category} offer. "
                f"The donor should be told today rather than after it spoils"
            ),
            findings=tuple(findings),
            # The one block in this fleet that turns on something which can
            # change, and so the only one that can be parked for another look: a
            # member's cold storage is a fact about today, not about the offer. A
            # freezer is repaired, a shelter confirms space. Two days is the
            # horizon because a perishable offer does not have a week.
            meta={
                "revisit_because": (
                    "no member could store it today. Cold storage is a fact "
                    "about the members rather than about the offer, so this is "
                    "worth asking again while the food is still good"
                )
            },
        )
    return Envelope(
        specialist="capacity",
        status=Status.NEEDS_CHANGES if findings else Status.OK,
        reason="some members cannot store this" if findings else "",
        findings=tuple(findings),
        meta={"eligible": eligible},
    )


#: The ceiling used when a network's filing does not state one. Documented rather
#: than silent: a network with no policy file gets a stated default, not no
#: ceiling, and the envelope says which of the two was applied.
DEFAULT_CEILING = 0.40


def ceiling_share(policy_text: str) -> tuple[float, str]:
    """The share ceiling this network wrote down, and where it came from.

    Read out of ``registers/allocation-policy.md`` rather than compiled in. It
    was compiled in until 2026-09-08, and a substitute corpus found it: a network
    whose own policy said 25% had its offers split at exactly 40%, because the
    register was listed as something the equity specialist reads while the number
    never came out of it. The premise of this product is that a network points
    the fleet at its own filing, and a ceiling that ignores the filing makes that
    a sentence about the wrong file.

    The first percentage in the document wins, because these registers are one
    page and state their ceiling in their first paragraph. A file that states two
    would need a person, and this returns the first with the source named so a
    reader can see which one was applied.
    """
    import re as _re

    match = _re.search(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)", policy_text or "")
    if not match:
        return DEFAULT_CEILING, "the default, because this filing states no ceiling"
    found = float(match.group(1)) / 100
    if not 0 < found <= 1:
        return DEFAULT_CEILING, f"the default, because {match.group(1)}% is not a share"
    return found, "registers/allocation-policy.md"


def equity(
    offer: Mapping[str, Any],
    orgs: Sequence[Mapping[str, Any]],
    recent: Sequence[Mapping[str, Any]] = (),
    policy_text: str = "",
) -> Envelope:
    """The ceiling this network wrote down, and the two-in-a-row rota."""
    quantity = float(offer.get("quantity") or 0)
    share, source = ceiling_share(policy_text)
    ceiling = quantity * share
    category = str(offer.get("category", "")).lower()
    took_last_two = _took_last_two(recent, category)
    findings: list[Finding] = []
    for name in took_last_two:
        findings.append(
            _finding(
                "rota",
                "medium",
                (
                    f"{name} received a share of the last two {category} offers, "
                    f"so it goes to the back of the queue for this one"
                ),
            )
        )
    return Envelope(
        specialist="equity",
        status=Status.NEEDS_CHANGES if findings else Status.OK,
        reason="the rota moves somebody down" if findings else "",
        findings=tuple(findings),
        meta={
            "ceiling": ceiling,
            "ceiling_share": share,
            "ceiling_from": source,
            "back_of_queue": took_last_two,
        },
    )


def _singular(word: str) -> str:
    """Enough stemming for a form field, and no more.

    A real stemmer would be a dependency and a source of surprises. This exists
    because ``nut_free`` has to catch ``nuts``.
    """
    word = word.strip().lower()
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _constraint_hit(token: str, declared: set[str]) -> str:
    """The declared allergen a constraint catches, or an empty string.

    Matches either way round, on the singular of both sides, so ``nut_free``
    catches ``nuts``, ``no_pork`` catches ``pork gelatin`` and
    ``alcohol_free_premises`` catches ``cooking alcohol``.

    It over-matches, and that is the direction chosen on purpose: ``nut`` is
    inside ``coconut``, so a coconut offer costs the library a share it could
    have had. The other error puts an allergen in front of a child who has a
    severe allergy to it. The record names the word and the constraint it
    matched, so the cheap error is visible and arguable and the expensive one
    does not happen quietly.
    """
    stem = _singular(token)
    for item in declared:
        other = _singular(item)
        if stem and (stem in other or other in stem):
            return item
    return ""


def premises(
    offer: Mapping[str, Any],
    orgs: Sequence[Mapping[str, Any]],
    manifest_text: str = "",
) -> Envelope:
    """Absolute constraints, and the specialist that needs to read the manifest.

    The deterministic half of this is honest about what it cannot see. It matches
    the offer's declared ``allergens`` against each organisation's constraints,
    and that is all a pattern can do. When the constraint is satisfied by the
    declared fields alone, this passes, and **that pass is the wrong answer on
    any offer whose contents are not in its declared fields**.

    That is not a hedge. ``offer-4483`` declares ``allergens: []`` and category
    ``ambient``, and its manifest puts wine, pork salami and hazelnut inside a
    gift hamper. Every pattern here passes it. Only an agent that chooses to open
    the manifest and then the register catches it, which is the comparison
    ``test_rules_alone_are_not_enough.py`` pins from both directions.
    """
    raw = offer.get("allergens", [])
    declared = {str(a).lower() for a in raw or []}
    findings: list[Finding] = []
    blocked_for: list[str] = []

    # ``None`` is not ``[]``. An empty list is "somebody checked and there are
    # none"; ``None`` is "nobody has established what is in this". They were the
    # same value until 2026-09-08, and every offer a coordinator typed carried
    # the second while being read as the first.
    #
    # This does not bar anybody. Barring the whole network on an unknown would
    # make the honest answer more expensive than the careless one, and the form
    # would go back to claiming there are no allergens. It states the gap, at
    # high severity, so it is on the card a person reads before approving and in
    # the published record afterwards.
    if raw is None:
        findings.append(
            _finding(
                "allergens-not-established",
                "high",
                (
                    "nobody has established what is in this offer, so the premises "
                    "constraints could not be checked against it. Absent evidence "
                    "is a finding, never a pass: ask the donor before collection, "
                    "and do not send it to a member whose constraint is absolute"
                ),
                evidence="allergens=null",
            )
        )

    for org in orgs:
        name = str(org.get("name", ""))
        constraints = [str(c).lower() for c in org.get("premises_constraints", []) or []]
        for constraint in constraints:
            token = constraint.replace("_free", "").replace("no_", "").replace("_premises", "")
            if token and _constraint_hit(token, declared):
                matched = _constraint_hit(token, declared)
                blocked_for.append(name)
                findings.append(
                    _finding(
                        "premises-constraint",
                        "high",
                        (
                            f"{name} cannot accept this offer: the offer declares "
                            f"{matched!r}, which the premises constraint {constraint} "
                            f"covers, and that constraint is absolute"
                        ),
                        evidence=f"{constraint} matched {matched!r}",
                    )
                )

    if manifest_text:
        extra, excluded = _manifest_contradicts_declaration(
            manifest_text, declared, orgs
        )
        findings.extend(extra)
        blocked_for.extend(excluded)

    return Envelope(
        specialist="premises",
        status=Status.NEEDS_CHANGES if findings else Status.OK,
        reason="a premises constraint excludes a member" if findings else "",
        findings=tuple(findings),
        meta={
            "blocked_for": sorted(set(blocked_for)),
            "declared_allergens": sorted(declared),
            "read_manifest": bool(manifest_text),
        },
    )


#: Words in a manifest that mean a constraint applies even though the offer's
#: declared fields say nothing. This list is short and it is **not** the answer
#: to offer-4483; it is a floor under the model, so that a wholly unreachable
#: model leaves the fleet more careful rather than less. It is deliberately not
#: extended to cover every case, because a rule per case is the rules engine this
#: project argues is insufficient, and pretending otherwise would make the
#: rules-versus-agent comparison on offer-4483 dishonest.
#:
#: **Matched on word boundaries since 2026-09-09.** It was a substring match, and
#: "ham" is inside "hamper", so every manifest mentioning a gift hamper was
#: flagged as pork. offer-4483, the example this project uses to argue that rules
#: alone are not enough, is about seasonal gift hampers: its real pork salami
#: masked the false positive by firing for the right organisation for the wrong
#: reason.
#:
#: **The bare category words are deliberately absent, and that is a known gap.**
#: A manifest saying "contains alcohol" in as many words blocks nobody here.
#: Adding "alcohol" to its own list was tried and reverted the same hour:
#: offer-4471's manifest reads "nothing here is alcohol", and a bare category
#: word matches the sentence that denies it, which excluded a member from an
#: offer it was one of two allowed to receive. Prose about a category is mostly
#: prose denying it, and the specific tokens below do not have that problem
#: because nobody writes "no hazelnut" as a matter of course.
#:
#: Negation handling would close it and is the beginning of the rules engine this
#: list exists not to be. Reading "nothing here is alcohol" correctly is the
#: model's job, and saying the floor does that would be claiming the
#: rules-versus-agent comparison on offer-4483 is unnecessary.
_MANIFEST_TOKENS = {
    "alcohol": ("wine", "beer", "spirits", "vodka", "whisky", "ouzo", "liqueur"),
    "pork": ("pork", "salami", "bacon", "ham", "gelatin"),
    "nut": ("hazelnut", "almond", "walnut", "peanut", "pistachio"),
}

#: One compiled matcher per category. ``\b(?:a|b)s?\b`` so that "nuts",
#: "wines" and "almonds" match and "hamper" does not.
_MANIFEST_PATTERNS = {
    category: re.compile(r"\b(?:" + "|".join(words) + r")s?\b", re.IGNORECASE)
    for category, words in _MANIFEST_TOKENS.items()
}


def _manifest_contradicts_declaration(
    manifest_text: str,
    declared: set[str],
    orgs: Sequence[Mapping[str, Any]],
) -> tuple[list[Finding], list[str]]:
    """Findings raised by reading the manifest rather than the offer's fields.

    Returns the findings **and the organisations they exclude**. Returning only
    the findings was a real defect and it is worth naming rather than quietly
    fixing: the specialist raised three high findings about wine, pork and
    hazelnut in offer-4483, and the run then allocated a share to all five
    members including the three whose premises exclude alcohol. A finding that
    changes nothing is a finding nobody is protected by.
    """
    lowered = manifest_text.lower()
    findings: list[Finding] = []
    excluded: list[str] = []
    for token, pattern in _MANIFEST_PATTERNS.items():
        found = pattern.search(lowered)
        hit = found.group(0) if found else ""
        if not hit or token in declared:
            continue
        affected = [
            str(org.get("name", ""))
            for org in orgs
            if any(
                token in str(constraint).lower()
                for constraint in org.get("premises_constraints", []) or []
            )
        ]
        excluded.extend(affected)
        who = ", ".join(affected) if affected else "no member, but the lot is still mixed"
        findings.append(
            _finding(
                "manifest-contradicts-declaration",
                "high",
                (
                    f"the manifest names {hit!r}, so this lot contains {token}, "
                    f"and the offer declares no such allergen or constraint. "
                    f"Excluded on this basis: {who}"
                ),
                evidence=hit,
            )
        )
    return findings, excluded


SPECIALISTS: dict[str, Callable[..., Envelope]] = {
    "food-safety": food_safety,
    "capacity": capacity,
    "equity": equity,
    "premises": premises,
}


# --------------------------------------------------------------------------
# The chore
# --------------------------------------------------------------------------


@dataclass
class ChoreResult:
    """Everything one run produced, including a run that produced no plan."""

    run_id: str
    subject: str
    offer_id: str
    woken: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    envelopes: list[Envelope] = field(default_factory=list)
    verdict: gate.Verdict | None = None
    draft: gate.Draft | None = None
    approval: Approval | None = None
    deferrals: list[Deferral] = field(default_factory=list)
    read_log: dict[str, Any] = field(default_factory=dict)
    outcome: str = ""
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "subject": self.subject,
            "offer_id": self.offer_id,
            "outcome": self.outcome,
            "note": self.note,
            "woken": self.woken,
            "skipped": self.skipped,
            "envelopes": [e.as_dict() for e in self.envelopes],
            "verdict": self.verdict.as_dict() if self.verdict else None,
            "approval_card": self.approval.as_dict() if self.approval else None,
            # The draft travels too, because the provenance thread is what the
            # screens render a finished run from. A run whose result cannot be
            # rebuilt is a run nobody can look at afterwards.
            "draft_body": self.draft.body if self.draft else "",
            "draft_allocations": [dict(a) for a in self.draft.allocations] if self.draft else [],
            "draft_must_not_receive": sorted(self.draft.must_not_receive) if self.draft else [],
            # The reason travels with the exclusion. A screen rebuilt from the
            # thread months later has to be able to say why somebody was
            # skipped, and recomputing it there would mean re-running the
            # specialists against today's register rather than the one that was
            # applied on the day.
            "draft_barred_because": dict(self.draft.barred_because) if self.draft else {},
            "deferrals": [d.as_dict() for d in self.deferrals],
            "reads": self.read_log,
        }

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True, default=str)


def run_chore(
    corpus: Corpus,
    offer: Mapping[str, Any],
    thread: Thread,
    analyst: Callable[[str, Mapping[str, Any], Toolbox], Envelope] | None = None,
    critic: Callable[..., tuple[Sequence[str], str]] | None = None,
    scheduler: Any = None,
    gate_fn: Callable[[gate.Draft], gate.Verdict] | None = None,
    approver: str = "",
    network: str = "kypseli-network",
) -> ChoreResult:
    """One offer, from arrival to an approval card a person reads.

    Nothing here publishes. The furthest this goes is minting an approval over
    exact bytes, and only when an approver is named. That is deliberate: a
    webhook produces a plan and stops, because the one thing a person is there
    for is the thing an automatic trigger must not do on their behalf.
    """
    from .corpus import orgs as read_orgs

    scheduler = scheduler or NullScheduler()
    offer_id = str(offer.get("id", "unknown"))
    result = ChoreResult(
        run_id=thread.run_id, subject=thread.subject, offer_id=offer_id
    )

    thread.append("offer.received", offer_id=offer_id, category=offer.get("category"))
    orgs = read_orgs(corpus)

    woken, skipped = route(offer)
    result.woken, result.skipped = woken, skipped
    thread.append("fleet.dispatch", woken=woken, skipped=skipped)

    # ADR-016. An empty woken set is a real answer and often the right one. A
    # run with nothing to govern says so and stops, rather than collecting no
    # fragments and handing an empty draft to a gate that correctly refuses it.
    if not woken:
        thread.append("run.nothing_to_allocate", skipped=skipped)
        result.outcome = "nothing_to_allocate"
        result.note = (
            f"no specialist in this network is concerned with a "
            f"{offer.get('category')!r} offer. Skipped: {', '.join(skipped)}"
        )
        return result

    # The manifest read is the run's own and is not charged to any specialist.
    setup_log = ReadLog()
    manifest_text = _read_manifest(corpus, offer, setup_log)
    policy_text = _read_policy(corpus)
    from .approval import published_history

    recent = [e.body for e in published_history(thread.ledger, network, [offer],
                                              category=offer.get("category", ""))
              if e.run_id != thread.run_id]
    if recent:
        thread.append("recall.performed", found=len(recent))

    envelopes: list[Envelope] = []
    logs: list[ReadLog] = [setup_log]
    for name in woken:
        envelope = _run_specialist(name, offer, orgs, recent, manifest_text, policy_text)
        # The deterministic verdict is the floor and it is never skipped. Where
        # it refuses, the model is not asked at all.
        if envelope.blocks:
            envelopes.append(envelope)
            thread.append("specialist.answered", **envelope.as_dict())
            continue
        if analyst is not None:
            # A budget of its own. Sharing one pool across the woken set spends
            # it in arrival order, and the arrival order is alphabetical. The
            # first deployed run showed exactly that: one specialist took ten of
            # twelve and the rest ran with nothing, each spending a model call
            # to report that it had been starved. They reported it correctly,
            # which is the safety property holding, but three model calls to
            # produce three findings that say "I could not read" is a design
            # fault rather than a result.
            log = ReadLog()
            logs.append(log)
            envelope = _union_model(envelope, analyst, offer, corpus, log, thread)
        envelopes.append(envelope)
        thread.append("specialist.answered", **envelope.as_dict())

    result.envelopes = envelopes
    result.read_log = _combined(logs)
    thread.append("read.performed", **result.read_log)

    overall = worst(envelopes)
    if overall is Status.BLOCKED:
        blocking = [e for e in envelopes if e.blocks]
        result.outcome = "blocked"
        result.note = "; ".join(e.reason for e in blocking)
        for envelope in blocking:
            deferral = _defer(envelope, thread, scheduler, result)
            if deferral is not None:
                result.deferrals.append(deferral)
        thread.append("plan.review_only", reason=result.note, outcome="blocked")
        return result

    draft = _draft(offer, orgs, envelopes, corpus, published=recent)
    result.draft = draft

    verdict = gate_fn(draft) if gate_fn else gate.judge(draft, critic=critic)
    result.verdict = verdict
    thread.append("gate.verdict", **verdict.as_dict())

    if not verdict.passed:
        result.outcome = "refused_by_gate"
        result.note = "; ".join(f.detail for f in verdict.blocking)
        thread.append("plan.review_only", reason=result.note, outcome="refused_by_gate")
        return result

    if not approver:
        result.outcome = "awaiting_approval"
        result.note = (
            "the plan passed the gate and stops here. A person has to read the "
            "bytes and approve them before anything is published"
        )
        thread.append("plan.proposed", offer_id=offer_id, shares=len(draft.allocations))
        return result

    approval = grant(
        network=network,
        key=record_key(offer_id, recent),
        body=draft.body,
        approved_by=approver,
        run_id=thread.run_id,
    )
    result.approval = approval
    result.outcome = "approved"
    result.note = "an approval was minted over these exact bytes, and expires"
    thread.append("plan.proposed", offer_id=offer_id, shares=len(draft.allocations))
    thread.append("approval.granted", **approval.as_dict())
    return result


def _run_specialist(
    name: str,
    offer: Mapping[str, Any],
    orgs: Sequence[Mapping[str, Any]],
    recent: Sequence[Mapping[str, Any]],
    manifest_text: str,
    policy_text: str = "",
) -> Envelope:
    """Call one deterministic specialist with the arguments it takes."""
    if name == "equity":
        return equity(offer, orgs, recent, policy_text)
    if name == "premises":
        return premises(offer, orgs, manifest_text)
    return SPECIALISTS[name](offer, orgs)


def _union_model(
    deterministic: Envelope,
    analyst: Callable[[str, Mapping[str, Any], Toolbox], Envelope],
    offer: Mapping[str, Any],
    corpus: Corpus,
    log: ReadLog,
    thread: Thread,
) -> Envelope:
    """Add the model's read to the deterministic one. It cannot subtract.

    A missing or unparseable answer contributes no verdict rather than
    defaulting to ``ok``, and an unreachable model leaves a finding saying so.
    Silence read as a pass is the failure mode of every tool of this kind.
    """
    box = Toolbox(corpus=corpus, log=log)
    try:
        model_envelope = analyst(deterministic.specialist, offer, box)
    except Exception as error:  # noqa: BLE001 - an outage must not clear a refusal
        return deterministic.union(
            Envelope(
                specialist=deterministic.specialist,
                status=Status.NEEDS_CHANGES,
                reason=f"the model read did not complete: {type(error).__name__}",
                findings=(
                    _finding(
                        "model-unreachable",
                        "medium",
                        (
                            f"{deterministic.specialist} could not be widened by a "
                            f"model read ({type(error).__name__}), so this is the "
                            f"deterministic answer alone"
                        ),
                    ),
                ),
            )
        )
    if model_envelope is None:
        return deterministic
    # The model is answering **as** this specialist, so its envelope is rebound
    # to that name rather than trusted to have set it. A model that named a
    # different specialist would otherwise raise inside ``union`` and take the
    # whole run down, which turns a mislabelled answer into an outage.
    if model_envelope.specialist != deterministic.specialist:
        model_envelope = replace(model_envelope, specialist=deterministic.specialist)
    thread.append(
        "specialist.answered",
        specialist=deterministic.specialist,
        source="model",
        paths_opened=log.paths_opened(),
    )
    return deterministic.union(model_envelope)



def _combined(logs: Sequence[ReadLog]) -> dict[str, Any]:
    """One run's reads, summed across the per-specialist budgets.

    The bound a reader cares about is still the run's: how much of my filing did
    this open. That number is now a sum rather than a single counter, and every
    read keeps the order it happened in, so the thread still shows one sequence.
    """
    entries = [e for log in logs for e in log.entries]
    return {
        "scope": list(logs[0].scope) if logs else [],
        "budget_per_specialist": READ_BUDGET,
        "budget": sum(log.budget for log in logs),
        "spent": sum(log.spent for log in logs),
        "remaining": sum(log.remaining for log in logs),
        "reads": entries,
    }

def _read_policy(corpus: Corpus) -> str:
    """This network's allocation policy, or nothing if it does not keep one.

    Not charged to a specialist's read budget, for the same reason the manifest
    is not: it is the run's own setup and every specialist would otherwise pay
    for it. An absent file is a legitimate state, and ``ceiling_share`` returns a
    documented default and says that is what it did.
    """
    try:
        return corpus.read("registers/allocation-policy.md")
    except Exception:  # noqa: BLE001 - a filing without a policy is not an error
        return ""


def _read_manifest(corpus: Corpus, offer: Mapping[str, Any], log: ReadLog) -> str:
    """Open the offer's manifest, if it names one and it can be read."""
    manifest = str(offer.get("manifest", "")).strip()
    if not manifest:
        return ""
    path = manifest if manifest.startswith("offers/") else f"offers/{manifest}"
    try:
        return bounded_read(log, corpus, "manifest", path)
    except Exception:  # noqa: BLE001 - a missing manifest is absence, not a crash
        return ""


def _defer(
    envelope: Envelope, thread: Thread, scheduler: Any, result: ChoreResult
) -> Deferral | None:
    """Park a blocked specialist's decision and schedule the wake.

    **Only when waiting could change the answer.** This parked every blocked
    specialist, which meant a cold chain refusal was scheduled for another look
    in two days. The register's answer to a broken cold chain is "refused in
    full", and the only thing two days changes is that the food is worse. A wake
    can only append an escalation, so nothing unsafe was going to be published,
    but a coordinator being asked to revisit a refusal that is not revisitable is
    a product telling somebody their judgement is wanted where it is not.

    An envelope that says nothing is treated as final. Silence should fall on the
    safe side, and the specialist that knows whether its refusal turns on an
    unknown is the specialist, not this function.
    """
    if not envelope.meta.get("revisit_because"):
        return None

    entry = thread.append(
        "finding.deferred", specialist=envelope.specialist, reason=envelope.reason
    )
    days = int(envelope.meta.get("revisit_in_days") or 2)
    when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    deferral = Deferral(
        deferral_id=entry.entry_id,
        subject=thread.subject,
        run_id=thread.run_id,
        reason=str(envelope.meta.get("revisit_because")),
        until=when,
    )
    try:
        deferral = scheduler.defer(deferral)
    except Exception as error:  # noqa: BLE001 - reported, never swallowed silently
        thread.append(
            "deferral.scheduled",
            deferral_id=deferral.deferral_id,
            scheduled=False,
            why=str(error),
        )
        return deferral
    thread.append(
        "deferral.scheduled",
        deferral_id=deferral.deferral_id,
        scheduled=deferral.scheduled,
        until=deferral.until.isoformat(),
        schedule_name=deferral.schedule_name,
    )
    return deferral


def record_key(offer_id: str, published: Sequence[Mapping[str, Any]] = ()) -> str:
    """Where this run's record would be published, never on top of an old one.

    A record for an offer already exists the moment somebody has approved one,
    and on 2026-09-08 one of them turned out to be wrong: offer-4471 published a
    share to an organisation a food-safety rule forbade. The repair for a public
    document that is wrong is not to write the right bytes to the same address.
    Somebody has read the old one, somebody has linked to it, and a coordinator
    who acted on it needs to be able to see what they acted on.

    So a correction takes the next key in the series and says what it corrects,
    and the original stays exactly where it is, still reachable, marked
    superseded by the index rather than edited in place.
    """
    highest = _highest_version(offer_id, published)
    if highest == 0:
        return f"records/{offer_id}.md"
    return f"records/{offer_id}-c{highest + 1}.md"


def superseded_by_this_run(offer_id: str, published: Sequence[Mapping[str, Any]] = ()) -> str:
    """The record this run would replace, or an empty string for a first record.

    Read from the version in the key rather than from where the entry sits in the
    list. ``recall`` returns newest first and this used to reverse it and take
    the first match, which is the oldest, so a correction to a correction opened
    by claiming it replaced the original. Its test passed a list in ascending
    order, so the bug and the test agreed with each other and both disagreed with
    what the ledger hands over.
    """
    highest = _highest_version(offer_id, published)
    if highest == 0:
        return ""
    return f"records/{offer_id}.md" if highest == 1 else f"records/{offer_id}-c{highest}.md"


def _highest_version(offer_id: str, published: Sequence[Mapping[str, Any]]) -> int:
    """Which version of this offer's record has been published. 0 for none.

    The base key is version 1, ``-c2`` is version 2. Order independent on
    purpose: nothing guarantees the order these arrive in, and both callers were
    guessing it.
    """
    base = f"records/{offer_id}.md"
    prefix = f"records/{offer_id}-c"
    highest = 0
    for entry in published:
        key = str(entry.get("key", ""))
        if key == base:
            highest = max(highest, 1)
        elif key.startswith(prefix) and key.endswith(".md"):
            number = key[len(prefix) : -len(".md")]
            if number.isdigit():
                highest = max(highest, int(number))
    return highest


def _draft(
    offer: Mapping[str, Any],
    orgs: Sequence[Mapping[str, Any]],
    envelopes: Sequence[Envelope],
    corpus: Corpus,
    published: Sequence[Mapping[str, Any]] = (),
) -> gate.Draft:
    """Turn the specialists' answers into the record that would be published."""
    quantity = float(offer.get("quantity") or 0)
    unit = str(offer.get("unit", "units"))
    # Absolute exclusions, which the gate independently re-checks, and soft ones
    # from the rota, which only move an organisation down the queue. They are
    # kept apart because conflating them would let a rota decision become a
    # permanent bar, and because only the absolute set is a safety claim.
    barred: set[str] = set()
    deprioritised: set[str] = set()
    # Which specialist barred whom. The record has to name the rule that
    # actually excluded an organisation, and a search for the member's name
    # across every finding returns whichever one mentions it first. That was
    # enough while one specialist did the excluding. It stopped being enough the
    # moment food-safety started excluding too: the library and the school were
    # barred by the same-day rule and the record attributed it to a note about
    # how much they can carry, which named the wrong rule to the one member most
    # likely to argue with it.
    barred_by: dict[str, str] = {}
    ceiling = quantity
    for envelope in envelopes:
        for name in envelope.meta.get("blocked_for", []) or []:
            barred.add(name)
            barred_by.setdefault(str(name), envelope.specialist)
        deprioritised.update(envelope.meta.get("back_of_queue", []) or [])
        if "ceiling" in envelope.meta:
            ceiling = float(envelope.meta["ceiling"])
        eligible_meta = envelope.meta.get("eligible")
        if eligible_meta is not None:
            for org in orgs:
                name = str(org.get("name", ""))
                if name not in eligible_meta:
                    barred.add(name)
                    barred_by.setdefault(name, envelope.specialist)
    excluded = barred | deprioritised

    receiving = [str(o.get("name", "")) for o in orgs if o.get("name") not in excluded]

    # The split is solved rather than divided. An even split bounded by the
    # ceiling is what this used to do, and it ignores the thing that decides
    # whether a share is any use: whether the member can store it. The solver
    # takes the ceiling and the per-member capacity together and returns a
    # feasibility proof with the shares, which is what the gate then re-checks.
    capacities = _capacities(offer, orgs, receiving)
    solution = solve_allocation(
        total_quantity=quantity,
        eligible_orgs=receiving,
        max_quota_ratio=(ceiling / quantity) if quantity else 0.40,
        capacities=capacities,
    )
    allocations: list[dict[str, Any]] = [
        {
            "org": share.org,
            "quantity": share.quantity,
            "reason": (
                "Eligible under the applied safety, premises and rota checks. "
                f"{share.reason}; ceiling {solution.proof['ceiling_enforced']:g} {unit}. "
                + (f"Collection capacity limit {capacities[share.org]:g} {unit}. "
                   if share.org in capacities else
                   "No additional collection capacity limit was established in this unit. ")
                + "The bounded split starts evenly, then assigns remaining headroom "
                "in filing order."
            ),
            "evidence_sources": [path for path in [f"offers/{offer['id']}.json",
                                 "registers/allocation-policy.md",
                                 *[f"orgs/{o['id']}.json" for o in orgs
                                   if o.get("name") == share.org and o.get("id")]]
                                 if path in corpus.list_paths()],
            "share_of_offer": f"{share.percentage:.1f}%",
        }
        for share in solution.shares
    ]

    because = _why_barred(sorted(excluded), envelopes, barred_by)
    for name in receiving:
        if not any(a["org"] == name for a in allocations):
            because[name] = (
                f"Collection capacity is zero {unit}; no share can be assigned."
                if capacities.get(name) == 0 else
                "Eligible, but no quantity remains within the policy ceiling and filing order."
            )
    supersedes = superseded_by_this_run(str(offer.get("id", "")), published)
    body = _render(
        offer, allocations, sorted(because), unit, envelopes, solution, because, supersedes
    )
    return gate.Draft(
        body=body,
        allocations=allocations,
        offer=offer,
        known_orgs=org_names(corpus),
        must_not_receive=frozenset(barred),
        barred_because=because,
    )


def _why_barred(
    excluded: Sequence[str],
    envelopes: Sequence[Envelope],
    barred_by: Mapping[str, str],
) -> dict[str, str]:
    """One sentence per excluded member, from the specialist that excluded them.

    Three renderers used to work this out for themselves by scanning every
    finding for the member's name, and a name search cannot tell which rule did
    the excluding. It returned whichever finding mentioned them first, which
    after food-safety began excluding was a note about how much they could
    carry. Computed here, once, so the record, the message for the group chat
    and the summary on the decision screen cannot disagree about why somebody
    was skipped.
    """
    reasons: dict[str, str] = {}
    for name in excluded:
        owner = barred_by.get(name)
        candidates = [
            f.detail
            for e in envelopes
            if owner is None or e.specialist == owner
            for f in e.findings
            if name in f.detail
        ]
        if not candidates and owner is not None:
            # A rule that excludes by naming who *may* receive never mentions
            # the excluded member, so the rule itself is the sentence to print.
            candidates = [
                f.detail for e in envelopes if e.specialist == owner for f in e.findings
            ] or [f"{e.reason} (`{e.specialist}`)" for e in envelopes if e.specialist == owner]
        reasons[name] = candidates[0] if candidates else "a rule in the register"
    return reasons


def _capacities(
    offer: Mapping[str, Any],
    orgs: Sequence[Mapping[str, Any]],
    receiving: Sequence[str],
) -> dict[str, float]:
    """What each member can physically take, where that is knowable.

    Cold storage is in litres and a chilled offer is in kilograms, so the two
    are not the same unit and are not converted here: one litre of fridge space
    does not hold one kilogram of yoghurt, and inventing a conversion would be
    a number nobody could check. A member with no van is capped at what a
    volunteer carries, which is the one limit the register states in the
    offer's own unit. Everything else is left unbounded and the ceiling governs.
    """
    weighable = str(offer.get("unit", "")).strip().lower() in ("kg", "kilogram", "kilograms")
    caps: dict[str, float] = {}
    for org in orgs:
        name = str(org.get("name", ""))
        if name not in receiving:
            continue
        if weighable and not org.get("has_van"):
            limit = float(org.get("walk_in_limit_kg") or 0)
            if limit > 0:
                caps[name] = limit
        # A rehearsal may tighten capacity for this offer only. It cannot clear
        # any specialist exclusion or expand a physical limit from the filing.
        extra = offer.get("dispatch_capacity_limits", {}).get(name)
        if type(extra) in (int, float) and 0 <= extra <= float(offer.get("quantity") or 0):
            caps[name] = min(caps.get(name, extra), extra)
    return caps


def _inert(value: Any) -> str:
    """Untrusted text that cannot become markup in the published record.

    A title typed into the intake form arrived in the record verbatim, so
    ``<img src=x onerror=alert(1)>`` became a tag in a permanent public
    document. Our own surfaces were never at risk and it is worth being precise
    about that rather than calling this an XSS: the approval card and the record
    screen both render the bytes escaped, and S3 serves the object as
    ``text/markdown``, which a browser displays. Anything that renders the
    markdown does render the tag, and the record is the artifact a funder opens.

    ``&lt;`` is a literal ``<`` in markdown, so a value that genuinely contains
    an angle bracket still reads correctly and stops being a tag.
    """
    return str(value if value is not None else "").replace("<", "&lt;").replace(">", "&gt;")


def _render(
    offer: Mapping[str, Any],
    allocations: Sequence[Mapping[str, Any]],
    excluded: Sequence[str],
    unit: str,
    envelopes: Sequence[Envelope],
    solution: AllocationSolution | None = None,
    because: Mapping[str, str] | None = None,
    supersedes: str = "",
) -> str:
    """The published record, in the words a member of the network would use."""
    lines = [
        f"# Allocation, {_inert(offer.get('id'))}",
        "",
    ]
    if supersedes:
        # First thing on the page, because somebody arriving here from a link to
        # the old record needs to know before they read a table.
        lines += [
            "> **This corrects an earlier record.**",
            f"> It replaces `{supersedes}`, which is still published and still",
            "> reachable, because a public document somebody may have acted on is",
            "> not repaired by overwriting it. What changed and why is at the foot",
            "> of this record.",
            "",
        ]
    lines += [
        f"**{_inert(offer.get('title'))}** from {_inert(offer.get('donor'))}.",
        (
            f"{offer.get('quantity')} {unit}, category {offer.get('category')}, "
            f"collected {offer.get('collection_date')}."
        ),
        "",
        "## Shares",
        "",
        "| Organisation | Share | Why |",
        "|---|---:|---|",
    ]
    for allocation in allocations:
        share = allocation.get("share_of_offer", "")
        lines.append(
            f"| {_inert(allocation['org'])} | {allocation['quantity']} {unit}"
            f"{f' ({share})' if share else ''} | {_inert(allocation['reason'])} |"
        )
    if excluded:
        lines += ["", "## Not receiving a share, and the rule that decided it", ""]
        for name in excluded:
            # The reason can carry a model's own words, and an organisation name
            # comes from a record the organisation edits. Both are outside text.
            lines.append(
                f"- **{_inert(name)}**: "
                f"{_inert((because or {}).get(name, 'excluded by policy'))}"
            )
    if solution is not None:
        lines += [
            "",
            "## The arithmetic, so it can be checked rather than trusted",
            "",
            f"- offered: **{_pretty(solution.total_offered)} {unit}**",
            f"- allocated: **{_pretty(solution.total_allocated)} {unit}**",
            f"- unallocated: **{_pretty(solution.unallocated_remainder)} {unit}**",
            (
                f"- ceiling: no member may take more than "
                f"**{solution.max_quota_ratio * 100:.0f}%**. The largest share here is "
                f"**{solution.max_observed_ratio * 100:.1f}%**"
            ),
            f"- every constraint satisfied: **{'yes' if solution.is_feasible else 'no'}**",
        ]

    lines += [
        "",
        "## How this was decided",
        "",
    ]
    for envelope in envelopes:
        lines.append(f"- `{envelope.specialist}`: {envelope.status.value}")
        for finding in envelope.findings:
            lines.append(f"  - {finding.severity}: {finding.detail}")
    lines += [
        "",
        (
            "This record carries organisations and quantities. It carries no "
            "person, by policy and by a gate that refuses one."
        ),
    ]
    return "\n".join(lines)



def _pretty(value: float) -> str:
    """Render a quantity without a trailing .0 on a whole number."""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _days_between(start: str, end: str) -> int | None:
    try:
        return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
    except ValueError:
        return None


def _took_last_two(recent: Sequence[Mapping[str, Any]], category: str) -> list[str]:
    """Organisations that appear in both of the last two records of a category."""
    # Corrections to one donation are not a second donation. Keep only the
    # newest receipt for each distinct offer, without inventing missing history.
    same, seen = [], set()
    for record in recent:
        if str(record.get("category", "")).lower() != category:
            continue
        offer = record.get("offer_id") or record.get("key") or id(record)
        if offer not in seen:
            same.append(record)
            seen.add(offer)
        if len(same) == 2:
            break
    if len(same) < 2:
        return []
    sets = [set(r.get("orgs", []) or []) for r in same]
    return sorted(sets[0] & sets[1])


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def subject_for_offer(network: str, offer: Mapping[str, Any]) -> str:
    """Key the memory on the network and the offer's category, never a constant.

    Built here rather than passed through ``subject_for``. That function takes
    the **files** a delivery changed and drops the basename, so handing it the
    area ``offers/ambient`` would return ``offers`` and every category in the
    network would share one memory. The two cases look identical as strings and
    only the caller knows which it holds, so the caller decides.
    """
    category = str(offer.get("category") or "unknown").strip().lower()
    return f"{network.strip() or 'unknown-network'}:offers/{category}"

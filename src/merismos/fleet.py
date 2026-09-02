"""The router, the specialists, and the chore that runs them.

The deterministic verdict is the floor. It runs first, always. Where it refuses,
the run returns that refusal **without consulting a model at all**, because
asking and discarding the answer costs a request and invites a later edit that
uses it. Where the rules pass, a model's answer is unioned in through
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
    """What ``GET /catalog`` serves. A queried structure, not a table in a doc."""
    return {
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

    if use_by and collection:
        margin = _days_between(collection, use_by)
        if margin is not None and margin <= 1:
            same_day = [o["name"] for o in orgs if o.get("same_day_service")]
            findings.append(
                _finding(
                    "same-day-only",
                    "medium",
                    (
                        f"use-by is {margin} day after collection, so only "
                        f"organisations that serve same day may take a share: "
                        f"{', '.join(same_day) or 'none in this network'}"
                    ),
                )
            )
    return Envelope(
        specialist="food-safety",
        status=Status.NEEDS_CHANGES if findings else Status.OK,
        reason="dates constrain who may take a share" if findings else "",
        findings=tuple(findings),
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
                findings.append(
                    _finding(
                        "transport",
                        "medium",
                        (
                            f"{name} has no van and can carry {limit:g} kg on foot, "
                            f"against a share of about {even_share:.0f} kg. The "
                            f"policy makes transport a veto rather than a preference"
                        ),
                        evidence=f"walk_in_limit_kg={limit:g}",
                    )
                )
                continue
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
        )
    return Envelope(
        specialist="capacity",
        status=Status.NEEDS_CHANGES if findings else Status.OK,
        reason="some members cannot store this" if findings else "",
        findings=tuple(findings),
        meta={"eligible": eligible},
    )


def equity(
    offer: Mapping[str, Any],
    orgs: Sequence[Mapping[str, Any]],
    recent: Sequence[Mapping[str, Any]] = (),
) -> Envelope:
    """The 40% ceiling and the two-in-a-row rota."""
    quantity = float(offer.get("quantity") or 0)
    ceiling = quantity * 0.40
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
        meta={"ceiling": ceiling, "back_of_queue": took_last_two},
    )


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
    the manifest and then the register catches it, which is the comparison the
    README reports and ``test_rules_alone_are_not_enough.py`` pins from both
    directions.
    """
    declared = {str(a).lower() for a in offer.get("allergens", []) or []}
    findings: list[Finding] = []
    blocked_for: list[str] = []

    for org in orgs:
        name = str(org.get("name", ""))
        constraints = [str(c).lower() for c in org.get("premises_constraints", []) or []]
        for constraint in constraints:
            token = constraint.replace("_free", "").replace("no_", "").replace("_premises", "")
            if token and token in declared:
                blocked_for.append(name)
                findings.append(
                    _finding(
                        "premises-constraint",
                        "high",
                        (
                            f"{name} cannot accept this offer: the offer declares "
                            f"{token} and the premises constraint {constraint} is absolute"
                        ),
                        evidence=constraint,
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
#: README's comparison dishonest.
_MANIFEST_TOKENS = {
    "alcohol": ("wine", "beer", "spirits", "vodka", "whisky", "ouzo", "liqueur"),
    "pork": ("pork", "salami", "bacon", "ham", "gelatin"),
    "nut": ("hazelnut", "almond", "walnut", "peanut", "pistachio"),
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
    for token, words in _MANIFEST_TOKENS.items():
        hit = next((w for w in words if w in lowered), "")
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
    recent = [e.body for e in thread.recall("record.published", limit=8)]
    if recent:
        thread.append("recall.performed", found=len(recent))

    envelopes: list[Envelope] = []
    logs: list[ReadLog] = [setup_log]
    for name in woken:
        envelope = _run_specialist(name, offer, orgs, recent, manifest_text)
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

    draft = _draft(offer, orgs, envelopes, corpus)
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
        key=f"records/{offer_id}.md",
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
) -> Envelope:
    """Call one deterministic specialist with the arguments it takes."""
    if name == "equity":
        return equity(offer, orgs, recent)
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
    """Park a blocked specialist's decision and schedule the wake."""
    entry = thread.append(
        "finding.deferred", specialist=envelope.specialist, reason=envelope.reason
    )
    when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
    deferral = Deferral(
        deferral_id=entry.entry_id,
        subject=thread.subject,
        run_id=thread.run_id,
        reason=envelope.reason,
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


def _draft(
    offer: Mapping[str, Any],
    orgs: Sequence[Mapping[str, Any]],
    envelopes: Sequence[Envelope],
    corpus: Corpus,
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
    ceiling = quantity
    for envelope in envelopes:
        barred.update(envelope.meta.get("blocked_for", []) or [])
        deprioritised.update(envelope.meta.get("back_of_queue", []) or [])
        if "ceiling" in envelope.meta:
            ceiling = float(envelope.meta["ceiling"])
        eligible_meta = envelope.meta.get("eligible")
        if eligible_meta is not None:
            barred.update(
                str(o.get("name", "")) for o in orgs if o.get("name") not in eligible_meta
            )
    excluded = barred | deprioritised

    receiving = [str(o.get("name", "")) for o in orgs if o.get("name") not in excluded]
    allocations: list[dict[str, Any]] = []
    if receiving:
        share = min(ceiling, quantity / len(receiving))
        remaining = quantity
        for name in receiving:
            amount = round(min(share, remaining), 2)
            if amount <= 0:
                break
            allocations.append(
                {
                    "org": name,
                    "quantity": amount,
                    "reason": "eligible under the policy, within the ceiling",
                }
            )
            remaining -= amount

    body = _render(offer, allocations, sorted(excluded), unit, envelopes)
    return gate.Draft(
        body=body,
        allocations=allocations,
        offer=offer,
        known_orgs=org_names(corpus),
        must_not_receive=frozenset(barred),
    )


def _render(
    offer: Mapping[str, Any],
    allocations: Sequence[Mapping[str, Any]],
    excluded: Sequence[str],
    unit: str,
    envelopes: Sequence[Envelope],
) -> str:
    """The published record, in the words a member of the network would use."""
    lines = [
        f"# Allocation, {offer.get('id')}",
        "",
        f"**{offer.get('title')}** from {offer.get('donor')}.",
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
        lines.append(
            f"| {allocation['org']} | {allocation['quantity']} {unit} | "
            f"{allocation['reason']} |"
        )
    if excluded:
        lines += ["", "## Not receiving a share, and the rule that decided it", ""]
        for name in excluded:
            reasons = [
                f.detail
                for e in envelopes
                for f in e.findings
                if name in f.detail
            ]
            lines.append(f"- **{name}**: {reasons[0] if reasons else 'excluded by policy'}")
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


def _days_between(start: str, end: str) -> int | None:
    try:
        return (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
    except ValueError:
        return None


def _took_last_two(recent: Sequence[Mapping[str, Any]], category: str) -> list[str]:
    """Organisations that appear in both of the last two records of a category."""
    same = [r for r in recent if str(r.get("category", "")).lower() == category][:2]
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

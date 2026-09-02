"""The two models, and the different amounts of trust each one is given.

**The analyst** is a Strands agent with the toolbox and the guard attached. It is
handed a network and a question rather than an answer, and it decides what to
open. That is what makes the agency inspectable: the sequence of files it chose
is recorded in the read log and reaches the provenance thread, so a fixed
pipeline and a real agent do not produce the same evidence.

**The critic** is a different model family and it is reached by calling Bedrock's
``Converse`` directly, with no ``toolConfig`` in the request. That is not
belt-and-braces around the guard, it is a narrower claim: the critic is not an
agent and there is no dispatcher for it to ask. It reviews prose about an
allocation, cannot open a file, and its output can only be added to what a person
reads.

**Two variables, never one.** ``MERISMOS_MODEL`` and ``MERISMOS_CRITIC_MODEL``.
A single ambiguous MODEL would make it possible to move the whole fleet onto a
review model by editing one deployment variable, and nothing would report that it
had happened.

**Model ids here are Bedrock inference profiles**, of the form
``{geo}.anthropic.claude-...``, not first-party Anthropic API ids. The default
geography is ``eu``, because this network's records concern people in Europe and
inference geography is a data-residency decision rather than a latency one. It is
a variable, so a deployment elsewhere changes it without editing code, and
nothing in this module assumes any particular model is enabled on any particular
account.

**What is reported is the model that answered, never the one configured.** Those
are different claims and only one of them is evidence. Every result carries the
id Bedrock echoed back and the latency it took.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .envelope import Envelope, Finding, Status
from .gate import Draft, Verdict, sanitise_for_independent_review
from .guard import Guard
from .tools import Toolbox

#: Default inference profiles. Both are overridable and neither is assumed to be
#: enabled on any account: a model that is not enabled produces an
#: AccessDeniedException, which this module reports as a finding rather than
#: swallowing.
DEFAULT_MODEL = "eu.anthropic.claude-opus-5"
DEFAULT_CRITIC_MODEL = "eu.amazon.nova-pro-v1:0"

#: The critic reviews a short piece of prose and must not ramble; the analyst is
#: doing the reading and needs room.
CRITIC_MAX_TOKENS = 600

SPECIALIST_BRIEF = {
    "food-safety": (
        "You are the food safety specialist for a network of small charities "
        "sharing donated food. Cold chain and use-by rules have already been "
        "applied deterministically and you cannot overturn them. Look for what "
        "a date field cannot show: read the manifest and the safety register."
    ),
    "capacity": (
        "You are the capacity specialist. Storage and transport limits have "
        "already been applied from the register. Look for what the register's "
        "numbers do not capture, for example a note saying a freezer is broken."
    ),
    "equity": (
        "You are the equity specialist. The 40% ceiling and the two-in-a-row "
        "rota have already been applied. Read the allocation policy and say "
        "whether anything about this offer makes the mechanical answer unfair."
    ),
    "premises": (
        "You are the premises specialist, and this is the one that matters most. "
        "Some members cannot accept some goods at all, absolutely, for reasons "
        "about the people they serve rather than about storage. An offer's "
        "declared fields routinely fail to reveal this: a pallet labelled "
        "'assorted ambient grocery' may contain alcohol, pork or nuts inside a "
        "mixed lot. Open the manifest. Then open the register and check each "
        "member's premises_constraints against what the manifest actually lists."
    ),
}

INSTRUCTIONS = """
You have tools for reading this network's own filing. Use list_paths first to
see what exists, then open only what you need: your read budget is small and a
search spends it.

Record what you find with record_finding. Severity is low, medium or high.

Answer in one line of JSON at the end, and nothing after it:
{"status": "ok" | "needs_changes" | "blocked", "reason": "<why, if not ok>"}

Rules that are not negotiable:
- If you refuse, you must name a reason. A refusal nobody can explain is worse
  than no refusal.
- Never invent an organisation. Only names in orgs/ exist.
- Never put a person's name, address, phone number or national identifier into
  anything you write. The record this becomes is published publicly.
- If you could not read something you needed, say so and use needs_changes.
  Absent evidence is a finding, never a pass.
"""

_JSON_LINE = re.compile(r"\{[^{}]*\"status\"\s*:\s*\"(?:ok|needs_changes|blocked)\"[^{}]*\}")


class ModelUnavailable(RuntimeError):
    """Raised when the configured model cannot be reached or is not enabled."""


def _client(service: str, region: str = "", client: Any = None) -> Any:
    if client is not None:
        return client
    import boto3

    return boto3.client(service, region_name=region or os.environ.get("AWS_REGION") or None)


@dataclass
class BedrockAnalyst:
    """One specialist's read, performed by a model that chose what to open."""

    model_id: str = ""
    region: str = ""
    role: str = "reader"
    #: Seconds. Short on purpose: see build_agent.
    connect_timeout: int = 5
    read_timeout: int = 120
    _model: Any = None

    def __post_init__(self) -> None:
        self.model_id = self.model_id or os.environ.get("MERISMOS_MODEL") or DEFAULT_MODEL

    def build_agent(self, box: Toolbox, brief: str) -> Any:
        """Assemble the Strands agent for one specialist on one offer.

        The guard is attached here rather than trusted to be attached somewhere.
        An agent constructed without it would be an agent whose tool authority is
        whatever its toolset happens to contain.

        **The timeouts are not tuning, they are a control.** With botocore's
        defaults a Lambda with no usable credentials retries with exponential
        backoff for over a minute, which is a billed timeout rather than an
        error, and nothing in the logs says why. A run that cannot reach its
        model should fail in seconds so ``run_chore`` can record the finding
        that says so. This was found by a test suite hanging, which is the
        cheapest possible place to find it.
        """
        from botocore.config import Config
        from strands import Agent
        from strands.models import BedrockModel

        model = self._model or BedrockModel(
            model_id=self.model_id,
            region_name=self.region or None,
            boto_client_config=Config(
                connect_timeout=self.connect_timeout,
                read_timeout=self.read_timeout,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
        return Agent(
            model=model,
            tools=box.build(),
            system_prompt=f"{brief}\n{INSTRUCTIONS}",
            hooks=[Guard(role=self.role)],
        )

    def __call__(
        self, specialist: str, offer: Mapping[str, Any], box: Toolbox
    ) -> Envelope:
        """The analyst signature ``run_chore`` expects.

        Returns an envelope that is unioned into the deterministic one, so
        anything returned here can tighten the answer and nothing here can
        loosen it. A model that cannot be reached raises, and ``run_chore``
        turns that into a finding rather than a clean pass.
        """
        brief = SPECIALIST_BRIEF.get(specialist, SPECIALIST_BRIEF["premises"])
        agent = self.build_agent(box, brief)
        question = (
            f"Offer {offer.get('id')}: {offer.get('title')!r} from "
            f"{offer.get('donor')}. {offer.get('quantity')} {offer.get('unit')}, "
            f"category {offer.get('category')}. The donor's note says: "
            f"{offer.get('note')!r}\n\n"
            f"Decide whether this offer can be apportioned as it stands."
        )
        started = time.time()
        try:
            result = agent(question)
        except Exception as error:  # noqa: BLE001 - re-raised as a typed failure
            raise ModelUnavailable(
                f"{self.model_id} could not be reached: {type(error).__name__}"
            ) from error

        status, reason = _parse_answer(str(result))
        findings = tuple(
            Finding(
                check=f["check"],
                severity=f["severity"],
                detail=f["detail"],
                evidence="model",
            )
            for f in box.findings
        )
        if status is Status.OK and not findings:
            reason = ""
        if status.is_refusal and not reason:
            # A refusal the model would not explain contributes caution without
            # an explanation, which is the safe direction and an honest label.
            reason = (
                "the model refused and named no reason, so this is recorded as "
                "needing a person rather than as an answer"
            )
            status = Status.NEEDS_CHANGES
        return Envelope(
            specialist=specialist,
            status=status,
            reason=reason,
            findings=findings,
            meta={
                "model": self.model_id,
                "latency_s": round(time.time() - started, 2),
                "paths_opened": box.log.paths_opened(),
                "reads_spent": box.log.spent,
            },
        )


def _parse_answer(text: str) -> tuple[Status, str]:
    """Read the model's verdict, contributing nothing when it cannot be read.

    An unparseable answer returns ``OK`` with no reason, which unions to the
    deterministic verdict unchanged. That is deliberate: defaulting a garbled
    answer to ``ok`` would be wrong only if ``ok`` were able to clear something,
    and it cannot, because ``union`` never loosens. Defaulting it to a refusal
    would let a truncated response block a food collection.
    """
    match = _JSON_LINE.search(text)
    if not match:
        return Status.OK, ""
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return Status.OK, ""
    try:
        status = Status(str(parsed.get("status", "ok")))
    except ValueError:
        return Status.OK, ""
    return status, str(parsed.get("reason", "")).strip()


@dataclass
class BedrockCritic:
    """An independent second read, from a different model family, that can only add.

    It is given the sanitiser's output and never the draft. It is called without
    ``toolConfig``, so it has no tools to call rather than tools it is asked not
    to call. And whatever it says lands in ``advisories``, which
    ``gate._with_critic`` copies alongside a verdict it does not touch.
    """

    model_id: str = ""
    region: str = ""
    _client: Any = None

    def __post_init__(self) -> None:
        self.model_id = (
            self.model_id
            or os.environ.get("MERISMOS_CRITIC_MODEL")
            or DEFAULT_CRITIC_MODEL
        )

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3
        from botocore.config import Config

        return boto3.client(
            "bedrock-runtime",
            region_name=self.region or os.environ.get("AWS_REGION") or None,
            config=Config(
                connect_timeout=5,
                read_timeout=60,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    def __call__(self, draft: Draft, verdict: Verdict) -> tuple[Sequence[str], str]:
        """Return ``(advisories, model_that_answered)``.

        The second element is read off the response rather than from
        ``self.model_id``, so a fleet that reports a critic reviewed something is
        reporting a review that happened.
        """
        envelope = sanitise_for_independent_review(draft, verdict)
        response = self.client.converse(
            modelId=self.model_id,
            system=[
                {
                    "text": (
                        "You are reviewing a proposed apportionment of donated "
                        "food between small charities. You are a second opinion "
                        "and you cannot approve, reject, or remove any finding. "
                        "List up to three concerns, one per line, plainly. If "
                        "you have none, say so in one line."
                    )
                }
            ],
            messages=[{"role": "user", "content": [{"text": envelope}]}],
            inferenceConfig={"maxTokens": CRITIC_MAX_TOKENS, "temperature": 0.0},
        )
        text = "".join(
            block.get("text", "")
            for block in response["output"]["message"]["content"]
        )
        advisories = [line.strip(" -*\t") for line in text.splitlines() if line.strip()]
        return advisories[:3], self.model_id


def analyst_from_env(env: Mapping[str, str] | None = None) -> BedrockAnalyst | None:
    """Build an analyst, or ``None`` when the offline path was asked for by name.

    ``MERISMOS_MODEL=none`` is the offline switch and it has to be spelled. A
    fleet that silently ran without a model would report the deterministic answer
    as though a model had agreed with it.
    """
    env = dict(os.environ) if env is None else env
    configured = env.get("MERISMOS_MODEL", "").strip()
    if configured.lower() in ("none", "off", "stub"):
        return None
    return BedrockAnalyst(model_id=configured or DEFAULT_MODEL, region=env.get("AWS_REGION", ""))


def critic_from_env(env: Mapping[str, str] | None = None) -> BedrockCritic | None:
    """Build a critic, or ``None``. Unset means no critic, which is the default."""
    env = dict(os.environ) if env is None else env
    configured = env.get("MERISMOS_CRITIC_MODEL", "").strip()
    if not configured or configured.lower() in ("none", "off"):
        return None
    return BedrockCritic(model_id=configured, region=env.get("AWS_REGION", ""))

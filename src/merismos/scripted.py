"""A deterministic planner, so the offline path needs no AWS account.

It is not the model and never claims to be. ``model_id`` reports
``scripted-planner`` and that string reaches the provenance thread, so a run
recorded offline can never be mistaken for a run that called Bedrock.

Two jobs. It walks the tool sequence the real planner would walk, which is what
lets CI, the recorded demo and a stranger with no credentials exercise the real
tools, the real guard and the real gate. And it can be told to demand one
specific tool, which is how the guard is proven: point a planner at
``publish_record`` from the reader role and watch the dispatcher refuse it.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, Sequence
from typing import Any

from strands.models import Model as _StrandsModel

MODEL_ID = "scripted-planner/1.0.0"


class ScriptedPlanner(_StrandsModel):
    """Emit a fixed list of tool calls, then stop.

    Each entry of ``plan`` is a tool name, or a ``(name, arguments)`` pair. The
    planner asks for each in order, skipping any that already appear in the
    conversation, and finishes with a sentence once the plan is exhausted.
    """

    stateful = False

    def __init__(
        self,
        plan: Sequence[Any] = (),
        closing: str = "Plan complete.",
        **kwargs: Any,
    ) -> None:
        self.plan = tuple(_normalise(step) for step in plan)
        self.closing = closing
        self._config: dict[str, Any] = dict(kwargs)

    @property
    def model_id(self) -> str:
        return MODEL_ID

    def update_config(self, **kwargs: Any) -> None:
        self._config.update(kwargs)

    def get_config(self) -> Any:
        return self._config

    async def structured_output(
        self, output_model: Any, prompt: Any = None, **kwargs: Any
    ) -> Any:
        raise NotImplementedError("the scripted planner never asks for structured output")

    async def stream(
        self,
        messages: Any,
        tool_specs: list | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[dict]:
        """Ask for the next unasked step, or close.

        A refused call still appears in the conversation as a tool result, so
        ``already`` counts attempts rather than successes. That is deliberate:
        a planner that retried a refused tool forever would turn one refusal
        into an infinite loop, and the guard is a control, not a suggestion to
        try again.
        """
        already = _tools_already_asked_for(messages)
        for name, arguments in self.plan:
            if name in already:
                continue
            async for event in _tool_use(name, arguments, len(already)):
                yield event
            return

        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        yield {"contentBlockDelta": {"delta": {"text": self.closing}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}


def _normalise(step: Any) -> tuple[str, dict[str, Any]]:
    """Accept either ``"tool_name"`` or ``("tool_name", {...})``."""
    if isinstance(step, str):
        return step, {}
    name, arguments = step
    return str(name), dict(arguments)


def _tools_already_asked_for(messages: Any) -> list[str]:
    """Every tool name that appears as a ``toolUse`` in the conversation."""
    asked: list[str] = []
    for message in messages or ():
        for block in message.get("content", []) or ():
            if isinstance(block, dict) and "toolUse" in block:
                asked.append(block["toolUse"].get("name", ""))
    return asked


async def _tool_use(
    name: str, arguments: dict[str, Any], index: int
) -> AsyncIterable[dict]:
    """The event sequence Strands parses into one tool call."""
    yield {"messageStart": {"role": "assistant"}}
    yield {
        "contentBlockStart": {
            "start": {"toolUse": {"name": name, "toolUseId": f"scripted-{index}-{name}"}}
        }
    }
    yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(arguments)}}}}
    yield {"contentBlockStop": {}}
    yield {"messageStop": {"stopReason": "tool_use"}}

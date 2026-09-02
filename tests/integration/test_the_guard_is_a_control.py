"""The guard is proven by disabling it, not by asserting it is registered.

Three assertions, and the middle one is the one that matters. A model demanding
``publish_record`` as the reader never reaches the tool. The same model, same
tools, same prompt, with the guard removed, does reach it. So the refusal is
attributable to the guard and to nothing else about the setup.

The third asserts the harness genuinely dispatches: as the writer, the same
demand goes through. Without it, a test that only ever sees a tool not run
cannot tell a working guard from a broken harness.
"""

from __future__ import annotations

import asyncio

import pytest

from mitos.guard import Guard
from mitos.scripted import ScriptedPlanner

strands = pytest.importorskip("strands")


class Spy:
    """Records whether the tool body ran, and what it was given."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def tool(self):
        from strands import tool

        @tool
        def publish_record(record_id: str = "", body: str = "") -> str:
            """Publish an approved allocation record.

            Args:
                record_id: The record to publish.
                body: The exact bytes that were approved.
            """
            self.calls.append({"record_id": record_id, "body": body})
            return "published"

        return publish_record


def _run(role: str, with_guard: bool) -> tuple[Spy, Guard]:
    from strands import Agent

    spy = Spy()
    guard = Guard(role=role)
    agent = Agent(
        model=ScriptedPlanner(
            plan=[("publish_record", {"record_id": "r-1", "body": "anything"})]
        ),
        tools=[spy.tool()],
        system_prompt="Publish the record.",
        hooks=[guard] if with_guard else [],
    )
    asyncio.run(agent.invoke_async("Publish record r-1."))
    return spy, guard


def test_the_reader_never_reaches_the_publish_tool():
    spy, guard = _run(role="reader", with_guard=True)

    assert spy.calls == [], "the reader reached publish_record, which is the whole failure"
    assert [refusal.tool for refusal in guard.refusals] == ["publish_record"]
    assert "cannot publish" in guard.refusals[0].message


def test_the_same_demand_succeeds_with_the_guard_removed():
    """Proof the refusal above is the guard and not the harness.

    If this ever fails, the test above stops being evidence of anything: it
    would mean the tool was unreachable for some other reason.
    """
    spy, _ = _run(role="reader", with_guard=False)

    assert len(spy.calls) == 1, "with no guard the model must reach the tool"
    assert spy.calls[0]["record_id"] == "r-1"


def test_the_writer_reaches_it_with_the_guard_in_place():
    """The guard permits as well as refuses, so it is a policy and not a wall."""
    spy, guard = _run(role="writer", with_guard=True)

    assert len(spy.calls) == 1
    assert guard.refusals == []

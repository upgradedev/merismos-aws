"""The guard's policy, decided without constructing an agent.

``decide`` is pure and free of every SDK type on purpose. It means the policy
can be re-run against a thread entry months later to ask whether the same call
would still be refused, and it means these cases cost nothing to test. The
dispatcher half is proven separately, against the real SDK, in
``tests/integration/test_the_guard_is_a_control.py``.

Everything here is about refusing in the safe direction. An unknown role, an
unnamed tool and an unknown tool all refuse, because each of them is a
deployment fault and a deployment fault must not become a permission.
"""

from __future__ import annotations

import pytest

from merismos.guard import (
    FORBIDDEN_EVERYWHERE,
    PUBLISH_TOOL,
    ROLE_TOOLS,
    Guard,
    Refusal,
    decide,
)


@pytest.mark.parametrize("role", sorted(ROLE_TOOLS))
def test_every_role_may_call_what_it_is_granted(role):
    for tool in ROLE_TOOLS[role]:
        assert decide(role, tool) is None, f"{role} was refused its own tool {tool}"


@pytest.mark.parametrize("role", sorted(ROLE_TOOLS))
def test_no_role_may_call_a_tool_forbidden_everywhere(role):
    for tool in FORBIDDEN_EVERYWHERE:
        message = decide(role, tool)

        assert message is not None
        assert "every identity" in message


def test_only_the_writer_may_publish():
    assert decide("writer", PUBLISH_TOOL) is None
    for role in ("reader", "evaluator"):
        message = decide(role, PUBLISH_TOOL)

        assert message is not None
        assert "cannot publish" in message
        assert "human approval" in message


def test_an_unknown_role_may_call_nothing_and_is_named_a_deployment_fault():
    """A typo in an environment variable must fail closed, and say why."""
    message = decide("raeder", "read_file")

    assert message is not None
    assert "deployment fault" in message


def test_a_tool_call_with_no_name_is_refused():
    assert decide("reader", "") is not None


def test_a_tool_the_role_does_not_hold_names_the_role_and_the_tool():
    message = decide("evaluator", "propose_allocation")

    assert message == "the evaluator identity may not call propose_allocation"


def test_the_evaluator_holds_no_read_tool_at_all():
    """A gate that can go looking is a gate that can be sent looking."""
    for tool in ("read_file", "search", "list_paths"):
        assert decide("evaluator", tool) is not None


def test_the_reader_holds_no_publish_and_the_writer_holds_no_read():
    """The two halves of the boundary, stated as one assertion each."""
    assert PUBLISH_TOOL not in ROLE_TOOLS["reader"]
    assert not ROLE_TOOLS["writer"] & {"read_file", "search", "list_paths"}


# --------------------------------------------------------------------------
# The hook's bookkeeping, which is what reaches the thread and /identity.
# --------------------------------------------------------------------------


class _Event:
    """The two fields the guard reads, and the one it writes."""

    def __init__(self, name: str) -> None:
        self.tool_use = {"name": name, "toolUseId": "t-1"}
        self.selected_tool = None
        self.cancel_tool: bool | str = False


def test_a_permitted_call_is_left_alone():
    guard = Guard(role="reader")
    event = _Event("read_file")

    guard.before_tool_call(event)

    assert event.cancel_tool is False
    assert guard.refusals == []


def test_a_refused_call_is_cancelled_with_the_reason_as_the_message():
    guard = Guard(role="reader")
    event = _Event(PUBLISH_TOOL)

    guard.before_tool_call(event)

    assert isinstance(event.cancel_tool, str)
    assert "cannot publish" in event.cancel_tool
    assert guard.refusals == [
        Refusal(tool=PUBLISH_TOOL, role="reader", message=event.cancel_tool)
    ]


def test_a_refusal_can_be_forwarded_to_the_thread_as_it_happens():
    seen: list[Refusal] = []
    guard = Guard(role="reader", on_refusal=seen.append)

    guard.before_tool_call(_Event(PUBLISH_TOOL))

    assert [r.tool for r in seen] == [PUBLISH_TOOL]
    assert seen[0].as_dict()["role"] == "reader"


def test_the_tool_name_is_read_from_the_selected_tool_when_there_is_no_tool_use():
    """The SDK may hand back a resolved tool and no dict, so both are handled."""

    class Resolved:
        tool_name = PUBLISH_TOOL

    guard = Guard(role="reader")
    event = _Event(PUBLISH_TOOL)
    event.tool_use = None
    event.selected_tool = Resolved()

    guard.before_tool_call(event)

    assert isinstance(event.cancel_tool, str)


def test_identity_reports_what_this_process_may_call_and_what_it_refused():
    guard = Guard(role="reader")
    guard.before_tool_call(_Event(PUBLISH_TOOL))

    reported = guard.as_dict()

    assert reported["role"] == "reader"
    assert PUBLISH_TOOL not in reported["may_call"]
    assert "read_file" in reported["may_call"]
    assert reported["refusals_this_process"][0]["tool"] == PUBLISH_TOOL
    assert sorted(FORBIDDEN_EVERYWHERE) == reported["refused_everywhere"]


def test_an_unknown_role_reports_an_empty_allowlist_rather_than_crashing():
    """``/identity`` has to answer even when the deployment is misconfigured."""
    assert Guard(role="nonsense").as_dict()["may_call"] == []

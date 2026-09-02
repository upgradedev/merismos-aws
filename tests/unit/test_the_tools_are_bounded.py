"""The tools an agent actually calls, and the bounds it cannot talk past.

These are exercised as functions rather than through an agent on purpose. The
dispatcher is proven separately in
``tests/integration/test_the_guard_is_a_control.py``; what is proven here is
that the bounds hold whoever calls them, including a caller that is not a model
at all.

The search assertions are the ones worth reading. A search that quietly reads
the whole corpus enforces nothing, and a search that spends the entire run
budget in one call leaves the agent unable to open the two files the search just
told it about. Both are asserted, because fixing either one alone produces a
tool that is useless in a different direction.
"""

from __future__ import annotations

import json

import pytest

from merismos.corpus import LocalCorpus
from merismos.tools import MAX_READ_BYTES, MAX_SEARCH_SCAN, READ_BUDGET, ReadLog, Toolbox


@pytest.fixture
def box() -> Toolbox:
    return Toolbox(corpus=LocalCorpus())


@pytest.fixture
def tools(box: Toolbox) -> dict:
    return {t.tool_name: t for t in box.build()}


def test_every_tool_the_guard_permits_the_reader_actually_exists(tools):
    """The guard's allowlist and the toolbox must not drift apart.

    A name in ``ROLE_TOOLS['reader']`` with no tool behind it is a permission
    granted over nothing, and a tool with no entry is refused at runtime by a
    guard that looks like a bug.
    """
    from merismos.guard import ROLE_TOOLS

    assert set(tools) == set(ROLE_TOOLS["reader"])


def test_listing_paths_costs_no_budget(tools, box):
    """An agent must always be able to see what exists before choosing."""
    answer = json.loads(tools["list_paths"]())

    assert box.log.spent == 0
    assert answer["reads_remaining"] == READ_BUDGET
    assert "registers/allocation-policy.md" in answer["paths"]


def test_listing_paths_shows_nothing_outside_the_scope(tools):
    answer = json.loads(tools["list_paths"]())

    assert all(
        p.startswith(("offers/", "orgs/", "registers/")) for p in answer["paths"]
    )


@pytest.mark.parametrize(
    "path",
    ["../../../etc/passwd", "/etc/passwd", "secrets/aws.json", "orgs/../../escape"],
)
def test_a_read_outside_the_bounds_returns_a_refusal_and_no_bytes(tools, box, path):
    answer = tools["read_file"](path)

    assert answer.startswith("REFUSED:")
    assert box.log.spent == 0, "a refused read must not consume budget"


def test_a_missing_file_in_scope_is_absence_rather_than_a_crash(tools, box):
    answer = tools["read_file"]("orgs/does-not-exist.json")

    assert answer.startswith("REFUSED:")
    assert box.log.spent == 0


def test_a_served_read_spends_exactly_one(tools, box):
    text = tools["read_file"]("registers/food-safety.md")

    assert "cold chain" in text.lower()
    assert box.log.spent == 1
    assert box.log.paths_opened() == ["registers/food-safety.md"]


def test_the_budget_stops_the_read_after_the_last_one(tools, box):
    for _ in range(READ_BUDGET):
        tools["read_file"]("registers/retention.md")

    assert box.log.spent == READ_BUDGET
    assert tools["read_file"]("registers/retention.md").startswith("REFUSED:")
    assert box.log.spent == READ_BUDGET, "the refusal must not increment the count"


def test_a_long_file_is_truncated_and_says_so(box):
    """Truncated rather than refused: a truncated policy is still worth reading."""
    long_text = "policy line\n" * 5_000

    class Padded:
        def list_paths(self):
            return ["registers/long.md"]

        def read(self, path):
            return long_text

    box.corpus = Padded()
    tools = {t.tool_name: t for t in box.build()}

    answer = tools["read_file"]("registers/long.md")

    assert "[truncated at" in answer
    assert len(answer.encode("utf-8")) < len(long_text.encode("utf-8"))
    assert len(answer.encode("utf-8")) <= MAX_READ_BYTES + 64


def test_search_finds_the_term_and_reports_what_it_did_not_open(tools, box):
    answer = json.loads(tools["search"]("alcohol"))

    assert answer["files_scanned"] <= MAX_SEARCH_SCAN
    assert answer["files_in_scope"] > MAX_SEARCH_SCAN
    assert answer["truncated"] is True
    assert answer["note"], "a partial search must say it was partial"


def test_search_spends_the_same_budget_as_a_read(tools, box):
    """The bug this prevents: a thousand reads served, zero counted."""
    before = box.log.spent

    tools["search"]("wine")

    assert box.log.spent > before
    assert box.log.spent <= MAX_SEARCH_SCAN


def test_one_search_cannot_spend_the_whole_run_budget(tools, box):
    """Both halves are needed. Without the per-call cap the agent is locked out.

    The failure this pins is not theoretical: counting search reads without
    capping them per call meant one search consumed everything and every later
    ``read_file`` was refused, so the agent answered without opening a file.
    """
    tools["search"]("the")

    assert box.log.remaining > 0, "a single search left the agent unable to read"
    assert not tools["read_file"]("orgs/pantry-kypseli.json").startswith("REFUSED:")


def test_search_stops_at_the_budget_rather_than_testing_files_it_did_not_pay_for(box):
    """A hit from an unpaid file leaks exactly the term-presence the bound withholds."""
    box.log = ReadLog(budget=1)
    tools = {t.tool_name: t for t in box.build()}

    answer = json.loads(tools["search"]("alcohol"))

    assert answer["files_scanned"] == 1
    assert answer["truncated"] is True


def test_the_scan_order_is_stable_between_runs(box):
    """A bound that moves between runs cannot be audited."""
    first = json.loads(Toolbox(corpus=LocalCorpus()).build()[2]("courgette"))
    second = json.loads(Toolbox(corpus=LocalCorpus()).build()[2]("courgette"))

    assert first["hits"] == second["hits"]
    assert first["files_scanned"] == second["files_scanned"]


def test_recall_says_so_when_no_memory_is_attached(tools):
    answer = json.loads(tools["recall"]())

    assert answer["prior"] == []
    assert "no memory" in answer["note"]


def test_recall_returns_what_the_fleet_already_decided(box):
    box.recall = lambda kind: [{"kind": kind, "reason": "the shelter said Thursday"}]
    tools = {t.tool_name: t for t in box.build()}

    answer = json.loads(tools["recall"]("finding.deferred"))

    assert answer["prior"][0]["reason"] == "the shelter said Thursday"


def test_a_finding_is_recorded_with_its_severity(tools, box):
    tools["record_finding"]("cold-chain", "high", "six hours at ambient")

    assert box.findings == [
        {"check": "cold-chain", "severity": "high", "detail": "six hours at ambient"}
    ]


def test_an_invented_severity_is_refused_rather_than_coerced(tools, box):
    answer = tools["record_finding"]("cold-chain", "catastrophic", "very bad")

    assert answer.startswith("REFUSED:")
    assert box.findings == [], "an unparseable severity must not become a finding"


def test_a_deferral_records_its_reason_and_date(tools, box):
    tools["defer_until"]("the shelter cannot confirm fridge space", "2026-09-10T06:00:00")

    assert box.deferrals == [
        {
            "reason": "the shelter cannot confirm fridge space",
            "until": "2026-09-10T06:00:00",
        }
    ]


def test_an_allocation_is_proposed_with_a_reason(tools, box):
    tools["propose_allocation"]("Omonoia Soup Kitchen", 96.0, "largest cold storage")

    assert box.allocations == [
        {
            "org": "Omonoia Soup Kitchen",
            "quantity": 96.0,
            "reason": "largest cold storage",
        }
    ]


def test_the_read_log_reports_refusals_alongside_what_was_served(tools, box):
    """The log is the evidence an agent chose, so it has to show the bad guesses."""
    tools["read_file"]("registers/retention.md")
    tools["read_file"]("../escape")

    entries = box.log.as_dict()["reads"]

    assert [e["served"] for e in entries] == [True, False]
    assert entries[1]["why"]
    assert box.log.as_dict()["spent"] == 1

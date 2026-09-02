"""The tools a specialist may call, and the bounds enforced inside them.

An agent that genuinely decides where to look can decide to look somewhere it
should not. So the reads are bounded here rather than asked for in a prompt, and
the bound is checked in one function that every reading tool goes through.

Four bounds. Scope: only the register, the offers and the policies. Traversal:
no ``..`` and no absolute path. Size: one read is capped. Budget: a finite number
of successful reads per run.

**Why the budget is counted here and not at the caller.** The obvious shape puts
all four bounds in ``read_file`` and none in ``search``, which checks scope
inline and then reads every in-scope file whole. On a thousand-file corpus with
the limit at twelve that is a thousand reads served and zero counted, and an
agent that wants the whole corpus only has to search for a common word. So ``search`` here spends
the same budget, stops when it is gone, and reports that it stopped.

**And why a per-call cap as well as a run budget.** Counting search reads without
capping them per call made the tool unusable: one search spent the whole budget
and every later read was refused, so the agent answered without opening
anything, which is worse than refusing. Both halves are needed. A per-call cap
with no run budget lets an agent search fifty times; a run budget with no
per-call cap is what broke it.

A refused read does not consume budget. An agent that guesses a path badly is
not locked out of the files it is entitled to open.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .corpus import Corpus, NotInCorpus

#: Where a specialist may read. Everything else is refused, including files that
#: exist. The default is the network's own filing and nothing more.
DEFAULT_SCOPE = ("offers/", "orgs/", "registers/")

#: One read returns at most this many bytes. A file longer than this is
#: truncated and says so, rather than being refused: a truncated policy is still
#: worth reading, and an agent told the text was cut can ask for a narrower path.
MAX_READ_BYTES = 8_000

#: Successful reads per run, across every tool.
READ_BUDGET = 12

#: Files one ``search`` call may open, inside the run budget rather than instead
#: of it.
MAX_SEARCH_SCAN = 4


class ReadRefused(PermissionError):
    """Raised when a read is outside the bounds. Never returns bytes."""


@dataclass
class ReadLog:
    """Every read attempted, whether it was served, and what it cost.

    This is what makes an agent's choices inspectable rather than claimed. The
    sequence of paths a specialist chose to open is the evidence that it chose,
    and it goes into the provenance thread.
    """

    scope: Sequence[str] = DEFAULT_SCOPE
    budget: int = READ_BUDGET
    spent: int = 0
    entries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.spent)

    def record(self, tool: str, path: str, served: bool, bytes_read: int, why: str = "") -> None:
        self.entries.append(
            {
                "tool": tool,
                "path": path,
                "served": served,
                "bytes": bytes_read,
                "why": why,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": list(self.scope),
            "budget": self.budget,
            "spent": self.spent,
            "remaining": self.remaining,
            "reads": self.entries,
        }

    def paths_opened(self) -> list[str]:
        """The choices, in order, for the thread and for the README's table."""
        return [e["path"] for e in self.entries if e["served"]]


def check_read(log: ReadLog, path: str) -> None:
    """Refuse a read, or return. Called before any bytes are produced.

    Raises rather than returning a reason, so a caller that forgets to check the
    return value cannot accidentally serve the file. That is the opposite of the
    convention elsewhere in this codebase and it is deliberate: everywhere else a
    refusal is data a human reads, and here a refusal is a control.
    """
    if not path or not path.strip():
        raise ReadRefused("a read arrived with no path")
    if path.startswith("/") or path.startswith("\\") or ":" in path[:3]:
        raise ReadRefused(f"{path} is an absolute path, and reads are relative")
    if ".." in path.split("/"):
        raise ReadRefused(f"{path} traverses out of the corpus")
    if not any(path.startswith(prefix) for prefix in log.scope):
        raise ReadRefused(
            f"{path} is outside the readable scope {list(log.scope)}. "
            f"The fleet reads the register, the offers and the policies"
        )
    if log.remaining <= 0:
        raise ReadRefused(
            f"the read budget of {log.budget} for this run is spent. "
            f"Opened so far: {', '.join(log.paths_opened()) or 'nothing'}"
        )


def bounded_read(log: ReadLog, corpus: Corpus, tool: str, path: str) -> str:
    """The one place bytes come from. Scope, budget, cap, log, in that order."""
    try:
        check_read(log, path)
    except ReadRefused as refusal:
        # A refused read costs nothing. Counting refusals against the cap
        # inflates the number past the limit on bad guesses alone, and then the
        # limit never stops the thing it exists to stop.
        log.record(tool, path, served=False, bytes_read=0, why=str(refusal))
        raise
    try:
        text = corpus.read(path)
    except NotInCorpus as missing:
        log.record(tool, path, served=False, bytes_read=0, why=str(missing))
        raise
    truncated = len(text.encode("utf-8")) > MAX_READ_BYTES
    if truncated:
        text = text.encode("utf-8")[:MAX_READ_BYTES].decode("utf-8", "ignore")
        text += f"\n\n[truncated at {MAX_READ_BYTES} bytes]"
    log.spent += 1
    log.record(tool, path, served=True, bytes_read=len(text.encode("utf-8")))
    return text


@dataclass
class Toolbox:
    """The tools bound to one run, so a tool cannot outlive its budget."""

    corpus: Corpus
    log: ReadLog = field(default_factory=ReadLog)
    recall: Callable[[str], list[dict[str, Any]]] | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    deferrals: list[dict[str, Any]] = field(default_factory=list)
    allocations: list[dict[str, Any]] = field(default_factory=list)

    def build(self) -> list[Any]:
        """Return the Strands tools. Imported here so the domain stays clean.

        ``src/merismos`` outside this module imports no SDK, which is the check
        STANDARDS A5 makes with a grep. This module is the boundary.
        """
        from strands import tool

        corpus = self.corpus
        log = self.log
        box = self

        @tool
        def list_paths() -> str:
            """List every file in the network's filing that may be read.

            Costs no read budget, so an agent can always find out what exists
            before deciding what to open.
            """
            paths = [
                p for p in corpus.list_paths() if any(p.startswith(s) for s in log.scope)
            ]
            return json.dumps(
                {"paths": paths, "reads_remaining": log.remaining}, indent=2
            )

        @tool
        def read_file(path: str) -> str:
            """Read one file from the network's filing.

            Args:
                path: A path inside offers/, orgs/ or registers/.
            """
            try:
                return bounded_read(log, corpus, "read_file", path)
            except (ReadRefused, NotInCorpus) as refusal:
                return f"REFUSED: {refusal}"

        @tool
        def search(term: str) -> str:
            """Find which files mention a term, opening at most a few of them.

            Args:
                term: The word or phrase to look for.
            """
            in_scope = [
                p for p in corpus.list_paths() if any(p.startswith(s) for s in log.scope)
            ]
            hits: list[str] = []
            scanned = 0
            truncated = False
            for path in in_scope:
                if scanned >= MAX_SEARCH_SCAN or log.remaining <= 0:
                    truncated = True
                    break
                try:
                    text = bounded_read(log, corpus, "search", path)
                except (ReadRefused, NotInCorpus):
                    continue
                scanned += 1
                if term.lower() in text.lower():
                    hits.append(path)
            return json.dumps(
                {
                    "term": term,
                    "hits": hits,
                    "files_scanned": scanned,
                    "files_in_scope": len(in_scope),
                    "reads_remaining": log.remaining,
                    # An agent that believes it searched everything will report
                    # that a term appears nowhere. Saying so is the honest
                    # failure and the useful one.
                    "truncated": truncated,
                    "note": (
                        "this search opened only the first files in sorted order. "
                        "It is a way to find the two or three files worth reading, "
                        "not a way to read the corpus"
                    )
                    if truncated
                    else "",
                },
                indent=2,
            )

        @tool
        def recall(kind: str = "finding.deferred") -> str:
            """What this fleet already decided about this network, before today.

            Args:
                kind: The kind of prior entry to look for.
            """
            if box.recall is None:
                return json.dumps({"prior": [], "note": "no memory is attached"})
            return json.dumps({"prior": box.recall(kind)}, indent=2, default=str)

        @tool
        def record_finding(check: str, severity: str, detail: str) -> str:
            """Record something noticed about this offer.

            Args:
                check: A short name for what was checked.
                severity: One of low, medium or high.
                detail: What was found, in a sentence a coordinator can act on.
            """
            if severity not in ("low", "medium", "high"):
                return f"REFUSED: severity must be low, medium or high, not {severity!r}"
            box.findings.append(
                {"check": check, "severity": severity, "detail": detail}
            )
            return f"recorded {check} at {severity}"

        @tool
        def defer_until(reason: str, until: str) -> str:
            """Park a decision until a date, and wake the fleet on that date.

            Args:
                reason: Why this cannot be decided now.
                until: An ISO date or timestamp, for example 2026-09-11T06:00:00.
            """
            box.deferrals.append({"reason": reason, "until": until})
            return f"deferred until {until}: {reason}"

        @tool
        def propose_allocation(org: str, quantity: float, reason: str) -> str:
            """Propose one organisation's share of this offer.

            Args:
                org: The organisation's name exactly as the register spells it.
                quantity: How much, in the offer's own unit.
                reason: Why this organisation and this amount.
            """
            box.allocations.append(
                {"org": org, "quantity": quantity, "reason": reason}
            )
            return f"proposed {quantity} to {org}"

        return [
            list_paths,
            read_file,
            search,
            recall,
            record_finding,
            defer_until,
            propose_allocation,
        ]

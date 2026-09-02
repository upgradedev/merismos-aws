"""The provenance thread: the memory, the audit trail and the evidence, one store.

Append only **by interface**. There is no update method and no delete method on
this protocol, so no caller anywhere in the fleet can express the idea of
changing an entry that already exists. That is a weaker guarantee than an IAM
policy and this file says so rather than implying otherwise: a principal with
``dynamodb:PutItem`` could overwrite a row from outside this code. What the
interface buys is that nothing inside the fleet can, including a model that has
been talked into wanting to.

Every entry carries ``parent_id``, so a run is a chain rather than a bag of rows
with a shared identifier. That is what makes "follow the thread back" a walk
instead of a sort.

The subject a run writes under is derived from the delivery, never from a module
constant. mitos-gcp shipped a constant and every organisation it watched shared
one memory with every other and with the demo corpus. The bug is cheap to
recreate and expensive to notice, because with one tenant a shared key and a
scoped key return identical rows.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

#: The kinds an entry may carry. Named rather than free text so that a typo is a
#: failure at write time instead of a row that no query will ever return.
KINDS = (
    "run.started",
    "run.nothing_to_allocate",
    "offer.received",
    "fleet.dispatch",
    "specialist.answered",
    "guard.refused",
    "read.performed",
    "recall.performed",
    "gate.delegated",
    "gate.verdict",
    "critic.independent_review",
    "finding.deferred",
    "deferral.scheduled",
    "deferral.fired",
    "deferral.escalated",
    "plan.proposed",
    "plan.review_only",
    "approval.granted",
    "record.published",
    "run.failed",
)


class UnknownKind(ValueError):
    """Raised when an entry names a kind the ledger does not publish."""


@dataclass(frozen=True)
class Entry:
    """One appended fact. Immutable once constructed, and never edited after."""

    kind: str
    subject: str
    run_id: str
    body: Mapping[str, Any] = field(default_factory=dict)
    entry_id: str = ""
    parent_id: str = ""
    at: float = 0.0
    scope: str = "live"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise UnknownKind(
                f"{self.kind!r} is not a kind this ledger publishes. Add it to "
                f"KINDS deliberately, so that queries stay writable"
            )
        if not self.subject.strip():
            raise ValueError("an entry names the subject it is about")
        if not self.run_id.strip():
            raise ValueError("an entry names the run that produced it")
        object.__setattr__(self, "entry_id", self.entry_id or uuid.uuid4().hex)
        object.__setattr__(self, "at", self.at or time.time())

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "parent_id": self.parent_id,
            "kind": self.kind,
            "subject": self.subject,
            "run_id": self.run_id,
            "at": self.at,
            "scope": self.scope,
            "body": dict(self.body),
        }

    def as_json(self) -> str:
        """Pretty-printed. A judge reads these (STANDARDS F8)."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True, default=str)


class Ledger(Protocol):
    """Two implementations, one interface, and neither can mutate.

    The in-memory one is what CI, the recorded demo and a stranger with no AWS
    account run. The DynamoDB one is what is deployed. Coverage that skipped
    the deployed adapter would be a fiction, so it is exercised against a local
    DynamoDB in CI rather than trusted.
    """

    def append(self, entry: Entry) -> Entry: ...

    def thread(self, run_id: str) -> list[Entry]: ...

    def recall(self, subject: str, kind: str, limit: int = 20) -> list[Entry]: ...

    def open_deferrals(self, subject: str = "") -> list[Entry]: ...


def subject_for(repository: str, paths: Sequence[str] = ()) -> str:
    """Derive the memory key from the delivery.

    ``network:organisation`` where it can be determined, falling back to the
    network alone. Erring coarse errs toward recalling more, which is the safe
    direction for a memory whose purpose is to stop the fleet re-deciding
    something it already decided.

    A key that spans unrelated organisations falls back to the network rather
    than borrowing a narrower one, because borrowing would be the global-memory
    bug wearing a different name.
    """
    network = repository.strip() or "unknown-network"
    if not paths:
        return network
    segments = [p.strip("/").split("/") for p in paths if p.strip()]
    if not segments:
        return network
    shared: list[str] = []
    for parts in zip(*segments, strict=False):
        if len(set(parts)) != 1:
            break
        shared.append(parts[0])
    shared = shared[:2]
    return f"{network}:{'/'.join(shared)}" if shared else network


class InMemoryLedger:
    """The offline implementation. Announces itself, so nobody mistakes it."""

    backend = "memory"

    def __init__(self) -> None:
        self._entries: list[Entry] = []

    def append(self, entry: Entry) -> Entry:
        self._entries.append(entry)
        return entry

    def thread(self, run_id: str) -> list[Entry]:
        return sorted(
            (e for e in self._entries if e.run_id == run_id), key=lambda e: e.at
        )

    def recall(self, subject: str, kind: str, limit: int = 20) -> list[Entry]:
        found = [e for e in self._entries if e.subject == subject and e.kind == kind]
        return sorted(found, key=lambda e: e.at, reverse=True)[:limit]

    def open_deferrals(self, subject: str = "") -> list[Entry]:
        found = [
            e
            for e in self._entries
            if e.kind == "finding.deferred"
            and (not subject or e.subject == subject)
            and not self._resolved(e)
        ]
        return sorted(found, key=lambda e: e.at)

    def _resolved(self, deferral: Entry) -> bool:
        target = deferral.entry_id
        return any(
            e.kind == "deferral.escalated" and e.body.get("deferral_id") == target
            for e in self._entries
        )

    def all(self) -> Iterator[Entry]:
        """Everything, oldest first. For the offline demo's thread view only."""
        return iter(sorted(self._entries, key=lambda e: e.at))


class DynamoDbLedger:
    """The deployed implementation. One table, one partition per subject.

    ``PutItem`` carries ``attribute_not_exists(entry_id)`` so a replayed write
    is a condition failure rather than a silent overwrite. That is the same
    primitive the approval nonce uses, for the same reason: on this platform,
    "exactly once" is a condition expression and not a hope.
    """

    backend = "dynamodb"

    def __init__(self, table_name: str = "", client: Any = None) -> None:
        self.table_name = table_name or os.environ.get("MITOS_LEDGER_TABLE", "")
        if not self.table_name:
            raise ValueError("MITOS_LEDGER_TABLE is not set, so there is no ledger")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("dynamodb")
        return self._client

    def append(self, entry: Entry) -> Entry:
        self.client.put_item(
            TableName=self.table_name,
            Item=_to_item(entry),
            ConditionExpression="attribute_not_exists(entry_id)",
        )
        return entry

    def thread(self, run_id: str) -> list[Entry]:
        response = self.client.query(
            TableName=self.table_name,
            IndexName="by-run",
            KeyConditionExpression="run_id = :r",
            ExpressionAttributeValues={":r": {"S": run_id}},
        )
        return sorted(
            (_from_item(item) for item in response.get("Items", [])),
            key=lambda e: e.at,
        )

    def recall(self, subject: str, kind: str, limit: int = 20) -> list[Entry]:
        response = self.client.query(
            TableName=self.table_name,
            KeyConditionExpression="subject = :s",
            FilterExpression="kind = :k",
            ExpressionAttributeValues={":s": {"S": subject}, ":k": {"S": kind}},
            ScanIndexForward=False,
            Limit=max(limit * 4, limit),
        )
        entries = [_from_item(item) for item in response.get("Items", [])]
        return sorted(entries, key=lambda e: e.at, reverse=True)[:limit]

    def open_deferrals(self, subject: str = "") -> list[Entry]:
        if not subject:
            response = self.client.query(
                TableName=self.table_name,
                IndexName="by-kind",
                KeyConditionExpression="kind = :k",
                ExpressionAttributeValues={":k": {"S": "finding.deferred"}},
            )
            candidates = [_from_item(item) for item in response.get("Items", [])]
        else:
            candidates = self.recall(subject, "finding.deferred", limit=200)
        escalated = self._escalated_ids()
        return sorted(
            (e for e in candidates if e.entry_id not in escalated), key=lambda e: e.at
        )

    def _escalated_ids(self) -> set[str]:
        response = self.client.query(
            TableName=self.table_name,
            IndexName="by-kind",
            KeyConditionExpression="kind = :k",
            ExpressionAttributeValues={":k": {"S": "deferral.escalated"}},
        )
        return {
            _from_item(item).body.get("deferral_id", "")
            for item in response.get("Items", [])
        }


def _to_item(entry: Entry) -> dict[str, Any]:
    """DynamoDB's attribute-value shape, written by hand rather than by a resource.

    The low-level client is used deliberately: ``ConditionExpression`` on the
    resource interface is the same feature with more magic between it and the
    call, and this write is the one that must not silently succeed.
    """
    return {
        "subject": {"S": entry.subject},
        "entry_id": {"S": entry.entry_id},
        "parent_id": {"S": entry.parent_id or "-"},
        "kind": {"S": entry.kind},
        "run_id": {"S": entry.run_id},
        "at": {"N": repr(entry.at)},
        "scope": {"S": entry.scope},
        "body": {"S": json.dumps(dict(entry.body), sort_keys=True, default=str)},
    }


def _from_item(item: Mapping[str, Any]) -> Entry:
    parent = item.get("parent_id", {}).get("S", "")
    return Entry(
        kind=item["kind"]["S"],
        subject=item["subject"]["S"],
        run_id=item["run_id"]["S"],
        body=json.loads(item.get("body", {}).get("S", "{}")),
        entry_id=item["entry_id"]["S"],
        parent_id="" if parent == "-" else parent,
        at=float(item["at"]["N"]),
        scope=item.get("scope", {}).get("S", "live"),
    )


@dataclass
class Thread:
    """A run being written, which keeps the chain linked without a caller doing it.

    Every append parents on the entry before it. A caller that had to pass
    ``parent_id`` would eventually forget, and a thread with a gap in it is a
    thread that cannot be walked, which is the one thing this product is named
    after.
    """

    ledger: Any
    subject: str
    run_id: str
    scope: str = "live"
    last_id: str = ""

    def append(self, kind: str, **body: Any) -> Entry:
        entry = self.ledger.append(
            Entry(
                kind=kind,
                subject=self.subject,
                run_id=self.run_id,
                body=body,
                parent_id=self.last_id,
                scope=self.scope,
            )
        )
        self.last_id = entry.entry_id
        return entry

    def recall(self, kind: str, limit: int = 20) -> list[Entry]:
        """What this fleet already decided about this subject, before now."""
        return [
            entry
            for entry in self.ledger.recall(self.subject, kind, limit=limit)
            if entry.run_id != self.run_id
        ]

    def walk(self) -> list[Entry]:
        """The chain, oldest first, following ``parent_id``."""
        entries = {e.entry_id: e for e in self.ledger.thread(self.run_id)}
        ordered: list[Entry] = []
        cursor = self.last_id
        while cursor and cursor in entries:
            entry = entries.pop(cursor)
            ordered.append(entry)
            cursor = entry.parent_id
        ordered.reverse()
        # Anything unreachable from the head is appended rather than dropped. A
        # thread view that silently hid an orphan would hide exactly the entry
        # written by the step that crashed before it could be linked.
        ordered.extend(sorted(entries.values(), key=lambda e: e.at))
        return ordered


def ledger_from_env(env: Mapping[str, str] | None = None) -> Any:
    """Pick a backend from the environment, defaulting to the deployed one.

    The default is DynamoDB deliberately. A demo that quietly falls back to an
    in-memory store shows a stub and nobody watching can tell, so the fallback
    is opt-in by name and announces itself.
    """
    env = os.environ if env is None else env
    choice = env.get("MITOS_LEDGER", "dynamodb").strip().lower()
    if choice == "memory":
        return InMemoryLedger()
    return DynamoDbLedger(table_name=env.get("MITOS_LEDGER_TABLE", ""))


def entries_as_json(entries: Iterable[Entry]) -> str:
    """A whole thread, human readable, for an evidence pack."""
    return json.dumps(
        [entry.as_dict() for entry in entries], indent=2, sort_keys=True, default=str
    )

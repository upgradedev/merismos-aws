"""Cross-process custody against a transactional, service-shape-checked test store.

SQLite here models the DynamoDB transaction boundary, not AWS IAM or deployment.
Two spawned processes use independent DynamoDbLedger instances and share no head cache.
"""

import json
import multiprocessing
import sqlite3

import botocore.session
import pytest
from botocore.exceptions import ClientError
from botocore.validate import validate_parameters

from merismos import custody
from merismos.ledger import DynamoDbLedger, Entry, Thread, _from_item


class TransactionStore:
    def __init__(self, path):
        self.path = path
        self.model = botocore.session.get_session().get_service_model("dynamodb")
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS items (k TEXT PRIMARY KEY, body TEXT)")

    def validate(self, operation, request):
        validate_parameters(request, self.model.operation_model(operation).input_shape)

    @staticmethod
    def key(item):
        return json.dumps([item["subject"]["S"], item["entry_id"]["S"]])

    def get_item(self, **request):
        self.validate("GetItem", request)
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT body FROM items WHERE k=?", (self.key(request["Key"]),)
                             ).fetchone()
        return {"Item": json.loads(row[0])} if row else {}

    def transact_write_items(self, **request):
        self.validate("TransactWriteItems", request)
        puts = [operation["Put"] for operation in request["TransactItems"]]
        assert len(puts) == 2
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            for put in puts:
                row = db.execute("SELECT body FROM items WHERE k=?",
                                 (self.key(put["Item"]),)).fetchone()
                current = json.loads(row[0]) if row else None
                condition = put["ConditionExpression"]
                if condition == "attribute_not_exists(entry_id)":
                    accepted = current is None
                else:
                    assert condition == "last_id = :last"
                    accepted = bool(current and current["last_id"] ==
                                    put["ExpressionAttributeValues"][":last"])
                if not accepted:
                    raise ClientError({"Error": {"Code": "TransactionCanceledException"},
                                       "CancellationReasons": [
                                           {"Code": "ConditionalCheckFailed"}, {"Code": "None"}]},
                                      "TransactWriteItems")
            for put in puts:
                db.execute("INSERT OR REPLACE INTO items VALUES (?, ?)",
                           (self.key(put["Item"]), json.dumps(put["Item"])))

    def entries(self):
        with sqlite3.connect(self.path) as db:
            items = [json.loads(row[0]) for row in db.execute("SELECT body FROM items")]
        return sorted([_from_item(item) for item in items if "kind" in item], key=lambda e: e.at)

    def query(self, **request):
        self.validate("Query", request)
        assert request["IndexName"] == "by-run"
        from merismos.ledger import _to_item

        run = request["ExpressionAttributeValues"][":r"]["S"]
        return {"Items": [_to_item(entry) for entry in self.entries() if entry.run_id == run]}


def append_in_process(path, kind):
    ledger = DynamoDbLedger("fixture-thread", TransactionStore(path))
    Thread(ledger, "net:offers/ambient", "run-new-process").append(kind)


def test_independent_processes_resume_the_persisted_head_and_detect_removal(tmp_path):
    path = str(tmp_path / "transport.sqlite")
    store = TransactionStore(path)
    Thread(DynamoDbLedger("fixture-thread", store), "net:offers/ambient",
           "run-new-process").append("run.started")
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=append_in_process, args=(path, kind))
                 for kind in ("offer.received", "gate.verdict")]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    entries = store.entries()
    assert len(entries) == 3
    assert entries[0].kind == "run.started"
    assert custody.summary("offer-1", entries)["verified"]
    assert not custody.summary("offer-1", [entries[0], entries[2]])["verified"]
    assert not custody.summary("offer-1", list(reversed(entries)))["verified"]


def test_rejected_transaction_relinks_but_transport_unknown_is_never_retried(tmp_path):
    store = TransactionStore(str(tmp_path / "retry.sqlite"))
    ledger = DynamoDbLedger("fixture-thread", store)
    first = ledger.append_linked(Entry(kind="run.started", subject="net", run_id="run-1"))
    duplicate = ledger.append_linked(first)
    assert duplicate == first
    calls = []

    def timeout(**request):
        calls.append(request)
        raise TimeoutError("transaction outcome unknown")

    store.transact_write_items = timeout
    with pytest.raises(TimeoutError, match="unknown"):
        ledger.append_linked(Entry(kind="offer.received", subject="net", run_id="run-1"))
    assert len(calls) == 1
    assert store.entries() == [first]


def test_history_reads_past_filtered_empty_pages_and_refuses_exhaustion():
    marker = {"subject": {"S": "net"}, "entry_id": {"S": "offset-not-first"}}
    calls = []

    class Paged:
        def query(self, **request):
            assert request["ConsistentRead"] is True
            calls.append(request)
            if len(calls) == 1:
                return {"Items": [], "LastEvaluatedKey": marker}
            assert request["ExclusiveStartKey"] == marker
            return {"Items": []}

    ledger = DynamoDbLedger("fixture-thread", Paged())
    assert ledger.recall("net", "record.published") == []
    assert len(calls) == 2
    ledger.client.query = lambda **request: {"LastEvaluatedKey": marker}
    with pytest.raises(ValueError, match="exceeds the read bound"):
        ledger.recall("net", "record.published")


def test_pre_upgrade_headless_run_is_read_only_and_new_run_can_start(tmp_path):
    from merismos.ledger import _to_item

    store = TransactionStore(str(tmp_path / "legacy.sqlite"))
    historic = Entry(kind="run.started", subject="net", run_id="run-old").stamped()
    original = json.dumps(_to_item(historic))
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO items VALUES (?, ?)", (store.key(_to_item(historic)), original))
    ledger = DynamoDbLedger("fixture-thread", store)
    with pytest.raises(ValueError, match="Legacy run"):
        Thread(ledger, "net", "run-old").append("offer.received")
    assert store.entries() == [historic]
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT body FROM items").fetchone()[0] == original
    Thread(ledger, "net", "run-new").append("run.started")
    assert len(store.entries()) == 2

"""Versioned coordinator state; never a public-record or approval store.

DynamoDB uses the existing thread table, in a separate partition without ledger
indexes. SQLite is the explicit offline HTTP harness, with the same CAS contract.
Session handles are hashed before becoming keys. Neither adapter writes S3.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any


class Conflict(ValueError):
    """Somebody changed the state after this caller read it."""


class WorkspaceStore:
    def __init__(self, client: Any = None) -> None:
        self._client = client
        self.table = os.environ.get("MERISMOS_LEDGER_TABLE", "")
        self.path = os.environ.get("MERISMOS_WORKSPACE_DB", "")
        if self.path:
            if os.environ.get("MERISMOS_OFFLINE_HTTP") != "1":
                raise RuntimeError("SQLite requires the explicit offline HTTP harness")
            with self.connection() as db:
                db.execute("CREATE TABLE IF NOT EXISTS workspace ("
                           "id TEXT PRIMARY KEY, version INTEGER, body TEXT, expires REAL)")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @property
    def client(self):
        if self._client is None:
            import boto3

            if not self.table:
                raise RuntimeError("MERISMOS_LEDGER_TABLE is not configured")
            self._client = boto3.client("dynamodb")
        return self._client

    @staticmethod
    def key(identifier: str) -> dict:
        return {"subject": {"S": f"workspace:{identifier}"}, "entry_id": {"S": "state"}}

    def get(self, identifier: str) -> dict | None:
        if self.path:
            with self.connection() as db:
                row = db.execute("SELECT body, expires FROM workspace WHERE id = ?",
                                 (identifier,)).fetchone()
            return json.loads(row[0]) if row and row[1] > time.time() else None
        row = self.client.get_item(TableName=self.table, Key=self.key(identifier),
                                   ConsistentRead=True).get("Item")
        if row and float(row["expires"]["N"]) > time.time():
            return json.loads(row["data"]["S"])
        return None

    def save(self, identifier: str, state: dict, expected: int) -> dict:
        updated = {**state, "version": expected + 1}
        payload = json.dumps(updated, sort_keys=True, separators=(",", ":"))
        # Leave room below DynamoDB's 400 KB item limit. Refuse, never truncate evidence.
        if len(payload.encode()) > 350_000:
            raise ValueError("This workspace is full. Start a new sandbox session.")
        expires = state.get("expires_at", time.time() + 86400)
        if self.path:
            with self.connection() as db:
                if expected == 0:
                    try:
                        db.execute("INSERT INTO workspace VALUES (?, ?, ?, ?)",
                                   (identifier, 1, payload, expires))
                    except sqlite3.IntegrityError as error:
                        raise Conflict("Workspace already exists") from error
                else:
                    result = db.execute("UPDATE workspace SET version=?, body=?, expires=? "
                                        "WHERE id=? AND version=?",
                                        (expected + 1, payload, expires, identifier, expected))
                    if result.rowcount != 1:
                        raise Conflict("Workspace changed. Refresh before trying again.")
            return updated
        values = {**self.key(identifier), "version": {"N": str(expected + 1)},
                  "data": {"S": payload}, "expires": {"N": str(expires)}}
        kwargs: dict[str, Any] = {
            "TableName": self.table, "Item": values,
            "ConditionExpression": "attribute_not_exists(entry_id)" if expected == 0
            else "version = :expected",
        }
        if expected:
            kwargs["ExpressionAttributeValues"] = {":expected": {"N": str(expected)}}
        try:
            self.client.put_item(**kwargs)
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code")
            if code == "ConditionalCheckFailedException":
                raise Conflict("Workspace changed. Refresh before trying again.") from error
            raise
        return updated

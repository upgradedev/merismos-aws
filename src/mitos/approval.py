"""One human, one hash, one use.

An approval here is not a flag saying somebody clicked yes. It is a statement
about **exact bytes**: this person approved this content, for this address, in
this network, until this moment, once. A caller who changes one character after
the approval is refused, and the same approval cannot be spent twice.

Three properties, and each is enforced by a different mechanism, deliberately:

- **what** is bound by sha256 over a canonical serialisation, recomputed by the
  writer from the bytes that actually arrived rather than read from a field the
  caller supplied;
- **when** is bound by an expiry, checked against the writer's clock;
- **once** is bound by a conditional write, so the second attempt is a condition
  failure inside the database rather than a check the code has to remember.

The third is why this is a DynamoDB table and not a field on an object. A nonce
that a process checks and then marks used has a window between the two, and
"exactly once" that depends on nobody racing you is not exactly once.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class ApprovalRefused(Exception):
    """Base class for every reason a write is not performed."""

    status = 403


class NotApproved(ApprovalRefused):
    """No approval exists for this nonce."""


class BytesChanged(ApprovalRefused):
    """An approval exists, and it is not for these bytes."""


class Expired(ApprovalRefused):
    """The approval was real and is no longer current."""

    status = 410


class AlreadySpent(ApprovalRefused):
    """The approval was real, current, and has already produced a write."""

    status = 409


def digest(network: str, key: str, body: str) -> str:
    """The hash the whole design hangs from.

    Canonical, so that the same logical write always produces the same digest,
    and structured, so that moving approved bytes to a different address is a
    different digest rather than the same one. Length-prefixing each field stops
    a caller shifting a delimiter to make two different writes collide.
    """
    parts = (network, key, body)
    payload = "\n".join(f"{len(part)}:{part}" for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Approval:
    """What a person signed, and what the writer will check it against."""

    nonce: str
    network: str
    key: str
    content_digest: str
    approved_by: str
    run_id: str
    expires_at: float
    granted_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "nonce": self.nonce,
            "network": self.network,
            "key": self.key,
            "content_digest": self.content_digest,
            "approved_by": self.approved_by,
            "run_id": self.run_id,
            "expires_at": self.expires_at,
            "granted_at": self.granted_at,
        }

    def as_card(self) -> str:
        """What a person reads before they approve. Human readable, on purpose."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


@dataclass(frozen=True)
class Receipt:
    """What came back, naming who authorised the write and which approval it spent."""

    nonce: str
    network: str
    key: str
    content_digest: str
    approved_by: str
    run_id: str
    published_url: str
    published_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "nonce": self.nonce,
            "network": self.network,
            "key": self.key,
            "content_digest": self.content_digest,
            "approved_by": self.approved_by,
            "run_id": self.run_id,
            "published_url": self.published_url,
            "published_at": self.published_at,
        }


DEFAULT_TTL_SECONDS = 15 * 60


def grant(
    network: str,
    key: str,
    body: str,
    approved_by: str,
    run_id: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: float | None = None,
) -> Approval:
    """Mint an approval over specific bytes.

    ``approved_by`` is required and is not defaulted to a service name. An
    approval that cannot name a person is the thing this design exists to
    prevent, so it raises here rather than publishing something signed by
    nobody.
    """
    if not approved_by.strip():
        raise ValueError("an approval names the person who granted it")
    if not key.strip():
        raise ValueError("an approval names the address it authorises")
    moment = time.time() if now is None else now
    return Approval(
        nonce=uuid.uuid4().hex,
        network=network,
        key=key,
        content_digest=digest(network, key, body),
        approved_by=approved_by.strip(),
        run_id=run_id,
        expires_at=moment + ttl_seconds,
        granted_at=moment,
    )


class ApprovalStore:
    """Where approvals live between the person clicking and the writer publishing.

    ``spend`` is the interesting method. It is not "check then mark"; it is one
    conditional write whose failure is the answer.
    """

    def __init__(self, table_name: str = "", client: Any = None) -> None:
        self.table_name = table_name or os.environ.get("MITOS_APPROVALS_TABLE", "")
        if not self.table_name:
            raise ValueError("MITOS_APPROVALS_TABLE is not set")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("dynamodb")
        return self._client

    def put(self, approval: Approval) -> Approval:
        self.client.put_item(
            TableName=self.table_name,
            Item={
                "nonce": {"S": approval.nonce},
                "network": {"S": approval.network},
                "key": {"S": approval.key},
                "content_digest": {"S": approval.content_digest},
                "approved_by": {"S": approval.approved_by},
                "run_id": {"S": approval.run_id},
                "expires_at": {"N": repr(approval.expires_at)},
                "granted_at": {"N": repr(approval.granted_at)},
                # DynamoDB removes the row itself once it is long past use.
                # Expiry is still checked in code: TTL deletion is eventual and
                # a control that depends on a background sweep is not a control.
                "ttl": {"N": str(int(approval.expires_at) + 86400)},
            },
            ConditionExpression="attribute_not_exists(nonce)",
        )
        return approval

    def get(self, nonce: str) -> Approval | None:
        response = self.client.get_item(
            TableName=self.table_name, Key={"nonce": {"S": nonce}}, ConsistentRead=True
        )
        item = response.get("Item")
        return _from_item(item) if item else None

    def spend(self, nonce: str, now: float | None = None) -> None:
        """Mark this approval used, or raise because somebody already did.

        The condition is the control: ``attribute_not_exists(spent_at)`` on the
        row itself, so two writers racing the same approval produce one write
        and one ``ConditionalCheckFailedException``. Nothing here reads the
        value first and decides.
        """
        moment = time.time() if now is None else now
        try:
            self.client.update_item(
                TableName=self.table_name,
                Key={"nonce": {"S": nonce}},
                UpdateExpression="SET spent_at = :t",
                ConditionExpression=(
                    "attribute_exists(nonce) AND attribute_not_exists(spent_at)"
                ),
                ExpressionAttributeValues={":t": {"N": repr(moment)}},
            )
        except Exception as error:
            if type(error).__name__ == "ConditionalCheckFailedException":
                raise AlreadySpent(
                    "this approval has already produced a published record. "
                    "An approval authorises one write"
                ) from error
            raise


def _from_item(item: Mapping[str, Any]) -> Approval:
    return Approval(
        nonce=item["nonce"]["S"],
        network=item["network"]["S"],
        key=item["key"]["S"],
        content_digest=item["content_digest"]["S"],
        approved_by=item["approved_by"]["S"],
        run_id=item["run_id"]["S"],
        expires_at=float(item["expires_at"]["N"]),
        granted_at=float(item["granted_at"]["N"]),
    )


class InMemoryApprovalStore:
    """The offline equivalent, with the same race behaviour under one process."""

    def __init__(self) -> None:
        self._rows: dict[str, tuple[Approval, float | None]] = {}

    def put(self, approval: Approval) -> Approval:
        if approval.nonce in self._rows:
            raise AlreadySpent("that nonce already exists")
        self._rows[approval.nonce] = (approval, None)
        return approval

    def get(self, nonce: str) -> Approval | None:
        row = self._rows.get(nonce)
        return row[0] if row else None

    def spend(self, nonce: str, now: float | None = None) -> None:
        row = self._rows.get(nonce)
        if row is None:
            raise NotApproved("no such approval")
        approval, spent = row
        if spent is not None:
            raise AlreadySpent(
                "this approval has already produced a published record. "
                "An approval authorises one write"
            )
        self._rows[nonce] = (approval, time.time() if now is None else now)


def authorise(
    store: Any,
    nonce: str,
    network: str,
    key: str,
    body: str,
    now: float | None = None,
) -> Approval:
    """The whole check the writer performs before it publishes anything.

    Order matters. Existence, then bytes, then expiry, then spend. The spend is
    last because it is the only step with an effect, and an approval must not be
    consumed by a request that was going to be refused for another reason.

    The digest is recomputed here from ``body``, the bytes that actually
    arrived. It is never read from the request. A caller who supplies a digest
    is supplying an assertion, and the point of this function is to not take
    one.
    """
    approval = store.get(nonce)
    if approval is None:
        raise NotApproved(f"no approval on file for nonce {nonce[:8]}...")

    recomputed = digest(network, key, body)
    if recomputed != approval.content_digest:
        raise BytesChanged(
            "these are not the bytes that were approved. The approval covers "
            f"{approval.content_digest[:12]}... and this content hashes to "
            f"{recomputed[:12]}..."
        )
    if approval.network != network or approval.key != key:
        raise BytesChanged(
            "the approval authorises a different address to the one requested"
        )

    moment = time.time() if now is None else now
    if moment > approval.expires_at:
        raise Expired(
            "this approval expired "
            f"{int(moment - approval.expires_at)}s ago and was not used. "
            "Approve it again after reading it again"
        )

    store.spend(nonce, now=moment)
    return approval

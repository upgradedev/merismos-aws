"""Where the fleet reads from, behind one interface with two implementations.

A corpus is the network's own filing: its register of member organisations, the
policies those members agreed, and the offers coming in. The local one reads the
directory in this repository, so a stranger with no AWS account gets the real
thing. The S3 one reads a bucket, so a network that has deployed its own fleet
points it at its own filing rather than at ours.

Neither implementation enforces a bound. Every bound lives in ``tools.py``,
deliberately and in one place. A corpus that policed its own reads would mean
the bound could differ between backends, and a bound that differs between
backends is not a bound.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class NotInCorpus(FileNotFoundError):
    """Raised when a path is asked for that the corpus does not hold."""


class Corpus(Protocol):
    """Read a path, or list what there is. Nothing else."""

    def list_paths(self) -> list[str]: ...

    def read(self, path: str) -> str: ...


class LocalCorpus:
    """The directory in this repository. What CI and the recorded demo use."""

    backend = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        default = Path(__file__).resolve().parents[2] / "corpus"
        self.root = Path(root) if root else default
        if not self.root.is_dir():
            raise NotInCorpus(f"no corpus directory at {self.root}")

    def list_paths(self) -> list[str]:
        """Every file, sorted, as posix-style paths relative to the root.

        Sorted rather than in filesystem order so that which files fall inside a
        read budget does not move between runs. A bound that moves cannot be
        audited, and a demo whose output changes on a different machine is a
        demo nobody can check.
        """
        paths = [
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
        ]
        return sorted(paths)

    def read(self, path: str) -> str:
        target = (self.root / path).resolve()
        # Resolved before comparison, so a path that escapes via a symlink is
        # caught here as well as by the traversal check in tools.py. Two layers
        # because this one is about the filesystem and that one is about policy.
        if not str(target).startswith(str(self.root.resolve())):
            raise NotInCorpus(f"{path} resolves outside the corpus")
        if not target.is_file():
            raise NotInCorpus(f"{path} is not in the corpus")
        return target.read_text(encoding="utf-8")


class S3Corpus:
    """A bucket. What a deployed network points at its own filing."""

    backend = "s3"

    def __init__(self, bucket: str = "", prefix: str = "", client: Any = None) -> None:
        self.bucket = bucket or os.environ.get("MERISMOS_CORPUS_BUCKET", "")
        if not self.bucket:
            raise ValueError("MERISMOS_CORPUS_BUCKET is not set, so there is no corpus")
        self.prefix = (prefix or os.environ.get("MERISMOS_CORPUS_PREFIX", "")).lstrip("/")
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    def list_paths(self) -> list[str]:
        paths: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": self.prefix}
            if token:
                kwargs["ContinuationToken"] = token
            response = self.client.list_objects_v2(**kwargs)
            for item in response.get("Contents", []):
                key = item["Key"]
                if key.endswith("/"):
                    continue
                paths.append(key[len(self.prefix) :].lstrip("/"))
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
        return sorted(paths)

    def read(self, path: str) -> str:
        key = f"{self.prefix}/{path}".lstrip("/") if self.prefix else path
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as error:  # noqa: BLE001 - reported as absence, not a crash
            raise NotInCorpus(f"{path} is not in the corpus: {type(error).__name__}") from error
        return response["Body"].read().decode("utf-8")


def offers(corpus: Corpus) -> list[dict[str, Any]]:
    """Every offer the corpus holds, parsed, sorted by id."""
    found = []
    for path in corpus.list_paths():
        if path.startswith("offers/") and path.endswith(".json"):
            found.append(json.loads(corpus.read(path)))
    return sorted(found, key=lambda o: str(o.get("id", "")))


def orgs(corpus: Corpus) -> list[dict[str, Any]]:
    """The register of member organisations, parsed, sorted by id."""
    found = []
    for path in corpus.list_paths():
        if path.startswith("orgs/") and path.endswith(".json"):
            found.append(json.loads(corpus.read(path)))
    return sorted(found, key=lambda o: str(o.get("id", "")))


def org_names(corpus: Corpus) -> frozenset[str]:
    """The names a share may be allocated to, and no others.

    This is what ``gate.check_orgs_exist`` compares against, so a plausible name
    for an organisation that does not exist is refused rather than published.
    """
    return frozenset(str(org.get("name", "")) for org in orgs(corpus) if org.get("name"))


def corpus_from_env(env: dict[str, str] | None = None) -> Corpus:
    """Pick a corpus, defaulting to S3 in a deployment and local otherwise."""
    env = dict(os.environ) if env is None else env
    if env.get("MERISMOS_CORPUS", "").strip().lower() == "local":
        return LocalCorpus(env.get("MERISMOS_CORPUS_ROOT") or None)
    if env.get("MERISMOS_CORPUS_BUCKET"):
        return S3Corpus(
            bucket=env["MERISMOS_CORPUS_BUCKET"], prefix=env.get("MERISMOS_CORPUS_PREFIX", "")
        )
    return LocalCorpus(env.get("MERISMOS_CORPUS_ROOT") or None)

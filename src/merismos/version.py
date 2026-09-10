"""Public build identity from packaged bytes only; no environment or cloud access."""

from __future__ import annotations

import json
import re
from importlib.resources import files


def valid_commit(value: object) -> bool:
    return (isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None
            and value != "0" * 40)


def build_version() -> dict:
    """An unpackaged/invalid build is unknown, even when environment SHAs exist."""
    commit = None
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate build metadata")
                result[key] = value
            return result

        raw = files("merismos").joinpath("build-info.json").read_bytes()
        metadata = json.loads(raw, object_pairs_hook=unique) if len(raw) <= 1024 else None
        if (isinstance(metadata, dict)
                and set(metadata) == {"schema_version", "application", "commit"}
                and type(metadata["schema_version"]) is int
                and metadata["schema_version"] == 1
                and metadata["application"] == "merismos"
                and valid_commit(metadata["commit"])):
            commit = metadata["commit"]
    except (OSError, ValueError, UnicodeError):
        pass
    return {"schema_version": 1, "application": "merismos", "commit": commit,
            "status": "known" if commit else "unknown",
            "source": "ci_package" if commit else "unknown"}

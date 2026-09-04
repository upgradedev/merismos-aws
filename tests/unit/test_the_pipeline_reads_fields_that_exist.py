"""Every field the deploy pipeline reads must be a field the handler serves.

This exists because it had already drifted. `/config` was renamed from
``read_budget_per_run`` to ``read_budget_per_specialist`` when the budget moved,
and `deploy.yml` kept asserting the old name against the old value. `jq -r` on a
missing key returns the string ``null``, so the comparison would simply have
failed on the next deploy, with an error message pointing at a value rather than
at the rename.

The same class of drift then happened again in the other direction on the same
day: `/identity` was restructured so the publish authority and the boundary
canary are reported separately, and every assertion in the pipeline about the
old flat shape became a comparison against ``null``.

A pipeline that can only be checked by running it is a pipeline that is checked
once a week at best. This resolves every path it reads against the real handler
output, offline, in milliseconds.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("MERISMOS_ROLE", "reader")
    monkeypatch.setenv("MERISMOS_LEDGER", "memory")
    monkeypatch.setenv("MERISMOS_CORPUS", "local")
    monkeypatch.setenv("MERISMOS_MODEL", "none")
    monkeypatch.delenv("MERISMOS_PUBLISH_SECRET", raising=False)
    monkeypatch.delenv("MERISMOS_RECORDS_BUCKET", raising=False)


def _served() -> list[dict]:
    """Every document the pipeline pulls a field out of."""
    from merismos import handler

    return [handler.identity(), handler.config()]


def _resolve(document: dict, dotted: str) -> bool:
    cursor = document
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return False
        cursor = cursor[part]
    return True


#: Fields that come from a run result rather than from identity or config.
FROM_A_RUN = {"outcome", "note", "approval_card", "body"}


def test_every_jq_path_in_the_deploy_pipeline_exists():
    workflow = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    paths = sorted(set(re.findall(r"jq -r '\.([A-Za-z_][A-Za-z0-9_.]*)'", workflow)))

    assert paths, "no jq paths found. This test has stopped checking anything"

    documents = _served()
    missing = [
        p
        for p in paths
        if p not in FROM_A_RUN and not any(_resolve(d, p) for d in documents)
    ]

    assert not missing, (
        f"deploy.yml reads {missing}, which the handler does not serve. "
        f"jq returns the string 'null' for these, so the pipeline would fail "
        f"on a value comparison rather than on the rename that caused it"
    )


def test_the_run_fields_the_pipeline_reads_are_actually_produced():
    """The other half. A run result is a different document to identity."""
    from merismos import handler

    result = handler.run({"offer": "offer-4471"})

    for field in ("outcome", "note", "approval_card"):
        assert field in result, f"a run result has no {field}"


def test_the_pipeline_asserts_the_write_and_not_only_the_canary():
    """The correction itself, pinned.

    Asserting only the Secrets Manager refusal would pass a reader that is
    denied a value nothing reads while holding the write that publishes.
    """
    workflow = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    assert "publish_authority.can_write" in workflow, (
        "the pipeline no longer checks the authority that actually publishes"
    )
    assert "boundary_canary.can_read" in workflow


def test_the_teardown_enumerates_before_it_claims_nothing_is_billing():
    """"Nothing is billing" is a claim about AWS, so it is checked against AWS.

    A destroy's exit code is not that claim. On 2026-09-02 a destroy that had
    not run at all was read twice as one that ran and left resources behind,
    because the reading came from a filtered log rather than from the account.
    """
    workflow = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")

    tail = workflow[workflow.index("What is still standing") :]
    for service in ("lambda", "dynamodb", "s3api", "iam", "sqs", "scheduler"):
        assert service in tail, f"the teardown check does not enumerate {service}"
    assert "teardown left resources behind" in tail, (
        "the teardown reports success without failing on leftovers"
    )

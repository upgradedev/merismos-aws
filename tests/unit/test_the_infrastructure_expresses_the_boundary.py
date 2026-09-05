"""The IAM in ``infra/`` is read and asserted, not reviewed by eye.

The README's central claim is that the reader and the evaluator cannot reach the
publish credential and that AWS refuses them rather than our code. That claim
lives in Terraform, so it is checked here against the Terraform, in a test that
runs with no AWS account and no terraform binary.

It is a text-level check and it says so. It cannot prove what AWS will do; only
a deployment can, which is what ``/identity`` is for. What it does prove is that
the file still says what the README says it says, which is the thing that
silently stops being true when somebody adds a policy in a hurry.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[2] / "infra"


@pytest.fixture(scope="module")
def iam() -> str:
    return (INFRA / "iam.tf").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def main() -> str:
    return (INFRA / "main.tf").read_text(encoding="utf-8")


def _statement_blocks(document: str, policy_name: str) -> str:
    """The body of one ``data "aws_iam_policy_document" "<name>"`` block."""
    match = re.search(
        r'data\s+"aws_iam_policy_document"\s+"' + re.escape(policy_name) + r'"\s*\{',
        document,
    )
    assert match, f"no policy document named {policy_name}"
    depth, i = 0, match.end() - 1
    while i < len(document):
        if document[i] == "{":
            depth += 1
        elif document[i] == "}":
            depth -= 1
            if depth == 0:
                return document[match.end() : i]
        i += 1
    raise AssertionError(f"unbalanced braces in {policy_name}")


def test_every_terraform_file_is_present():
    for name in ("main.tf", "iam.tf", "variables.tf", "outputs.tf"):
        assert (INFRA / name).is_file(), f"infra/{name} is missing"


@pytest.mark.parametrize("who", ["reader", "evaluator"])
def test_only_the_writer_is_granted_the_publish_credential(iam, who):
    """The grant. Absence is the primary control."""
    policy = _statement_blocks(iam, who)

    assert "GetSecretValue" not in policy, (
        f"the {who} policy grants GetSecretValue, which dissolves the boundary "
        f"this entry argues for"
    )


def test_the_writer_is_granted_it(iam):
    """The other half. A boundary nobody can cross in either direction is a wall."""
    assert "secretsmanager:GetSecretValue" in _statement_blocks(iam, "writer")


@pytest.mark.parametrize("who", ["reader", "evaluator"])
def test_and_they_are_denied_it_explicitly(iam, who):
    """The Deny survives somebody attaching a broad policy later. A gap does not."""
    deny = _statement_blocks(iam, "never_the_publish_credential")

    assert 'effect    = "Deny"' in deny or 'effect  = "Deny"' in deny
    assert "secretsmanager:GetSecretValue" in deny
    assert re.search(
        r'for_each\s*=\s*toset\(\["reader",\s*"evaluator"\]\)',
        iam,
    ), "the deny is not attached to both of the two roles that need it"


def test_the_evaluator_cannot_read_the_filing_at_all(iam):
    """A gate that can go looking is a gate that can be sent looking."""
    policy = _statement_blocks(iam, "evaluator")

    for forbidden in ("s3:GetObject", "s3:ListBucket", "bedrock:", "lambda:InvokeFunction"):
        assert forbidden not in policy, f"the evaluator holds {forbidden}"


def test_the_writer_cannot_rewrite_the_filing_it_was_judged_against(iam):
    """Otherwise a compromised writer could edit the register to justify itself.

    The writer gained one corpus prefix when the intake form was added, because
    a coordinator filing their own offer is a write and every write in this
    system happens under this one identity. What it must never gain is the two
    prefixes it is measured against: ``orgs/`` is who the members are and
    ``registers/`` is the policy the gate applies. A fleet that can edit the
    rules it is judged by is a fleet whose refusals mean nothing.
    """
    policy = _statement_blocks(iam, "writer")

    assert "records/*" in policy, "the writer's S3 grant is not scoped to the record prefix"

    corpus_grants = re.findall(r"\$\{aws_s3_bucket\.corpus\.arn\}/([^\"]*)", policy)
    assert corpus_grants == ["offers/*"], (
        f"the writer reaches {corpus_grants} of the filing. Only offers/ may be written"
    )


def test_no_identity_may_write_the_register_or_the_policy(iam):
    """Said once for all three, so a new role cannot quietly acquire it."""
    for who in ("reader", "evaluator", "writer"):
        policy = _statement_blocks(iam, who)
        reachable = re.findall(r"\$\{aws_s3_bucket\.corpus\.arn\}/([^\"]*)", policy)
        for prefix in reachable:
            if prefix in ("*", ""):
                # A whole bucket grant is only ever a read here, checked below.
                continue
            assert prefix.startswith("offers/"), f"{who} reaches {prefix} of the filing"


def test_the_identity_a_stranger_talks_to_can_write_nothing_in_s3(iam):
    """The intake form is open to the internet and added the reader no authority.

    This is the claim the feature has to survive. A coordinator adds an offer by
    asking the writer, over the invoke grant the reader already held for
    publishing, so the identity actually serving the form still cannot put a
    single object anywhere. If that stops being true, the whole three-identity
    argument is decoration.
    """
    policy = _statement_blocks(iam, "reader")

    assert "s3:PutObject" not in policy
    assert "s3:DeleteObject" not in policy


def test_the_reader_can_mint_an_approval_and_cannot_spend_one(iam):
    """Spending is the writer's, so the reader cannot forge the receipt."""
    policy = _statement_blocks(iam, "reader")

    approvals = policy[policy.index("MintAnApproval") :]
    approvals = approvals[: approvals.index("}")]
    assert "dynamodb:UpdateItem" not in approvals


def test_the_reader_may_invoke_exactly_two_functions_and_not_a_wildcard(iam):
    policy = _statement_blocks(iam, "reader")

    invoke = policy[policy.index("AskTheOtherTwo") :]
    assert "evaluator" in invoke and "writer" in invoke
    assert 'resources = ["*"]' not in invoke.split("statement")[0]


def test_only_the_reader_answers_a_stranger(main):
    """The half of the boundary a judge can check with curl and no account."""
    assert re.search(
        r'resource\s+"aws_lambda_function_url"\s+"reader"[\s\S]*?authorization_type\s*=\s*"NONE"',
        main,
    ), "the reader's URL is not public, so no judge can check anything"
    assert re.search(
        r'resource\s+"aws_lambda_function_url"\s+"private"[\s\S]*?authorization_type\s*=\s*"AWS_IAM"',
        main,
    ), "the evaluator and writer URLs are not IAM protected"


def test_the_private_urls_cover_both_of_the_other_two(main):
    assert re.search(r'for_each\s*=\s*toset\(\["evaluator",\s*"writer"\]\)', main)


def test_the_records_bucket_is_public_on_one_prefix_and_not_the_bucket(main):
    """A published record is meant to be read by strangers. Nothing else is."""
    assert 'resources = ["${aws_s3_bucket.records.arn}/records/*"]' in main
    assert 'resources = ["${aws_s3_bucket.records.arn}/*"]' not in main


def test_the_filing_bucket_blocks_public_access_entirely(main):
    block = main[main.index('"aws_s3_bucket_public_access_block" "corpus"') :]
    block = block[: block.index("\n}")]

    for setting in (
        "block_public_acls       = true",
        "block_public_policy     = true",
        "ignore_public_acls      = true",
        "restrict_public_buckets = true",
    ):
        assert setting in block, f"the corpus bucket is missing {setting}"


def test_the_model_is_set_on_the_reader_alone(main):
    """A variable a role does not need could be misread as a capability it has."""
    assert 'MERISMOS_MODEL        = each.key == "reader" ? var.model_id : "none"' in main
    assert 'MERISMOS_CRITIC_MODEL = each.key == "reader" ? var.critic_model_id : ""' in main


def test_one_bundle_builds_every_function(main):
    """Several artifacts could drift. One means they provably run the same gate."""
    assert main.count('data "archive_file"') == 1
    assert "filename         = data.archive_file.bundle.output_path" in main
    assert "for_each = local.deployments" in main


def test_the_role_comes_from_terraform_and_not_from_a_request(main):
    assert "MERISMOS_ROLE            = each.value" in main


def test_there_are_more_deployments_than_identities_and_that_is_deliberate(iam):
    """The runner is the reader's own role in its own concurrency pool.

    Not a fourth identity. If it ever acquires its own IAM role, the boundary has
    four members and every count in the README and the docs is wrong, so this
    asserts the mapping rather than the names.
    """
    deployments = iam[iam.index("deployments = {") :]
    deployments = deployments[: deployments.index("}")]

    assert "runner    = \"reader\"" in deployments, "the runner is not the reader's role"
    assert "roles = toset([\"reader\", \"evaluator\", \"writer\"])" in iam, (
        "the boundary no longer has exactly three identities"
    )


def test_the_page_and_the_chore_do_not_share_a_concurrency_pool(main):
    """The defect this split exists for, and it was found on the deployed site.

    Three background chores held three of the reader's five reserved slots, the
    polling of the pages waiting on them took the rest, and API Gateway answered
    every stranger 503 with a body this code never sees. A reservation is still
    the cost guard; what was wrong is that one pool was serving requests that
    must answer in under a second and chores that take about nine minutes.
    """
    reservation = main[main.index("reserved_concurrent_executions") :]
    reservation = reservation[: reservation.index("\n\n")]

    assert "var.reader_reserved_concurrency" in reservation
    assert "var.runner_reserved_concurrency" in reservation, (
        "the chore has no pool of its own, so a run in flight can still 503 the site"
    )


def test_a_request_cannot_hold_a_slot_for_a_quarter_of_an_hour(main):
    """The reader answers requests, and the gateway abandons one at 30 seconds.

    Leaving the reader on the 900 second budget meant an abandoned request went
    on holding a concurrency slot for another fourteen minutes. The long budget
    belongs to the runner, which is the only thing that needs it.
    """
    assert 'each.key == "runner" ? 900 : (each.key == "reader" ? 60 : 30)' in main


def test_the_wake_has_a_dead_letter_queue_and_a_scoped_role(main, iam):
    """A wake that fails silently is a parked decision nobody ever hears about."""
    assert 'resource "aws_sqs_queue" "wake_dlq"' in main
    scheduler = _statement_blocks(iam, "scheduler")
    assert "aws_lambda_function.fleet[\"runner\"].arn" in scheduler
    assert "evaluator" not in scheduler and "writer" not in scheduler


def test_the_scheduler_grant_and_the_schedule_target_name_the_same_function(main, iam):
    """A grant on one function and a schedule on another fails a fortnight later.

    Nothing here notices until a parked decision reaches its date, by which time
    the run that should have escalated it simply did not.
    """
    scheduler = _statement_blocks(iam, "scheduler")
    granted = "runner" if "fleet[\"runner\"]" in scheduler else "reader"

    assert f"function:${{var.project}}-{granted}" in main, (
        "MERISMOS_WAKE_TARGET_ARN names a function the scheduler role cannot invoke"
    )
    permission = main[main.index('"scheduler_may_wake_the_reader"') :]
    permission = permission[: permission.index("\n}")]
    assert f'fleet["{granted}"]' in permission, (
        "the resource policy allows the scheduler to invoke a different function"
    )


def test_the_chore_is_sent_to_the_pool_that_has_the_time_for_it(main):
    assert 'MERISMOS_READER_FUNCTION = "${var.project}-runner"' in main
    assert 'function:${var.project}-runner"' in main, "a wake still targets the reader"


def test_no_variable_the_code_requires_is_left_unset():
    """The direction that actually breaks things, and the one this test missed.

    The sibling below checks that terraform sets nothing the code ignores, which
    is tidiness. This checks that the code requires nothing terraform forgets,
    which is an outage: `os.environ["X"]` with no default raises KeyError, and
    the first live approval returned a 500 because MERISMOS_WRITER_FUNCTION was
    read that way and set nowhere. The publish path failed on the one action the
    whole product exists to perform.

    Only reads without a default are checked. A `.get` with a fallback is a
    choice; a bare subscript is a requirement.
    """
    tf = "\n".join(p.read_text(encoding="utf-8") for p in INFRA.glob("*.tf"))
    source_dir = INFRA.parent / "src" / "merismos"
    code = "\n".join(p.read_text(encoding="utf-8") for p in source_dir.glob("*.py"))

    required = set(re.findall(r'os\.environ\[\s*["\'](MERISMOS_[A-Z_]+)', code))
    provided = set(re.findall(r"\b(MERISMOS_[A-Z_]+)\s*=", tf))

    assert required, "no required variables found. This test has stopped checking anything"
    missing = required - provided
    assert not missing, (
        f"the code requires {sorted(missing)} with no default and terraform sets "
        f"none of them. Every one is a KeyError in a deployed Lambda"
    )


def test_the_handlers_environment_variables_all_exist_in_the_code():
    """Terraform setting a variable nothing reads is YAGNI; the reverse is a bug."""
    main_tf = (INFRA / "main.tf").read_text(encoding="utf-8")
    declared = set(re.findall(r"\b(MERISMOS_[A-Z_]+)\b", main_tf))

    source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (INFRA.parent / "src" / "merismos").glob("*.py")
    )
    read_by_code = set(re.findall(r"\b(MERISMOS_[A-Z_]+)\b", source))

    unread = declared - read_by_code
    assert not unread, f"terraform sets {sorted(unread)} and no code reads them"

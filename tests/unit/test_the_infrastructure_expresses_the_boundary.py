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
    """Otherwise a compromised writer could edit the register to justify itself."""
    policy = _statement_blocks(iam, "writer")

    assert "aws_s3_bucket.corpus" not in policy
    assert "records/*" in policy, "the writer's S3 grant is not scoped to the record prefix"


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


def test_one_bundle_builds_all_three_functions(main):
    """Three artifacts could drift. One means they provably run the same gate."""
    assert main.count('data "archive_file"') == 1
    assert "filename         = data.archive_file.bundle.output_path" in main
    assert 'for_each = local.roles' in main


def test_the_role_comes_from_terraform_and_not_from_a_request(main):
    assert "MERISMOS_ROLE            = each.key" in main


def test_the_wake_has_a_dead_letter_queue_and_a_scoped_role(main, iam):
    """A wake that fails silently is a parked decision nobody ever hears about."""
    assert 'resource "aws_sqs_queue" "wake_dlq"' in main
    scheduler = _statement_blocks(iam, "scheduler")
    assert "aws_lambda_function.fleet[\"reader\"].arn" in scheduler
    assert "evaluator" not in scheduler and "writer" not in scheduler


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

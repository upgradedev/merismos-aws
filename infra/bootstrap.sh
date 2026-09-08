#!/usr/bin/env bash
# The one thing the pipeline cannot create is the pipeline's own credential.
#
# Everything else about this fleet is Terraform, applied by GitHub Actions. Two
# things have to exist before that can happen at all: somewhere to keep the
# state, and a role the workflow may assume. This script makes both, is safe to
# run again, and is checked in so the bootstrap is readable rather than folklore
# about what somebody once clicked.
#
# Run it once, with credentials that can create IAM roles:
#
#   infra/bootstrap.sh
#
# BE HONEST ABOUT WHAT THIS ROLE IS. It holds iam:CreateRole, iam:PutRolePolicy
# and iam:PassRole, because the stack it manages *is* three IAM roles and a
# privilege boundary. Anything that can write IAM can escalate to anything in
# the account. That is inherent to letting a pipeline manage IAM and it is not
# least privilege, so this file does not call it least privilege. The controls
# that actually bound it are narrower than a policy document: the workflow is
# workflow_dispatch only and never fires on a push, the trust policy admits one
# repository and one environment rather than any ref, and the environment can
# carry a required reviewer. The README says the same thing in the same words.
set -euo pipefail

REGION="${AWS_REGION:-eu-west-1}"
PROJECT="${PROJECT:-merismos}"
REPO="${REPO:-upgradedev/merismos-aws}"
ENVIRONMENT="${ENVIRONMENT:-aws}"
STATE_BUCKET="${STATE_BUCKET:-merismos-tfstate-e6ac6047}"
ROLE="${ROLE:-${PROJECT}-github-deploy}"

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
OIDC="arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"

echo "account ${ACCOUNT}, region ${REGION}"

# ---------------------------------------------------------------------------
# The state. Versioned, because a corrupted state file with no history is a
# stack nobody can manage any more, and encrypted and closed to the public,
# because a Terraform state carries every resource name and ARN in the account
# it manages.
# ---------------------------------------------------------------------------
if aws s3api head-bucket --bucket "${STATE_BUCKET}" 2>/dev/null; then
  echo "state bucket ${STATE_BUCKET} exists"
else
  echo "creating state bucket ${STATE_BUCKET}"
  aws s3api create-bucket \
    --bucket "${STATE_BUCKET}" \
    --region "${REGION}" \
    --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
fi

aws s3api put-bucket-versioning \
  --bucket "${STATE_BUCKET}" \
  --versioning-configuration Status=Enabled

aws s3api put-public-access-block \
  --bucket "${STATE_BUCKET}" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

aws s3api put-bucket-encryption \
  --bucket "${STATE_BUCKET}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# ---------------------------------------------------------------------------
# The role. GitHub's OIDC provider already exists in this account, so this only
# adds a role that trusts it, and trusts exactly one repository and one
# environment. Not "repo:owner/name:*": this repository is public, and a
# wildcard there admits any ref anybody can open a pull request from.
#
# **It does not match on `sub`, and that is the whole lesson of 2026-09-08.**
# Two runs failed with "Not authorized to perform sts:AssumeRoleWithWebIdentity"
# against a trust policy that looked correct and matched the shape of every other
# GitHub OIDC role in this account. GitHub has rolled out immutable subject
# claims, which carry numeric ids rather than names, and this repository is on
# the new format while the older ones are not:
#
#   repo:upgradedev/archon-cockroach-memory              the classic prefix
#   repo:upgradedev@25751981/merismos-aws@1338494452     what this repo sends
#
# So copying the working sibling's shape is precisely what carried the mistake
# in. The claims below do not move under either format, and they are **tighter**
# than a name: a rename does not widen them, and another repository that later
# takes this one's name cannot satisfy them, which a name match would allow.
#
# AWS also refuses a GitHub trust policy that does not constrain `sub` at all:
# "must evaluate ... token.actions.githubusercontent.com:sub or
# token.actions.githubusercontent.com:job_workflow_ref which is not scoped to
# all". It is right to insist, so `sub` is in there. What it is not is a guess.
# GitHub publishes the prefix this repository actually sends, so this reads it
# rather than assembling it out of a name that turned out to be the wrong shape.
IDS=$(gh api "repos/${REPO}" --jq '.id, .owner.id' 2>/dev/null || true)
REPO_ID="${REPO_ID:-$(echo "${IDS}" | sed -n 1p)}"
OWNER_ID="${OWNER_ID:-$(echo "${IDS}" | sed -n 2p)}"
SUB_PREFIX="${SUB_PREFIX:-$(gh api "repos/${REPO}/actions/oidc/customization/sub" \
  --jq '.sub_claim_prefix // empty' 2>/dev/null || true)}"
SUB_PREFIX="${SUB_PREFIX:-repo:${REPO}}"

if [ -z "${REPO_ID}" ] || [ -z "${OWNER_ID}" ]; then
  echo "could not read the numeric ids for ${REPO}. Set REPO_ID and OWNER_ID and run again." >&2
  echo "  gh api repos/${REPO} --jq '.id, .owner.id'" >&2
  exit 1
fi
echo "repository ${REPO} is id ${REPO_ID}, owner id ${OWNER_ID}"
echo "subject claim prefix ${SUB_PREFIX}"

TRUST=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "${OIDC}" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "${SUB_PREFIX}:environment:${ENVIRONMENT}",
        "token.actions.githubusercontent.com:repository_id": "${REPO_ID}",
        "token.actions.githubusercontent.com:repository_owner_id": "${OWNER_ID}",
        "token.actions.githubusercontent.com:environment": "${ENVIRONMENT}"
      }
    }
  }]
}
JSON
)

if aws iam get-role --role-name "${ROLE}" >/dev/null 2>&1; then
  echo "role ${ROLE} exists, updating its trust policy"
  aws iam update-assume-role-policy \
    --role-name "${ROLE}" \
    --policy-document "${TRUST}" >/dev/null
else
  echo "creating role ${ROLE}"
  aws iam create-role \
    --role-name "${ROLE}" \
    --description "Deploys the ${PROJECT} fleet from GitHub Actions. Manages IAM, so read the note in infra/bootstrap.sh." \
    --assume-role-policy-document "${TRUST}" \
    --tags "Key=Project,Value=${PROJECT}" >/dev/null
fi

# What it may do. Scoped to this project's own resources where a name allows it,
# and to a service where it does not: an inference profile resolves across
# regions, and IAM's own list and get calls take no useful resource scope.
#
# **The Secrets Manager line reads `${PROJECT}*` and not `${PROJECT}-*` on
# purpose.** Every other resource here is `merismos-something`; the secret is
# `merismos/publish-e6ac6047`, with a slash. The hyphen was a reasonable guess
# and it was still a guess, and the first plan failed on it. A name is not a
# pattern until something has checked it against the name.
POLICY=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "KeepTheState",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:GetBucketVersioning"],
      "Resource": ["arn:aws:s3:::${STATE_BUCKET}", "arn:aws:s3:::${STATE_BUCKET}/*"]
    },
    {
      "Sid": "TheFleetsOwnBuckets",
      "Effect": "Allow",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::${PROJECT}-*", "arn:aws:s3:::${PROJECT}-*/*"]
    },
    {
      "Sid": "ListBucketsToPlan",
      "Effect": "Allow",
      "Action": ["s3:ListAllMyBuckets", "s3:GetBucketLocation"],
      "Resource": "*"
    },
    {
      "Sid": "TheFunctionsAndTheirLayer",
      "Effect": "Allow",
      "Action": "lambda:*",
      "Resource": [
        "arn:aws:lambda:${REGION}:${ACCOUNT}:function:${PROJECT}-*",
        "arn:aws:lambda:${REGION}:${ACCOUNT}:layer:${PROJECT}-*",
        "arn:aws:lambda:${REGION}:${ACCOUNT}:layer:${PROJECT}-*:*"
      ]
    },
    {
      "Sid": "LambdaAccountReadsThatTakeNoResource",
      "Effect": "Allow",
      "Action": ["lambda:GetAccountSettings", "lambda:ListFunctions", "lambda:ListLayers"],
      "Resource": "*"
    },
    {
      "Sid": "TheBoundaryItself",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole",
        "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy", "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies", "iam:UpdateAssumeRolePolicy", "iam:PassRole"
      ],
      "Resource": [
        "arn:aws:iam::${ACCOUNT}:role/${PROJECT}-*"
      ]
    },
    {
      "Sid": "TheThreadAndTheApprovals",
      "Effect": "Allow",
      "Action": "dynamodb:*",
      "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/${PROJECT}-*"
    },
    {
      "Sid": "TheJudgesDoor",
      "Effect": "Allow",
      "Action": "apigateway:*",
      "Resource": "arn:aws:apigateway:${REGION}::*"
    },
    {
      "Sid": "TheWakes",
      "Effect": "Allow",
      "Action": ["scheduler:*"],
      "Resource": [
        "arn:aws:scheduler:${REGION}:${ACCOUNT}:schedule-group/${PROJECT}-*",
        "arn:aws:scheduler:${REGION}:${ACCOUNT}:schedule/${PROJECT}-*/*"
      ]
    },
    {
      "Sid": "ListSchedulerToPlan",
      "Effect": "Allow",
      "Action": ["scheduler:ListScheduleGroups", "scheduler:ListSchedules"],
      "Resource": "*"
    },
    {
      "Sid": "TheDeadLetterQueue",
      "Effect": "Allow",
      "Action": "sqs:*",
      "Resource": "arn:aws:sqs:${REGION}:${ACCOUNT}:${PROJECT}-*"
    },
    {
      "Sid": "ListQueuesToProve",
      "Effect": "Allow",
      "Action": ["sqs:ListQueues"],
      "Resource": "*"
    },
    {
      "Sid": "TheBoundaryCanary",
      "Effect": "Allow",
      "Action": "secretsmanager:*",
      "Resource": "arn:aws:secretsmanager:${REGION}:${ACCOUNT}:secret:${PROJECT}*"
    },
    {
      "Sid": "TheLogsAndTheAlarms",
      "Effect": "Allow",
      "Action": ["logs:*", "cloudwatch:*"],
      "Resource": "*"
    },
    {
      "Sid": "WhoAmI",
      "Effect": "Allow",
      "Action": ["sts:GetCallerIdentity", "iam:ListRoles"],
      "Resource": "*"
    }
  ]
}
JSON
)

aws iam put-role-policy \
  --role-name "${ROLE}" \
  --policy-name "manage-the-fleet" \
  --policy-document "${POLICY}" >/dev/null

ARN="arn:aws:iam::${ACCOUNT}:role/${ROLE}"
echo
echo "state bucket : ${STATE_BUCKET}"
echo "deploy role  : ${ARN}"
echo
echo "Put that ARN in the repository as the AWS_DEPLOY_ROLE_ARN secret of the"
echo "'${ENVIRONMENT}' environment. It is an identifier rather than a credential:"
echo "the workflow exchanges a short lived OIDC token for it, and no long lived"
echo "AWS key is stored anywhere in this repository."
echo
echo "  gh secret set AWS_DEPLOY_ROLE_ARN --env ${ENVIRONMENT} --body '${ARN}'"

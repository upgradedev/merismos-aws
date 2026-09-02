###############################################################################
# The privilege boundary. This file is the entry's central claim, so it is its
# own file rather than a section of main.tf.
#
# Three roles. Only merismos-writer can read the publish credential, and the
# other two are refused by AWS rather than by anything in our code. That is what
# /identity demonstrates live: it calls GetSecretValue and reports what came
# back.
#
# The refusal is expressed twice, deliberately:
#
#   1. No grant. The reader and evaluator policies simply do not include
#      secretsmanager:GetSecretValue on the publish secret.
#   2. An explicit Deny on that one ARN.
#
# (1) alone is the cleaner statement and would be enough today. (2) exists
# because an explicit Deny cannot be overridden by any later Allow, from any
# policy, attached by anyone. The failure this guards against is not a bug in
# this file; it is somebody in six months attaching a broad
# SecretsManagerReadWrite policy to the reader for an unrelated reason and
# silently dissolving the boundary the whole product argues for. A Deny survives
# that. A missing Allow does not.
###############################################################################

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

locals {
  roles = toset(["reader", "evaluator", "writer"])
}

resource "aws_iam_role" "fleet" {
  for_each           = local.roles
  name               = "${var.project}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Project = var.project
    Role    = each.key
  }
}

# Writing its own logs is the one thing all three may do, and it is scoped to
# each function's own log group rather than to "*".
data "aws_iam_policy_document" "logs" {
  for_each = local.roles
  statement {
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.fleet[each.key].arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "logs" {
  for_each = local.roles
  name     = "logs"
  role     = aws_iam_role.fleet[each.key].id
  policy   = data.aws_iam_policy_document.logs[each.key].json
}

###############################################################################
# The reader. Orchestrates everything and can publish nothing.
###############################################################################

data "aws_iam_policy_document" "reader" {
  # Read the network's own filing. Read only: the fleet never edits the register
  # it is judging against.
  statement {
    sid       = "ReadTheFiling"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.corpus.arn, "${aws_s3_bucket.corpus.arn}/*"]
  }

  # The provenance thread is append only by interface. IAM cannot express "no
  # overwrite", so PutItem is granted and the condition expression in
  # ledger.append is what enforces it. Stated rather than implied: a principal
  # with this policy could overwrite a row from outside our code.
  statement {
    sid       = "AppendToTheThread"
    actions   = ["dynamodb:PutItem", "dynamodb:Query", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.thread.arn, "${aws_dynamodb_table.thread.arn}/index/*"]
  }

  # Mint an approval. Not spend one: UpdateItem is the writer's, so the reader
  # cannot mark an approval used and cannot forge the receipt that follows.
  statement {
    sid       = "MintAnApproval"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem"]
    resources = [aws_dynamodb_table.approvals.arn]
  }

  statement {
    sid       = "AskTheModels"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse"]
    resources = ["*"] # Inference profiles resolve across regions; a narrower ARN breaks them.
  }

  # Ask the evaluator to judge, and the writer to publish. Naming the two
  # functions rather than "*" is what stops a compromised reader invoking
  # anything else in the account.
  statement {
    sid       = "AskTheOtherTwo"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.fleet["evaluator"].arn, aws_lambda_function.fleet["writer"].arn]
  }

  # Park a decision until a date. Delete is included so a superseded deferral
  # can be withdrawn; a fired schedule deletes itself via ActionAfterCompletion.
  statement {
    sid       = "ScheduleAWake"
    actions   = ["scheduler:CreateSchedule", "scheduler:DeleteSchedule", "scheduler:GetSchedule"]
    resources = ["arn:aws:scheduler:${var.region}:${data.aws_caller_identity.me.account_id}:schedule/${aws_scheduler_schedule_group.wakes.name}/*"]
  }

  statement {
    sid       = "LetTheSchedulerAssumeItsOwnRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.scheduler.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["scheduler.amazonaws.com"]
    }
  }
}

###############################################################################
# The evaluator. Judges the bytes it was handed and reaches for nothing.
#
# It holds no S3 read, no Bedrock, and no corpus access at all. A gate that can
# go looking is a gate that can be sent looking, and the deterministic checks
# need nothing but the draft in the request.
###############################################################################

data "aws_iam_policy_document" "evaluator" {
  statement {
    sid       = "RecordTheVerdict"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.thread.arn]
  }
}

###############################################################################
# The writer. Publishes an approved record and does nothing else.
###############################################################################

data "aws_iam_policy_document" "writer" {
  statement {
    sid       = "ReadThePublishCredential"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.publish.arn]
  }

  # Spend the approval. UpdateItem with a condition expression is what makes
  # "exactly once" a property of the database rather than of our code.
  statement {
    sid       = "SpendTheApproval"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.approvals.arn]
  }

  statement {
    sid       = "RecordThePublish"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.thread.arn]
  }

  # Write the record, and only under records/. The writer cannot touch the
  # filing the fleet judged against, so a compromised writer cannot rewrite the
  # register to justify what it published.
  statement {
    sid       = "PublishTheRecord"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.records.arn}/records/*"]
  }
}

resource "aws_iam_role_policy" "reader" {
  name   = "reader"
  role   = aws_iam_role.fleet["reader"].id
  policy = data.aws_iam_policy_document.reader.json
}

resource "aws_iam_role_policy" "evaluator" {
  name   = "evaluator"
  role   = aws_iam_role.fleet["evaluator"].id
  policy = data.aws_iam_policy_document.evaluator.json
}

resource "aws_iam_role_policy" "writer" {
  name   = "writer"
  role   = aws_iam_role.fleet["writer"].id
  policy = data.aws_iam_policy_document.writer.json
}

###############################################################################
# The explicit Deny. Reason (2) at the top of this file.
###############################################################################

data "aws_iam_policy_document" "never_the_publish_credential" {
  statement {
    sid       = "TheReaderAndEvaluatorMayNeverReadThePublishCredential"
    effect    = "Deny"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.publish.arn]
  }
}

resource "aws_iam_role_policy" "never_the_publish_credential" {
  for_each = toset(["reader", "evaluator"])
  name     = "never-the-publish-credential"
  role     = aws_iam_role.fleet[each.key].id
  policy   = data.aws_iam_policy_document.never_the_publish_credential.json
}

###############################################################################
# The scheduler's own role. It may wake the reader and do nothing else.
#
# An unattended wake is limited to appending an escalation, which is enforced in
# handler._wake. This role is the second half of that: even if the code were
# wrong, the scheduler can invoke one function and holds no other permission.
###############################################################################

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.me.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
  tags               = { Project = var.project }
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.fleet["reader"].arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.wake_dlq.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "wake-the-reader"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

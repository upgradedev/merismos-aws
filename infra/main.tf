terraform {
  required_version = ">= 1.6"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.60" }
    archive = { source = "hashicorp/archive", version = "~> 2.4" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project = var.project
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "me" {}

# Bucket names are global, so a suffix is needed for a second fleet to deploy at
# all. Random rather than the account id: the account id in a public bucket name
# is an unnecessary disclosure on a bucket that is meant to be read by strangers.
resource "random_id" "suffix" {
  byte_length = 4
}

###############################################################################
# The bundle. One package, three functions.
#
# What fixes each deployment's authority is its role and its MERISMOS_ROLE, not
# its code. Building three artifacts would let them drift; building one means
# the reader and the writer are provably running the same gate.
###############################################################################

data "archive_file" "bundle" {
  type        = "zip"
  output_path = "${path.module}/.build/merismos.zip"

  source_dir = "${path.module}/../src"
  excludes   = ["**/__pycache__/**", "**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "fleet" {
  for_each          = local.roles
  name              = "/aws/lambda/${var.project}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fleet" {
  for_each = local.roles

  function_name    = "${var.project}-${each.key}"
  role             = aws_iam_role.fleet[each.key].arn
  handler          = "merismos.handler.handler"
  runtime          = "python3.13"
  filename         = data.archive_file.bundle.output_path
  source_code_hash = data.archive_file.bundle.output_base64sha256

  # The reader runs a model that reads files and thinks. The other two do
  # arithmetic and one write, so they get less of both.
  timeout     = each.key == "reader" ? 300 : 30
  memory_size = each.key == "reader" ? 1024 : 512

  layers = [aws_lambda_layer_version.deps.arn]

  environment {
    variables = {
      MERISMOS_ROLE            = each.key
      MERISMOS_NETWORK         = var.network
      MERISMOS_LEDGER_TABLE    = aws_dynamodb_table.thread.name
      MERISMOS_APPROVALS_TABLE = aws_dynamodb_table.approvals.name
      MERISMOS_CORPUS_BUCKET   = aws_s3_bucket.corpus.id
      MERISMOS_RECORDS_BUCKET  = aws_s3_bucket.records.id
      MERISMOS_PUBLISH_SECRET  = aws_secretsmanager_secret.publish.arn
      MERISMOS_BUILD_SHA       = var.build_sha

      # The model is set on the reader alone. The evaluator is deterministic by
      # design and the writer publishes bytes it was handed, so neither has any
      # use for one, and a variable they do not need is a variable that could be
      # misread as a capability they have.
      MERISMOS_MODEL        = each.key == "reader" ? var.model_id : "none"
      MERISMOS_CRITIC_MODEL = each.key == "reader" ? var.critic_model_id : ""

      MERISMOS_WAKE_TARGET_ARN   = "arn:aws:lambda:${var.region}:${data.aws_caller_identity.me.account_id}:function:${var.project}-reader"
      MERISMOS_SCHEDULER_ROLE_ARN = aws_iam_role.scheduler.arn
      MERISMOS_SCHEDULE_GROUP     = aws_scheduler_schedule_group.wakes.name
      MERISMOS_WAKE_DLQ_ARN       = aws_sqs_queue.wake_dlq.arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.fleet]
}

# Dependencies as a layer so the function bundle stays small and a code change
# does not re-upload boto3 and Strands.
resource "aws_lambda_layer_version" "deps" {
  layer_name          = "${var.project}-deps"
  filename            = "${path.module}/.build/deps.zip"
  compatible_runtimes = ["python3.13"]
  source_code_hash    = filebase64sha256("${path.module}/.build/deps.zip")

  lifecycle {
    # Built by infra/build.sh before apply. Terraform does not build it, because
    # a pip install inside a terraform run is a build nobody can reproduce.
    ignore_changes = []
  }
}

###############################################################################
# Function URLs. The reader answers a stranger. The other two do not.
#
# This is the half of the boundary a judge can check without an account: the
# reader returns 200 and the evaluator and writer return 403 to anyone who is
# not signing requests with the reader's credentials.
###############################################################################

resource "aws_lambda_function_url" "reader" {
  function_name      = aws_lambda_function.fleet["reader"].function_name
  authorization_type = "NONE"

  cors {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST"]
    max_age       = 300
  }
}

resource "aws_lambda_function_url" "private" {
  for_each           = toset(["evaluator", "writer"])
  function_name      = aws_lambda_function.fleet[each.key].function_name
  authorization_type = "AWS_IAM"
}

###############################################################################
# State
###############################################################################

resource "aws_dynamodb_table" "thread" {
  name         = "${var.project}-thread"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "subject"
  range_key    = "entry_id"

  attribute {
    name = "subject"
    type = "S"
  }
  attribute {
    name = "entry_id"
    type = "S"
  }
  attribute {
    name = "run_id"
    type = "S"
  }
  attribute {
    name = "kind"
    type = "S"
  }

  # Follow one run back as a chain.
  global_secondary_index {
    name            = "by-run"
    hash_key        = "run_id"
    projection_type = "ALL"
  }

  # Every open deferral, across every subject, which is what the wake path reads.
  global_secondary_index {
    name            = "by-kind"
    hash_key        = "kind"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "approvals" {
  name         = "${var.project}-approvals"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "nonce"

  attribute {
    name = "nonce"
    type = "S"
  }

  # DynamoDB removes a long expired approval on its own. Expiry is still checked
  # in code: TTL deletion is eventual, and a control that depends on a
  # background sweep is not a control.
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

###############################################################################
# Buckets
###############################################################################

# The network's own filing. Private. Read by the reader and by nobody else.
resource "aws_s3_bucket" "corpus" {
  bucket = "${var.project}-corpus-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "corpus" {
  bucket                  = aws_s3_bucket.corpus.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "corpus" {
  bucket = aws_s3_bucket.corpus.id
  versioning_configuration {
    status = "Enabled"
  }
}

# The published records. Public read on one prefix, because the whole point is
# that a funder or a member can read them with no account.
resource "aws_s3_bucket" "records" {
  bucket = "${var.project}-records-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "records" {
  bucket = aws_s3_bucket.records.id
  # ACLs stay blocked. Only the bucket policy below opens anything, and it opens
  # exactly one prefix, so a future object written elsewhere in this bucket is
  # not public by accident.
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = false
  restrict_public_buckets = false
}

data "aws_iam_policy_document" "records_public_read" {
  statement {
    sid       = "AnyoneMayReadAPublishedRecord"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.records.arn}/records/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
  }
}

resource "aws_s3_bucket_policy" "records" {
  bucket     = aws_s3_bucket.records.id
  policy     = data.aws_iam_policy_document.records_public_read.json
  depends_on = [aws_s3_bucket_public_access_block.records]
}

resource "aws_s3_bucket_versioning" "records" {
  bucket = aws_s3_bucket.records.id
  # A published record is permanent. Versioning is what makes an accidental
  # overwrite recoverable, which matters more here than anywhere else in the
  # stack because the readers of this bucket are outside the organisation.
  versioning_configuration {
    status = "Enabled"
  }
}

# Seed the filing so a fresh deployment has something to apportion. Terraform
# owns these because a judge cloning this repository and applying it should get
# a working fleet, not an empty bucket and a runbook.
resource "aws_s3_object" "corpus" {
  for_each = fileset("${path.module}/../corpus", "**")

  bucket = aws_s3_bucket.corpus.id
  key    = each.value
  source = "${path.module}/../corpus/${each.value}"
  etag   = filemd5("${path.module}/../corpus/${each.value}")
}

###############################################################################
# The publish credential
###############################################################################

resource "aws_secretsmanager_secret" "publish" {
  name                    = "${var.project}/publish"
  description             = "Readable by ${var.project}-writer alone. The reader and the evaluator are denied."
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "publish" {
  secret_id = aws_secretsmanager_secret.publish.id
  # The writer publishes to S3 with its own role, so this holds a marker rather
  # than a credential. It is real infrastructure: /identity attempts to read it
  # from all three roles and reports what IAM said, and that answer is the same
  # whatever the bytes are.
  secret_string = jsonencode({
    purpose = "the publish credential. Only ${var.project}-writer may read this."
  })
}

###############################################################################
# The wake
###############################################################################

resource "aws_scheduler_schedule_group" "wakes" {
  name = "${var.project}-wakes"
}

resource "aws_sqs_queue" "wake_dlq" {
  name                      = "${var.project}-wake-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_lambda_permission" "scheduler_may_wake_the_reader" {
  statement_id  = "AllowSchedulerInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fleet["reader"].function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = "arn:aws:scheduler:${var.region}:${data.aws_caller_identity.me.account_id}:schedule/${aws_scheduler_schedule_group.wakes.name}/*"
}

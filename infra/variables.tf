variable "project" {
  description = "Name prefix for every resource. Changing it deploys a second, independent fleet."
  type        = string
  default     = "merismos"
}

variable "region" {
  description = "The AWS region. Bedrock inference profiles are geography prefixed separately, in model_id."
  type        = string
  default     = "eu-west-1"
}

variable "network" {
  description = "The community network this fleet apportions for. It is the memory's top level key."
  type        = string
  default     = "kypseli-network"
}

variable "model_id" {
  description = <<-EOT
    The Bedrock inference profile the specialists read with. Set to "none" to deploy
    the deterministic path with no model, which is a real configuration rather than a
    fallback: the fleet reports which of the two it ran.
  EOT
  type        = string
  default     = "eu.anthropic.claude-opus-5"
}

variable "critic_model_id" {
  description = <<-EOT
    The independent second read, from a different model family. Empty means no critic,
    which is the default. It is a separate variable from model_id on purpose: one
    ambiguous MODEL would let a single edit move the whole fleet onto a review model.
  EOT
  type        = string
  default     = ""
}

variable "build_sha" {
  description = "The commit this bundle was built from. Reported by /identity so a deployment can be identified."
  type        = string
  default     = "unknown"
}

variable "log_retention_days" {
  description = "Provenance lives in DynamoDB for six years. CloudWatch is operational noise and expires."
  type        = number
  default     = 14
}

variable "destroyable" {
  description = <<-EOT
    Whether terraform destroy may empty the buckets. True for a demonstrator that
    has to be able to disappear; a network running this for real sets it false,
    because a published record is permanent and a destroy should not be able to
    erase the answer somebody will ask for months later.
  EOT
  type        = bool
  default     = true
}

variable "judge_rate_limit" {
  description = <<-EOT
    Requests per second the judge URL will serve before throttling. Deliberately
    low: this serves a handful of people reading a few pages, not a launch. An
    open endpoint with no ceiling is one somebody else can spend your money
    through.
  EOT
  type        = number
  default     = 10
}

variable "judge_burst_limit" {
  description = "Burst allowance above the steady rate, for a page that loads several things at once."
  type        = number
  default     = 20
}

variable "judge_hourly_alarm" {
  description = <<-EOT
    Invocations in one hour that mean something other than judging is happening.
    A panel reading every screen of every offer is well under a hundred.
  EOT
  type        = number
  default     = 500
}

variable "reader_reserved_concurrency" {
  description = <<-EOT
    How many readers may run at once. A burst through the gateway would otherwise
    become an unbounded number of concurrent Lambdas, each able to call Bedrock.
    -1 disables the reservation.
  EOT
  type        = number
  default     = 5
}

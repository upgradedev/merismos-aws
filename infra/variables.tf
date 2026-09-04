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

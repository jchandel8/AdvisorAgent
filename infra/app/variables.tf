variable "region" {
  type    = string
  default = "us-west-1"
}

variable "image_tag" {
  description = "Image tag in the advisoragent ECR repository (the deploy workflow passes the git SHA)"
  type        = string
}

# Public identifiers from `infra/tf.sh persistent output` (not secrets); see demo.auto.tfvars.
variable "cognito_user_pool_id" {
  type = string
}

variable "cognito_client_id" {
  type = string
}

variable "cognito_domain" {
  type = string
}

variable "llm_provider" {
  description = "bedrock: Claude on Amazon Bedrock with the task role (no API key). anthropic: Anthropic API key from Secrets Manager."
  type        = string
  default     = "bedrock"
  validation {
    condition     = contains(["bedrock", "anthropic"], var.llm_provider)
    error_message = "llm_provider must be bedrock or anthropic."
  }
}

# Bedrock IDs are US cross-region inference profiles. The 5.5 models (us.anthropic.claude-sonnet-5-5 and
# us.anthropic.claude-haiku-5-5) return "not available for this account" until AWS enables them for the
# account; switch these two defaults once they are. With llm_provider = anthropic use claude-sonnet-5-5 /
# claude-haiku-5-5.
variable "anthropic_model" {
  description = "The assistant's main model"
  type        = string
  default     = "us.anthropic.claude-sonnet-4-6"
}

variable "guard_model" {
  description = "The small model for the assistant's scope check"
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

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

variable "anthropic_model" {
  type    = string
  default = "claude-sonnet-5-5"
}

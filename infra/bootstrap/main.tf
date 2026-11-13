# One-time setup, applied by the owner (local state). Creates:
#  - the S3 bucket that holds the "app" stack's Terraform state (so GitHub Actions can deploy and tear down)
#  - GitHub's OIDC identity provider and a deploy role, so workflows get short-lived AWS credentials
#    without any stored access keys.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.27"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "AdvisorAgent", Stack = "bootstrap", ManagedBy = "terraform" }
  }
}

variable "region" {
  type    = string
  default = "us-west-1"
}

variable "github_repo" {
  description = "owner/name of the GitHub repository allowed to deploy"
  type        = string
  default     = "jchandel8/AdvisorAgent"
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "tfstate" {
  bucket = "advisoragent-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# Only this repository's "demo" environment can assume the role. Jobs that use an environment get the OIDC
# subject repo:<owner>/<repo>:environment:<name> (not the branch), so the branch rule lives on the GitHub
# side: the demo environment's deployment branches are limited to main (see docs/DEPLOY.md).
data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:environment:demo"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "advisoragent-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_trust.json
  max_session_duration = 3600
}

# Terraform creates IAM roles, RDS, ECS and more, so the deploy role needs broad rights. It is limited to
# this repository's demo environment (main branch only) and short-lived sessions. Tighten to a custom policy before real use.
resource "aws_iam_role_policy_attachment" "github_deploy_admin" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

output "TFSTATE_BUCKET" {
  value = aws_s3_bucket.tfstate.bucket
}

output "AWS_DEPLOY_ROLE_ARN" {
  description = "Add as a GitHub repository variable named AWS_DEPLOY_ROLE_ARN"
  value       = aws_iam_role.github_deploy.arn
}

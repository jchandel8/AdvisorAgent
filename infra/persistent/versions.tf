terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.27"
    }
  }
  # Local state for now (gitignored). Step 5 moves state to an S3 bucket, with the owner's permission.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "AdvisorAgent"
      Stack     = "persistent"
      ManagedBy = "terraform"
    }
  }
}

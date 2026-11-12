# The disposable part of the deployment: database + ECS Express service. "Deploy demo" applies it and
# "Tear down" destroys it (GitHub Actions); everything is re-seeded on the next deploy.
terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.27"
    }
  }
  # Bucket is passed at init: terraform init -backend-config="bucket=<TFSTATE_BUCKET>"
  backend "s3" {
    key          = "app/terraform.tfstate"
    region       = "us-west-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "AdvisorAgent", Stack = "app", ManagedBy = "terraform" }
  }
}

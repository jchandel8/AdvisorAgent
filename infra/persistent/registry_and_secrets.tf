# Kept across demo teardowns: the image registry and the secrets the app reads.

resource "aws_ecr_repository" "app" {
  name                 = "advisoragent"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 10 most recent images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

# Secret containers only. Terraform never sees the values: the owner sets them once with
#   aws secretsmanager put-secret-value --secret-id advisoragent/anthropic-api-key --secret-string '...'
#   aws secretsmanager put-secret-value --secret-id advisoragent/demo-password --secret-string '...'
resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "advisoragent/anthropic-api-key"
  description             = "Anthropic API key for the advisor assistant"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "demo_password" {
  name                    = "advisoragent/demo-password"
  description             = "Shared password for the demo logins"
  recovery_window_in_days = 0
}

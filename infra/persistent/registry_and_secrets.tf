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

# Secret container only. Terraform never sees the value: the owner sets it once with
#   aws secretsmanager put-secret-value --secret-id advisoragent/demo-password --secret-string '...'
# (No Claude API key on AWS: the app calls Claude on Bedrock with its IAM task role.)
resource "aws_secretsmanager_secret" "demo_password" {
  name                    = "advisoragent/demo-password"
  description             = "Shared password for the demo logins"
  recovery_window_in_days = 0
}

# News search for the AI Finalyst's Market MCP server. Container only; the owner sets the value once with
#   aws secretsmanager put-secret-value --secret-id advisoragent/tavily-api-key --secret-string '...'
# Only public news queries are sent with it (the app refuses queries containing client data).
resource "aws_secretsmanager_secret" "tavily_api_key" {
  name                    = "advisoragent/tavily-api-key"
  description             = "Tavily API key for the AI Finalyst's news search"
  recovery_window_in_days = 0
}

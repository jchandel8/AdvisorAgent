data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ecr_repository" "app" {
  name = "advisoragent"
}

data "aws_secretsmanager_secret" "demo_password" {
  name = "advisoragent/demo-password"
}

locals {
  # Inference profile "us.anthropic.claude-x" routes to foundation model "anthropic.claude-x" in US regions.
  model_profiles = distinct([var.anthropic_model, var.guard_model])
  profile_arns = [
    for m in local.model_profiles : "arn:aws:bedrock:${var.region}:${data.aws_caller_identity.current.account_id}:inference-profile/${m}"
  ]
  foundation_model_arns = [
    for m in local.model_profiles : "arn:aws:bedrock:*::foundation-model/${replace(m, "/^(us|global)\\./", "")}"
  ]
  # Secrets the container receives at start. No Claude API key: Bedrock is called with the task role.
  secret_arns = [data.aws_secretsmanager_secret.demo_password.arn, aws_db_instance.db.master_user_secret[0].secret_arn]
}

# --- Database --------------------------------------------------------------------------------------
# Not publicly accessible. Reachable only from inside the default VPC (where the ECS tasks run), and only
# with the password RDS keeps in Secrets Manager (manage_master_user_password). Disposable: the app
# re-seeds an empty database on start, so no final snapshot.

resource "aws_security_group" "db" {
  name        = "advisoragent-db"
  description = "Postgres from inside the VPC only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Postgres from the VPC (ECS tasks)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.default.cidr_block]
  }
}

resource "aws_db_subnet_group" "db" {
  name       = "advisoragent"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "db" {
  identifier                  = "advisoragent"
  engine                      = "postgres"
  engine_version              = "17"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  db_name                     = "wealth"
  username                    = "wealth_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.db.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  publicly_accessible         = false
  multi_az                    = false
  backup_retention_period     = 1
  skip_final_snapshot         = true
  deletion_protection         = false
  apply_immediately           = true
}

# --- Document files ---------------------------------------------------------------------------------
# Uploaded documents. Private (all public access blocked, owner-enforced, TLS only), encrypted at rest. Part of
# the disposable demo: Tear down empties and deletes it (force_destroy), like the database. The API streams
# files itself, so nothing is ever served from the bucket directly.

resource "aws_s3_bucket" "documents" {
  bucket        = "advisoragent-documents-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "documents_tls_only" {
  bucket     = aws_s3_bucket.documents.id
  depends_on = [aws_s3_bucket_public_access_block.documents]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# --- IAM -------------------------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "ecs_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com"]
    }
  }
}

# Execution role: pull the image, write logs, read the app's secrets at container start.
resource "aws_iam_role" "execution" {
  name               = "advisoragent-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy_attachment" "execution_base" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "read-app-secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = local.secret_arns
    }]
  })
}

# Infrastructure role: lets ECS Express create and manage the load balancer, target groups and scaling.
resource "aws_iam_role" "infrastructure" {
  name               = "advisoragent-express-infrastructure"
  assume_role_policy = data.aws_iam_policy_document.ecs_trust.json
}

resource "aws_iam_role_policy_attachment" "infrastructure" {
  role       = aws_iam_role.infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

# Task role: what the running app may call. Cognito user administration (admin portal, demo logins) and the
# two Claude models on Bedrock.
resource "aws_iam_role" "task" {
  name               = "advisoragent-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy" "task_cognito" {
  name = "manage-demo-logins"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "cognito-idp:AdminCreateUser",
        "cognito-idp:AdminSetUserPassword",
        "cognito-idp:AdminAddUserToGroup",
        "cognito-idp:AdminRemoveUserFromGroup",
      ]
      Resource = "arn:aws:cognito-idp:${var.region}:${data.aws_caller_identity.current.account_id}:userpool/${var.cognito_user_pool_id}"
    }]
  })
}

# Bedrock: invoke only the configured models, only through their US inference profiles. A cross-region
# profile forwards the call to the foundation model in another US region, so that ARN uses region "*", and the
# condition allows it only when the call came through one of our profiles.
resource "aws_iam_role_policy" "task_bedrock" {
  name = "invoke-claude"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InferenceProfiles"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = local.profile_arns
      },
      {
        Sid       = "FoundationModelsViaProfiles"
        Effect    = "Allow"
        Action    = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource  = local.foundation_model_arns
        Condition = { StringLike = { "bedrock:InferenceProfileArn" = local.profile_arns } }
      },
    ]
  })
}

# Documents: read and write files under documents/ in the one bucket. No delete (deleting a document hides it),
# no listing, no other bucket.
resource "aws_iam_role_policy" "task_documents" {
  name = "document-files"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:GetObject"]
      Resource = "${aws_s3_bucket.documents.arn}/documents/*"
    }]
  })
}

# --- Service ---------------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "app" {
  name              = "/advisoragent/app"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "main" {
  name = "advisoragent"
}

resource "aws_ecs_express_gateway_service" "app" {
  service_name            = "advisoragent"
  cluster                 = aws_ecs_cluster.main.name
  execution_role_arn      = aws_iam_role.execution.arn
  infrastructure_role_arn = aws_iam_role.infrastructure.arn
  task_role_arn           = aws_iam_role.task.arn
  health_check_path       = "/api/health"
  cpu                     = "512"
  memory                  = "1024"
  wait_for_steady_state   = true

  primary_container {
    image          = "${data.aws_ecr_repository.app.repository_url}:${var.image_tag}"
    container_port = 8000

    aws_logs_configuration {
      log_group         = aws_cloudwatch_log_group.app.name
      log_stream_prefix = "app" # required by the ECS API, although the provider marks it optional
    }

    environment {
      name  = "AUTH_MODE"
      value = "cognito"
    }
    environment {
      name  = "COGNITO_REGION"
      value = var.region
    }
    environment {
      name  = "COGNITO_USER_POOL_ID"
      value = var.cognito_user_pool_id
    }
    environment {
      name  = "COGNITO_CLIENT_ID"
      value = var.cognito_client_id
    }
    environment {
      name  = "COGNITO_DOMAIN"
      value = var.cognito_domain
    }
    environment {
      name  = "DOCUMENTS_BUCKET"
      value = aws_s3_bucket.documents.bucket
    }
    environment {
      name  = "LLM_PROVIDER"
      value = "bedrock"
    }
    environment {
      name  = "BEDROCK_REGION"
      value = var.region
    }
    environment {
      name  = "ANTHROPIC_MODEL"
      value = var.anthropic_model
    }
    environment {
      name  = "GUARD_MODEL"
      value = var.guard_model
    }
    environment {
      name  = "DB_HOST"
      value = aws_db_instance.db.address
    }
    environment {
      name  = "DB_USER"
      value = aws_db_instance.db.username
    }
    environment {
      name  = "DB_NAME"
      value = aws_db_instance.db.db_name
    }

    secret {
      name       = "DB_PASSWORD"
      value_from = "${aws_db_instance.db.master_user_secret[0].secret_arn}:password::"
    }
    secret {
      name       = "DEMO_PASSWORD"
      value_from = data.aws_secretsmanager_secret.demo_password.arn
    }
  }

  scaling_target {
    min_task_count = 1
    max_task_count = 1
    # AWS fills these defaults in; leaving them unset makes provider 6.73 fail with "inconsistent result after apply".
    auto_scaling_metric       = "AVERAGE_CPU"
    auto_scaling_target_value = 60
  }

  # Avoid a stuck delete: roles must outlive the service.
  depends_on = [
    aws_iam_role_policy_attachment.infrastructure,
    aws_iam_role_policy_attachment.execution_base,
    aws_iam_role_policy.execution_secrets,
    aws_iam_role_policy.task_bedrock,
    aws_iam_role_policy.task_documents,
  ]
}

output "COGNITO_USER_POOL_ID" {
  value = var.cognito_user_pool_id
}

output "COGNITO_CLIENT_ID" {
  value = var.cognito_client_id
}

output "APP_URL" {
  description = "Open this. Then add it to infra/persistent app_urls so Cognito sign-in can return here."
  value       = try(aws_ecs_express_gateway_service.app.ingress_paths[0].endpoint, null) # already includes https://
}

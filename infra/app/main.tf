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

data "aws_secretsmanager_secret" "anthropic_api_key" {
  name = "advisoragent/anthropic-api-key"
}

data "aws_secretsmanager_secret" "demo_password" {
  name = "advisoragent/demo-password"
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

# Execution role: pull the image, write logs, read the three secrets at container start.
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
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        data.aws_secretsmanager_secret.anthropic_api_key.arn,
        data.aws_secretsmanager_secret.demo_password.arn,
        aws_db_instance.db.master_user_secret[0].secret_arn,
      ]
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

# Task role: what the running app may call. Only Cognito user administration (admin portal, demo logins).
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
      name  = "ANTHROPIC_MODEL"
      value = var.anthropic_model
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
      name       = "ANTHROPIC_API_KEY"
      value_from = data.aws_secretsmanager_secret.anthropic_api_key.arn
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
  ]
}

output "APP_URL" {
  description = "Open this. Then add it to infra/persistent app_urls so Cognito sign-in can return here."
  value       = try(aws_ecs_express_gateway_service.app.ingress_paths[0].endpoint, null) # already includes https://
}

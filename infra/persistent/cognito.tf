# Sign-in for both portals and the admin portal. Kept across demo teardowns ("persistent" stack).
#
# - Usernames match the database usernames (advisors.username / clients.username); the group decides
#   which table the backend looks in. No custom attributes or Lambda triggers.
# - Only administrators create users (no self sign-up). Passwords never touch this app: users sign in on
#   Cognito's hosted page and the app receives tokens (authorization code flow with PKCE).

data "aws_caller_identity" "current" {}

resource "aws_cognito_user_pool" "main" {
  name           = "advisoragent"
  user_pool_tier = "LITE" # hosted sign-in page, groups, admin-created users; free under 10,000 monthly users

  username_configuration {
    case_sensitive = false
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true
    string_attribute_constraints {
      min_length = 3
      max_length = 254
    }
  }

  deletion_protection = "INACTIVE" # set ACTIVE once real users exist
}

resource "aws_cognito_user_group" "groups" {
  for_each     = toset(["advisors", "clients", "admins"])
  name         = each.key
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "AdvisorAgent ${each.key}"
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "advisoragent-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false # browser app: public client, PKCE instead of a secret
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = [for u in var.app_urls : "${u}/auth/callback"]
  logout_urls                          = [for u in var.app_urls : "${u}/login"]
  explicit_auth_flows                  = ["ALLOW_REFRESH_TOKEN_AUTH", "ALLOW_USER_SRP_AUTH"]

  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 12
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "hours"
  }

  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
}

resource "aws_cognito_user_pool_domain" "hosted" {
  domain                = "advisoragent-${data.aws_caller_identity.current.account_id}"
  user_pool_id          = aws_cognito_user_pool.main.id
  managed_login_version = 1 # classic hosted sign-in page (works on the Lite tier)
}

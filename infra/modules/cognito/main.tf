# Cognito user pool + the single app client the backend uses, and the IAM policy for the AWS calls
# the backend makes (cognito-idp admin calls, SES sending). API-only: sign-up and sign-in are
# proxied through the backend's cognito-idp admin calls (backend/app/core/cognito.py), so there is
# no Hosted UI, no OAuth, no self-service sign-up and no MFA.

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_cognito_user_pool" "this" {
  name = "${local.name_prefix}-users"

  # Email is the username; the backend passes Username=email on every admin call.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  username_configuration {
    case_sensitive = false
  }

  # Only AdminCreateUser (the backend) can create users, so the public client id alone cannot
  # self-register an account and skip the backend's local user row.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  # The backend's password_auth rejects every challenge, so nothing here may trigger one:
  # no MFA, no device tracking, no Lambda triggers.
  mfa_configuration = "OFF"

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  password_policy {
    minimum_length                   = var.password_min_length
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = var.password_require_symbols
    temporary_password_validity_days = 7
  }

  # Cognito's own sender (50 mails/day) stays unused: the backend suppresses the invite mail and
  # sends password-reset mail itself through SES (backend/app/core/mail.py), never through
  # Cognito's recovery flow.
  email_configuration {
    email_sending_account = "COGNITO_DEFAULT"
  }

  # Standard attributes the backend writes. Declared up front: changing or removing a schema entry
  # later forces replacement of the whole pool (and every user in it). The constraints blocks are
  # required on String attributes or the provider recreates the pool.
  schema {
    name                     = "email"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = true
    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  schema {
    name                     = "name"
    attribute_data_type      = "String"
    developer_only_attribute = false
    mutable                  = true
    required                 = false
    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }

  user_pool_tier      = var.user_pool_tier
  deletion_protection = var.deletion_protection

  tags = merge(var.tags, { Name = "${local.name_prefix}-users" })
}

# Public client (no secret): the backend computes no SECRET_HASH, and REFRESH_TOKEN_AUTH could not
# carry one anyway. Only the two flows the backend calls are enabled.
resource "aws_cognito_user_pool_client" "backend" {
  name         = "${local.name_prefix}-backend"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret     = false
  explicit_auth_flows = ["ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]

  # Unknown user on sign-in → NotAuthorizedException, same as a wrong password (no enumeration).
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true
  supported_identity_providers  = ["COGNITO"]

  access_token_validity  = var.access_token_validity_hours
  id_token_validity      = var.id_token_validity_hours
  refresh_token_validity = var.refresh_token_validity_days
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

# The identity the backend sends mail from was verified outside Terraform; look it up so the
# policy is scoped to its ARN.
data "aws_sesv2_email_identity" "backend" {
  count          = var.ses_identity == null ? 0 : 1
  email_identity = var.ses_identity
}

# The exact AWS calls the backend makes: cognito-idp admin calls scoped to this pool, and SES
# sending from the verified identity. Attach it to whatever identity runs the backend (task role,
# Lambda role, IAM user). GlobalSignOut is authorized by the user's own access token and needs no
# IAM permission; AdminUserGlobalSignOut (password reset) does.
resource "aws_iam_policy" "backend" {
  count = var.create_backend_policy ? 1 : 0

  name        = "${local.name_prefix}-cognito-backend"
  description = "AWS calls the ${var.project_name} backend makes: cognito-idp admin calls on the ${var.environment} user pool, SES sending"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Sid    = "CognitoBackendAdminCalls"
          Effect = "Allow"
          Action = [
            "cognito-idp:AdminCreateUser",
            "cognito-idp:AdminSetUserPassword",
            "cognito-idp:AdminDeleteUser",
            "cognito-idp:AdminInitiateAuth",
            "cognito-idp:AdminUserGlobalSignOut",
          ]
          Resource = aws_cognito_user_pool.this.arn
        },
      ],
      [
        for identity in data.aws_sesv2_email_identity.backend : {
          Sid      = "SesPasswordResetMail"
          Effect   = "Allow"
          Action   = ["ses:SendEmail"]
          Resource = identity.arn
        }
      ],
    )
  })

  tags = var.tags
}

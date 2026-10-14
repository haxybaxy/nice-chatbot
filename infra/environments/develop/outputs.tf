output "cognito_user_pool_id" {
  description = "User pool id (COGNITO_USER_POOL_ID)"
  value       = module.cognito.user_pool_id
}

output "cognito_user_pool_arn" {
  description = "User pool ARN"
  value       = module.cognito.user_pool_arn
}

output "cognito_issuer_url" {
  description = "Expected `iss` claim of the pool's tokens"
  value       = module.cognito.issuer_url
}

output "cognito_jwks_url" {
  description = "Token signing keys the backend verifies against"
  value       = module.cognito.jwks_url
}

output "cognito_app_client_id" {
  description = "Backend app client id (COGNITO_CLIENT_ID)"
  value       = module.cognito.app_client_id
}

output "cognito_backend_policy_arn" {
  description = "IAM policy to attach to the identity that runs the backend"
  value       = module.cognito.backend_policy_arn
}

output "backend_env" {
  description = "Lines to paste into backend/.env (`just backend-env`)"
  value       = <<-EOT
    AWS_REGION=${var.aws_region}
    COGNITO_USER_POOL_ID=${module.cognito.user_pool_id}
    COGNITO_CLIENT_ID=${module.cognito.app_client_id}
  EOT
}

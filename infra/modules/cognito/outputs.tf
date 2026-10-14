output "user_pool_id" {
  description = "User pool id (COGNITO_USER_POOL_ID)"
  value       = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  description = "User pool ARN (scope IAM policies to it)"
  value       = aws_cognito_user_pool.this.arn
}

output "user_pool_endpoint" {
  description = "cognito-idp.<region>.amazonaws.com/<pool id>, without scheme"
  value       = aws_cognito_user_pool.this.endpoint
}

output "issuer_url" {
  description = "Expected `iss` claim of tokens from this pool"
  value       = "https://${aws_cognito_user_pool.this.endpoint}"
}

output "jwks_url" {
  description = "Signing keys the backend verifies access tokens against"
  value       = "https://${aws_cognito_user_pool.this.endpoint}/.well-known/jwks.json"
}

output "app_client_id" {
  description = "Backend app client id (COGNITO_CLIENT_ID)"
  value       = aws_cognito_user_pool_client.backend.id
}

output "backend_policy_arn" {
  description = "IAM managed policy granting the backend's cognito-idp calls on this pool (null when not created)"
  value       = var.create_backend_policy ? aws_iam_policy.backend[0].arn : null
}

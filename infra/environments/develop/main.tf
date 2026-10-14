# develop — the Cognito user pool the backend's auth flows are tested against. Cognito only for
# now: the API and Postgres run locally (backend/docker-compose.yml).

module "cognito" {
  source = "../../modules/cognito"

  project_name = var.project_name
  environment  = var.environment
  tags         = var.tags

  # A throwaway pool: `just destroy` must work.
  deletion_protection = "INACTIVE"

  # The backend's password-reset mail leaves from this identity (verified outside Terraform).
  ses_identity = var.ses_identity
}

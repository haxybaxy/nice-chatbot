# Acme Infrastructure

OpenTofu for Acme's AWS resources. Today that is one thing: the **Cognito user pool** the backend
authenticates against, one pool per environment. Only `develop` exists so far, in **us-west-1**.
Conventions for contributors are in `CLAUDE.md`; this file is the quick start.

## Prerequisites

- [OpenTofu](https://opentofu.org) ≥ 1.12 (`brew install opentofu`), `just`, AWS CLI v2.
- AWS credentials for the Acme account in your environment: the `default` profile, or export
  `AWS_PROFILE`. With an `aws login` session profile, `just login <profile>` re-authenticates it
  when it expires.

## Quick start

```bash
just bootstrap      # once per account: S3 state bucket acme-tfstate-<account id> in us-west-1; paste the
                    # printed bucket name into environments/develop/versions.tf (it ships with a placeholder)
just init           # providers + S3 backend for environments/develop
just plan           # first run: user pool, app client, backend IAM policy
just apply
just backend-env    # → paste into backend/.env
```

Then in `backend/`: `just dev` and exercise `POST /api/auth/signup`,
`/signin`, `/refresh` and `/signout` from Swagger UI at `http://localhost:8000/docs`
(see `backend/README.md` → Authentication).

Every recipe takes the environment as an optional argument (`just plan develop`); `just` alone
lists them all.

## Layout

```
.
├── bootstrap.sh              one-time state bucket setup (idempotent)
├── justfile                  login · bootstrap · init · plan · apply · destroy · output · backend-env · fmt · validate · check
├── environments/
│   └── develop/              one root module = one state: versions.tf (tofu + provider pins, S3 backend),
│                             providers.tf, main.tf, variables.tf, outputs.tf, terraform.tfvars
└── modules/
    └── cognito/              user pool + app client + IAM policy for the backend
```

## What the Cognito module builds

Shaped by `backend/app/core/cognito.py`, which proxies every auth call through the cognito-idp
admin API:

- **User pool** `acme-<env>-users`: email is the username; only `AdminCreateUser` can create
  users (no self-service sign-up, so the public client id alone cannot bypass the backend); MFA
  off; no device tracking, Lambda triggers or add-ons (the backend rejects every auth challenge);
  passwords ≥ 8 characters with a lowercase, an uppercase and a digit; standard `email` and `name`
  attributes declared up front (changing a schema entry later replaces the pool); `ESSENTIALS`
  tier; `deletion_protection` INACTIVE on develop.
- **App client** `acme-<env>-backend`: public (no secret), `ALLOW_ADMIN_USER_PASSWORD_AUTH` +
  `ALLOW_REFRESH_TOKEN_AUTH` only, access/id tokens 1 h, refresh tokens 30 days, user-existence
  errors hidden.
- **IAM managed policy** `acme-<env>-cognito-backend`: `AdminCreateUser`, `AdminSetUserPassword`,
  `AdminDeleteUser`, `AdminInitiateAuth`, `AdminUserGlobalSignOut` on that pool only, plus
  `ses:SendEmail` on the verified SES identity named by `ses_identity` (password-reset mail). Attached to nothing yet: attach it to
  the role that runs the backend once it is deployed. Locally the backend uses your own profile.

Outputs: `cognito_user_pool_id`, `cognito_app_client_id`, `cognito_issuer_url`, `cognito_jwks_url`,
`cognito_user_pool_arn`, `cognito_backend_policy_arn` and `backend_env`.

## State

S3 backend, bucket `acme-tfstate-<account id>` (us-west-1, versioned, SSE-S3, public access
blocked), one key per environment (`develop/terraform.tfstate`), locking via the S3-native lockfile
(`use_lockfile = true`, no DynamoDB). `bootstrap.sh` creates the bucket and prints the backend
block; paste the bucket name into `environments/<env>/versions.tf`, which ships with the placeholder
account id `123456789012`, because backend blocks cannot read variables.

## Adding an environment

1. Copy `environments/develop/` to `environments/<env>/`; change `key` in the backend block, the
   defaults in `variables.tf` and `terraform.tfvars`; set `deletion_protection = "ACTIVE"` for
   anything that will hold real users.
2. `just init <env> && just plan <env> && just apply <env>`.

## Not here yet

No CI (plan on PR, apply on merge) and no GitHub OIDC deploy role: applies are manual with a
developer's own credentials. Add both alongside the first deployed backend.

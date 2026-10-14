# CLAUDE.md — infra

Guidance for working in `infra/`. `README.md` has the quick start; this file has the rules.

## Commands (run from `infra/`)

```bash
just login [profile]                    # only for an aws-login session profile; static keys in `default` need nothing
just bootstrap                          # one-time S3 state bucket
just init | plan | apply | destroy      # develop by default; pass an env name for another
just backend-env                        # .env lines for the backend
just check                              # fmt-check + offline validate — run before every commit
```

OpenTofu ≥ 1.12 (`tofu`), AWS provider `~> 6.25`, region us-west-1. `.tf` files use standard
`terraform {}` blocks (Terraform-CLI compatible); docs and recipes say `tofu`.

## Layout

- `modules/<name>/` — reusable resources: `versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`.
  Modules take `project_name` + `environment` and name resources `${project_name}-${environment}-…`.
- `environments/<env>/` — one root module = one state: `versions.tf` (tofu/provider pins + the S3
  backend block), `providers.tf` (region + `default_tags`), `main.tf` (module calls only),
  `variables.tf`, `outputs.tf`, `terraform.tfvars` (committed; never secrets).

## Rules

- **The backend code is the spec for the Cognito pool.** `backend/app/core/cognito.py` and
  `security.py` decide which auth flows, attributes and IAM calls are needed; change them together.
  Nothing in the pool may produce an auth challenge (MFA, device tracking, Lambda triggers,
  add-ons): the backend rejects every challenge.
- **Schema blocks are append-only.** Editing or removing a `schema` entry on an existing pool
  forces replacement of the pool and loses every user.
- `Project`, `Environment` and `ManagedBy` tags come from the provider's `default_tags`; modules add
  only `Name` and `var.tags`.
- Credentials come from the process environment (the `default` profile or `AWS_PROFILE`), never
  from `profile =` in HCL, so the same config works under CI OIDC later.
- State is remote from day one (S3 + native lockfile). Never commit `*.tfstate`; do commit
  `.terraform.lock.hcl`.
- `deletion_protection = "INACTIVE"` only for throwaway environments; anything holding real users
  is `ACTIVE`.
- `just check` before every commit; the root pre-commit config runs `tofu fmt -check` on `infra/**.tf`.

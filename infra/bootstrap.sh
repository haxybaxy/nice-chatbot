#!/usr/bin/env bash
# One-time AWS setup for OpenTofu state: an S3 bucket (versioned, encrypted, private) in us-west-1
# that every environments/<env>/versions.tf backend block points at. Idempotent — re-running it is
# safe. Locking uses the S3 backend's native lockfile (use_lockfile = true); no DynamoDB table.
#
#   just bootstrap            (or: AWS_PROFILE=acme ./bootstrap.sh)
set -euo pipefail

PROJECT_NAME="acme"
AWS_REGION="us-west-1"

if ! ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2> /dev/null); then
    echo "error: AWS CLI is not authenticated (try: aws login --profile ${AWS_PROFILE:-acme})" >&2
    exit 1
fi

STATE_BUCKET="${PROJECT_NAME}-tfstate-${ACCOUNT_ID}"
echo "account ${ACCOUNT_ID} · region ${AWS_REGION} · bucket ${STATE_BUCKET}"

if aws s3api head-bucket --bucket "$STATE_BUCKET" 2> /dev/null; then
    echo "bucket already exists"
else
    # Every region except us-east-1 needs an explicit LocationConstraint.
    aws s3api create-bucket \
        --bucket "$STATE_BUCKET" \
        --region "$AWS_REGION" \
        --create-bucket-configuration "LocationConstraint=${AWS_REGION}"
    echo "bucket created"
fi

aws s3api put-bucket-versioning \
    --bucket "$STATE_BUCKET" \
    --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption \
    --bucket "$STATE_BUCKET" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-public-access-block \
    --bucket "$STATE_BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
echo "versioning, encryption and public-access block enabled"

cat << EOF

State bucket ready. Each environments/<env>/versions.tf must point at it:

  backend "s3" {
    bucket       = "${STATE_BUCKET}"
    key          = "<env>/terraform.tfstate"
    region       = "${AWS_REGION}"
    encrypt      = true
    use_lockfile = true
  }

Next: just init && just plan && just apply
EOF

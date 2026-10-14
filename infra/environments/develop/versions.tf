terraform {
  # 1.12: the S3 backend resolves `aws login` session profiles.
  required_version = ">= 1.12"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.25"
    }
  }

  # State bucket created once by ../../bootstrap.sh. Backend blocks cannot use variables, so the
  # account id is spelled out: replace the placeholder 123456789012 with yours (bootstrap.sh prints
  # the exact block). Locking is the S3-native lockfile (no DynamoDB).
  backend "s3" {
    bucket       = "acme-tfstate-123456789012"
    key          = "develop/terraform.tfstate"
    region       = "us-west-1"
    encrypt      = true
    use_lockfile = true
  }
}

terraform {
  # 1.12: the S3 backend resolves `aws login` session profiles.
  required_version = ">= 1.12"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # 6.25: the provider resolves `aws login` session profiles.
      version = "~> 6.25"
    }
  }
}

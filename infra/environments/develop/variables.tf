variable "aws_region" {
  description = "Region the user pool lives in; the backend's AWS_REGION must match"
  type        = string
  default     = "us-west-1"
}

variable "project_name" {
  description = "Project name used as the resource-name prefix"
  type        = string
  default     = "acme"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "develop"
}

variable "tags" {
  description = "Extra tags for every resource"
  type        = map(string)
  default     = {}
}

variable "ses_identity" {
  description = "Verified SES identity the backend sends mail from (a domain or address already verified in aws_region)"
  type        = string
  default     = "example.com"
}

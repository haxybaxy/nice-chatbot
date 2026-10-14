variable "project_name" {
  description = "Project name used as the resource-name prefix"
  type        = string
}

variable "environment" {
  description = "Environment name (develop, staging, production)"
  type        = string
}

variable "deletion_protection" {
  description = "ACTIVE blocks deleting the pool (production); INACTIVE lets `tofu destroy` remove it"
  type        = string
  default     = "INACTIVE"
  validation {
    condition     = contains(["ACTIVE", "INACTIVE"], var.deletion_protection)
    error_message = "deletion_protection must be ACTIVE or INACTIVE."
  }
}

variable "user_pool_tier" {
  description = "Cognito feature plan. ESSENTIALS is AWS's default for new pools; LITE is the legacy feature set; PLUS adds threat protection"
  type        = string
  default     = "ESSENTIALS"
  validation {
    condition     = contains(["LITE", "ESSENTIALS", "PLUS"], var.user_pool_tier)
    error_message = "user_pool_tier must be LITE, ESSENTIALS or PLUS."
  }
}

variable "password_min_length" {
  description = "Minimum password length (a lowercase, an uppercase and a digit are always required)"
  type        = number
  default     = 8
}

variable "password_require_symbols" {
  description = "Require at least one symbol in passwords"
  type        = bool
  default     = false
}

variable "access_token_validity_hours" {
  description = "Access token lifetime in hours (1-24)"
  type        = number
  default     = 1
}

variable "id_token_validity_hours" {
  description = "ID token lifetime in hours (1-24)"
  type        = number
  default     = 1
}

variable "refresh_token_validity_days" {
  description = "Refresh token lifetime in days"
  type        = number
  default     = 30
}

variable "create_backend_policy" {
  description = "Create the IAM managed policy that grants the backend its cognito-idp admin calls on this pool"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Extra tags. Project, Environment and ManagedBy come from the provider's default_tags"
  type        = map(string)
  default     = {}
}

variable "ses_identity" {
  description = "Verified SES identity (domain or address, in the provider region) the backend sends mail from; null grants no SES permission"
  type        = string
  default     = null
}

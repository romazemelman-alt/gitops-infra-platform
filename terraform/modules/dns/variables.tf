variable "environment" {
  type        = string
  description = "environment (dev, staging, prod)"
}

variable "domain_name" {
  type        = string
  description = "Domain name for cluster. E.g. staging.dev"
}

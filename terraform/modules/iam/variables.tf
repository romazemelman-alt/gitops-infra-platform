variable "cluster_name" {
  type        = string
  description = "The name of the EKS cluster"
}

variable "environment" {
  type        = string
  description = "Deployment environment name"
}

variable "aws_managed_policies" {
  type        = list(string)
  description = "List of standard AWS-managed policy ARNs for the EKS Node Group"
  default     = []
}

variable "custom_policies" {
  type        = list(string)
  description = "List of customer-managed (custom) policy ARNs for specific project needs"
  default     = []
}


variable "cluster_oidc_issuer_url" {
  type        = string
  description = "cluster oidc issuer URL"
}

variable "oidc_provider_arn" {
  type        = string
  description = "cluster oidc provider arn"
}

variable "hosted_zone_id" {
  type        = string
  description = "ID zone Route53 to restrict access"
}
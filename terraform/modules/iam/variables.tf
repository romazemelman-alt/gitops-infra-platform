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
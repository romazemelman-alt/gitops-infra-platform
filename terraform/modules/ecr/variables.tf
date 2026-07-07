variable "repository_name" {
  type        = string
  description = "The name of the ECR repository"
}

variable "environment" {
  type        = string
  description = "Environment name (dev, stage, prod)"
}

variable "max_image_count" {
  type        = number
  default     = 20
  description = "How many images to keep before recycling"
}
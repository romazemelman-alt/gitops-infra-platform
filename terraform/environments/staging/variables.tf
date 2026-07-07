variable "aws_region" { type = string }
variable "environment" { type = string }
variable "vpc_cidr" { type = string }
variable "cluster_name" { type = string }
variable "node_min_size" { type = number }
variable "node_max_size" { type = number }
variable "node_desired_size" { type = number }
variable "instance_types" { type = list(string) }
variable "capacity_type" { type = string }
variable "aws_managed_policies" {
  type    = list(string)
  default = []
}

variable "custom_policies" {
  type    = list(string)
  default = []
}

variable "max_image_count" { type = number }
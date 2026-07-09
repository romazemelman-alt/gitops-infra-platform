output "node_group_role_arn" {
  value       = aws_iam_role.node_group.arn
  description = "The ARN of the IAM role for the EKS node group"
}

output "lb_controller_role_arn" {
  value = aws_iam_role.lb_controller.arn
}

output "external_dns_role_arn" {
  value       = aws_iam_role.external_dns.arn
  description = "ARN for annotation in ServiceAccount in Kubernetes"
}
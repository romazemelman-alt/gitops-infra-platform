output "node_group_role_arn" {
  value       = aws_iam_role.node_group.arn
  description = "The ARN of the IAM role for the EKS node group"
}
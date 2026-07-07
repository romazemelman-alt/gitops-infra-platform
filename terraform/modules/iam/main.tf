resource "aws_iam_role" "node_group" {
  name = "${var.cluster_name}-node-group-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
  }
}


resource "aws_iam_role_policy_attachment" "node_policies" {
  count      = length(concat(var.aws_managed_policies, var.custom_policies))


  policy_arn = concat(var.aws_managed_policies, var.custom_policies)[count.index]
  role       = aws_iam_role.node_group.name
}
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "${var.environment}-${var.cluster_name}"
  cluster_version = var.cluster_version

  cluster_endpoint_public_access = true

  vpc_id     = var.vpc_id
  subnet_ids = var.private_subnet_ids

  enable_cluster_creator_admin_permissions = true

  #  Managed Node Groups Autoscaler
  eks_managed_node_groups = {
    default = {

      create_iam_role = false

      iam_role_arn    = var.node_group_role_arn

      min_size     = var.node_min_size
      max_size     = var.node_max_size
      desired_size = var.node_desired_size

      instance_types = var.instance_types
      capacity_type  = var.capacity_type

      tags = {
        "k8s.io/cluster-autoscaler/enabled" : "true"
        "k8s.io/cluster-autoscaler/${var.environment}-${var.cluster_name}" : "owned"
      }
    }
  }

  tags = {
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}
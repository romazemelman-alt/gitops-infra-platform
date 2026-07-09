provider "aws" {
  region = var.aws_region
}


module "ecr_app" {
  source          = "../../modules/ecr"
  repository_name = "${var.environment}-k8s-node-app"
  environment     = var.environment
  max_image_count = var.max_image_count
}

resource "aws_iam_policy" "secrets_manager" {
  name        = "${var.environment}-${var.cluster_name}-secrets-policy"
  description = "Dynamic policy for EKS nodes to access Secrets Manager in ${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:*:secret:${var.environment}/${var.cluster_name}/*"
      }
    ]
  })
}

module "dns" {
  source      = "../../modules/dns"
  domain_name = var.domain_name
  environment = var.environment
}

module "iam" {
  source               = "../../modules/iam"
  cluster_name         = var.cluster_name
  environment          = var.environment
  aws_managed_policies = var.aws_managed_policies
  custom_policies      = concat(var.custom_policies, [aws_iam_policy.secrets_manager.arn])
  oidc_provider_arn = module.eks.oidc_provider_arn
  cluster_oidc_issuer_url = module.eks.cluster_oidc_issuer_url
  hosted_zone_id          = module.dns.zone_id

}

module "network" {
  source = "../../modules/network"

  environment = var.environment
  vpc_cidr    = var.vpc_cidr
}

module "eks" {
  source = "../../modules/eks"

  environment        = var.environment
  cluster_name       = var.cluster_name
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnets
  node_group_role_arn = module.iam.node_group_role_arn
  node_min_size     = var.node_min_size
  node_max_size     = var.node_max_size
  node_desired_size = var.node_desired_size
  instance_types    = var.instance_types
  capacity_type     = var.capacity_type

}
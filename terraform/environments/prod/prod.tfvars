aws_region   = "eu-central-1"
environment  = "prod"
vpc_cidr     = "10.20.0.0/16"
cluster_name = "teraSky-prod"

# Production Scaling & Provisioning Settings
node_min_size     = 3
node_max_size     = 10
node_desired_size = 3
instance_types    = ["m5.large"]
capacity_type     = "ON_DEMAND"

node_policies = [
  "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
  "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
  "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
]

custom_policies = []

max_image_count = 50
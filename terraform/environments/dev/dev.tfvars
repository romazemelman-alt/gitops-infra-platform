aws_region  = "eu-central-1"
environment = "dev"
vpc_cidr    = "10.0.0.0/16"
cluster_name = "teraSky-gitops"


node_min_size     = 1
node_max_size     = 3
node_desired_size = 1
instance_types    = ["t3.medium"]
capacity_type     = "SPOT"

aws_managed_policies = [
  "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
  "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
  "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
]

custom_policies = []

max_image_count = 20

domain_name = "dev.terasky.com"
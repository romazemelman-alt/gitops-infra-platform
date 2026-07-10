aws_region   = "eu-central-1"
environment  = "staging"
vpc_cidr     = "10.10.0.0/16"
cluster_name = "teraSky-staging"

# staging Scaling Settings
node_min_size     = 2
node_max_size     = 5
node_desired_size = 2
instance_types    = ["t3.medium"]
capacity_type     = "SPOT"

aws_managed_policies = [
  "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
  "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
  "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
]

custom_policies = []

max_image_count = 20

domain_name = "stage.terasky.com"

github_token    = ""
github_owner    = ""
repository_name = ""
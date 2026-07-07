terraform {
  backend "s3" {
    bucket         = "roman-terasky-tf-state-dev"
    key            = "eks/dev/terraform.tfstate"
    region         = "eu-central-1"

    dynamodb_table = "roman-terasky-tf-locks-dev"

    encrypt        = true
  }
}
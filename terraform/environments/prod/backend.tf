terraform {
  backend "s3" {
    bucket         = "roman-terasky-tf-state-prod"
    key            = "eks/prod/terraform.tfstate"
    region         = "eu-central-1"

    dynamodb_table = "roman-terasky-tf-locks-prod"

    encrypt        = true
  }
}
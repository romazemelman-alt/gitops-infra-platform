terraform {
  backend "s3" {
    bucket         = "roman-terasky-tf-state-staging"
    key            = "eks/staging/terraform.tfstate"
    region         = "eu-central-1"

    dynamodb_table = "roman-terasky-tf-locks-staging"

    encrypt        = true
  }
}
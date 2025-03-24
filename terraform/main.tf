terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
  
  # Uncomment this block to configure remote state
  # backend "s3" {
  #   bucket         = "sensing-garden-terraform-state"
  #   key            = "sensing-garden-web/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "sensing-garden-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}

# No longer need the ECR module since we're using source-based deployment

module "apprunner" {
  source = "./modules/apprunner"
  
  app_name                 = var.app_name
  repository_url           = var.repository_url
  source_code_branch       = var.source_code_branch
  port                     = var.port
  sensing_garden_api_key   = var.sensing_garden_api_key
  api_base_url             = var.api_base_url
  tags                     = var.tags
  instance_configuration   = var.instance_configuration
  auto_deployments_enabled = var.auto_deployments_enabled
}

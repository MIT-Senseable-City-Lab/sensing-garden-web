terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.0"
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

module "ecr" {
  source = "./modules/ecr"
  
  repository_name = var.ecr_repository_name
  tags            = var.tags
}

module "apprunner" {
  source = "./modules/apprunner"
  
  app_name                 = var.app_name
  ecr_repository_url       = module.ecr.repository_url
  image_tag                = var.image_tag
  port                     = var.port
  sensing_garden_api_key   = var.sensing_garden_api_key
  api_base_url             = var.api_base_url
  tags                     = var.tags
  instance_configuration   = var.instance_configuration
  auto_deployments_enabled = var.auto_deployments_enabled
}

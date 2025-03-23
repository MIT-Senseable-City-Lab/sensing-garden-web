#!/bin/bash
# Script to create terraform.tfvars from .env without exposing secrets

# Set script to exit on error
set -e

# Check if .env file exists
if [ ! -f "../.env" ]; then
    echo "Error: .env file not found in parent directory"
    exit 1
fi

# Create terraform.tfvars with standard configurations
cat > terraform.tfvars << EOF
aws_region = "us-east-1"
app_name = "sensing-garden-web"
ecr_repository_name = "sensing-garden-web"
image_tag = "latest"
port = 5052
tags = {
  Environment = "production"
  Project     = "sensing-garden"
  ManagedBy   = "terraform"
}
instance_configuration = {
  cpu    = "1 vCPU"
  memory = "2 GB"
}
auto_deployments_enabled = true
EOF

# Extract API key and base URL from .env and append to terraform.tfvars
# This approach doesn't echo the values or expose them in process list
API_KEY=$(grep SENSING_GARDEN_API_KEY ../.env | cut -d'=' -f2)
API_BASE_URL=$(grep API_BASE_URL ../.env | cut -d'=' -f2)

# Append to terraform.tfvars without revealing values
echo "sensing_garden_api_key = \"$API_KEY\"" >> terraform.tfvars
echo "api_base_url = \"$API_BASE_URL\"" >> terraform.tfvars

echo "terraform.tfvars created successfully with values from .env"
echo "IMPORTANT: The terraform.tfvars file contains sensitive information and should never be committed to version control."

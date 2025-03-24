#!/bin/bash
# Script to set environment variables for Terraform from .env file

# Set script to exit on error
set -e

# Check if .env file exists
if [ ! -f "../.env" ]; then
    echo "Error: .env file not found in parent directory"
    exit 1
fi

# Source the .env file to set environment variables
source ../.env

# Export variables for Terraform
export TF_VAR_sensing_garden_api_key="$SENSING_GARDEN_API_KEY"
export TF_VAR_api_base_url="$API_BASE_URL"

echo "Environment variables set for Terraform"
echo "You can now run terraform commands"
echo "Note: This script must be run with 'source' command: source set_env.sh"

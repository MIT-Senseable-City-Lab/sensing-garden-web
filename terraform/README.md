# Sensing Garden Web - Terraform Configuration

This directory contains the Terraform configuration for deploying the Sensing Garden Web application to AWS App Runner.

## Environment Variables

The Terraform configuration uses environment variables with the `TF_VAR_` prefix for sensitive data. These are automatically set by the `set_env.sh` script, which sources your existing `.env` file and exports the variables with the required prefix.

## Deployment Instructions

1. Ensure you have the `.env` file in the project root directory with the following variables:
   ```
   SENSING_GARDEN_API_KEY=your_api_key
   API_BASE_URL=your_api_base_url
   ```

2. Set the environment variables for Terraform:
   ```bash
   source terraform/set_env.sh
   ```
   Note: You must use `source` to run this script, not `./set_env.sh`, so that the variables are exported to your current shell session.

3. Initialize Terraform:
   ```bash
   cd terraform
   terraform init
   ```

4. Apply the Terraform configuration:
   ```bash
   terraform apply
   ```

## AWS Resources

The Terraform configuration creates the following AWS resources:

- ECR Repository for storing Docker images
- AWS Secrets Manager secret for storing sensitive environment variables
- IAM roles and policies for App Runner
- App Runner service for running the application

## Auto-Deployments

The App Runner service is configured to automatically deploy new versions when a new Docker image is pushed to ECR. This eliminates the need to manually update the service or destroy and recreate it when deploying new versions.

## Health Checks

The App Runner service is configured with a health check endpoint at `/health`. The application provides a robust health check implementation that ensures the service is properly initialized before accepting traffic.

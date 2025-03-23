# Sensing Garden Web - AWS App Runner Deployment Guide

This guide explains how to deploy the Sensing Garden Web application to AWS App Runner using Terraform.

## Prerequisites

- [AWS CLI](https://aws.amazon.com/cli/) installed and configured with appropriate access
- [Terraform](https://www.terraform.io/downloads) (v1.0.0 or newer)
- [Docker](https://docs.docker.com/get-docker/) installed locally
- AWS Account with permissions to create:
  - ECR repositories
  - App Runner services
  - IAM roles and policies

## Deployment Steps

### 1. Configure AWS Credentials

Ensure your AWS credentials are configured either through:
- AWS CLI (`aws configure`)
- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`)
- A credentials file

### 2. Set up Terraform Variables

1. Copy the example variables file:
   ```bash
   cp terraform.tfvars.example terraform.tfvars
   ```

2. Edit `terraform.tfvars` with your specific values:
   - Replace `sensing_garden_api_key` with your actual API key
   - Update `api_base_url` with your API base URL
   - Adjust other variables as needed

### 3. Build and Push Docker Image to ECR

Before deploying with Terraform, you need to build and push your Docker image to ECR:

```bash
# Initialize Terraform to get ECR repository URL
cd terraform
terraform init
terraform apply -target=module.ecr -auto-approve

# Get the ECR repository URL
ECR_REPO=$(terraform output -raw ecr_repository_url)

# Authenticate Docker to ECR
aws ecr get-login-password --region $(aws configure get region) | docker login --username AWS --password-stdin $ECR_REPO

# Build and tag the Docker image
cd ..
docker build -t $ECR_REPO:latest .

# Push the image to ECR
docker push $ECR_REPO:latest
```

### 4. Deploy the App Runner Service

Once your Docker image is in ECR, deploy the App Runner service:

```bash
cd terraform
terraform apply
```

Review the planned changes and type `yes` to confirm the deployment.

### 5. Access Your Deployed Application

After deployment completes, you can access your application URL:

```bash
# Get the App Runner service URL
terraform output app_runner_service_url
```

## Managing Secrets

For production environments, consider these best practices for managing secrets:

1. **AWS Secrets Manager**: Store your `SENSING_GARDEN_API_KEY` in AWS Secrets Manager
2. **Environment Variables**: Pass secrets as environment variables in Terraform

Example using AWS Secrets Manager (requires additional configuration):

```hcl
# In your Terraform code, you would retrieve the secret
data "aws_secretsmanager_secret" "api_key" {
  name = "sensing-garden/api-key"
}

data "aws_secretsmanager_secret_version" "api_key" {
  secret_id = data.aws_secretsmanager_secret.api_key.id
}

# Then use it in App Runner configuration
sensing_garden_api_key = jsondecode(data.aws_secretsmanager_secret_version.api_key.secret_string)["key"]
```

## Updates and Maintenance

### Updating the Application

To deploy a new version:

1. Build and push a new Docker image to ECR
2. Either:
   - Wait for auto-deployment (if enabled)
   - Update the image tag in `terraform.tfvars` and run `terraform apply`

### Cleaning Up Resources

To remove all resources when no longer needed:

```bash
cd terraform
terraform destroy
```

## Troubleshooting

- **Deployment Failures**: Check the App Runner service logs in the AWS Console
- **Container Issues**: Review the container logs for application errors
- **IAM Permissions**: Ensure your IAM role has sufficient permissions

## Cost Considerations

AWS App Runner is billed based on:
- Compute resources allocated
- Idle time
- Transfer data

Review AWS pricing and consider setting up AWS Budget Alerts to monitor costs.

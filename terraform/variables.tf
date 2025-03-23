variable "aws_region" {
  description = "The AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Name of the sensing garden web application"
  type        = string
  default     = "sensing-garden-web"
}

variable "ecr_repository_name" {
  description = "Name of the ECR repository"
  type        = string
  default     = "sensing-garden-web"
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "port" {
  description = "Port the container exposes"
  type        = number
  default     = 5052
}

variable "sensing_garden_api_key" {
  description = "API key for the Sensing Garden API"
  type        = string
  sensitive   = true
}

variable "api_base_url" {
  description = "Base URL for the Sensing Garden API"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {
    Environment = "production"
    Project     = "sensing-garden"
    ManagedBy   = "terraform"
  }
}

variable "instance_configuration" {
  description = "Configuration for the App Runner service instances"
  type        = object({
    cpu    = string
    memory = string
  })
  default     = {
    cpu    = "1 vCPU"
    memory = "2 GB"
  }
}

variable "auto_deployments_enabled" {
  description = "Whether to enable auto deployments on the App Runner service"
  type        = bool
  default     = true
}

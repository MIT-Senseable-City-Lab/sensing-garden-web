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

variable "repository_url" {
  description = "URL of the Git repository to deploy from"
  type        = string
  default     = "https://github.com/daydemir/sensing-garden-web"
}

variable "source_code_branch" {
  description = "Branch of the Git repository to deploy"
  type        = string
  default     = "main"
}

variable "port" {
  description = "Port the container exposes"
  type        = number
  default     = 8080
}

# This variable is populated from the TF_VAR_sensing_garden_api_key environment variable
# which is set by the set_env.sh script from your SENSING_GARDEN_API_KEY in .env
variable "sensing_garden_api_key" {
  description = "API key for the Sensing Garden API"
  type        = string
  sensitive   = true
}

# This variable is populated from the TF_VAR_api_base_url environment variable
# which is set by the set_env.sh script from your API_BASE_URL in .env
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

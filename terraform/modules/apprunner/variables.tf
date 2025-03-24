variable "app_name" {
  description = "Name of the App Runner service"
  type        = string
}

variable "repository_url" {
  description = "URL of the Git repository to deploy from"
  type        = string
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
  description = "Tags to apply to the App Runner service"
  type        = map(string)
  default     = {}
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

resource "aws_iam_role" "app_runner_service_role" {
  name = "${var.app_name}-apprunner-service-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = ["build.apprunner.amazonaws.com", "tasks.apprunner.amazonaws.com"]
        }
      }
    ]
  })
  
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "app_runner_service_policy" {
  role       = aws_iam_role.app_runner_service_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# Generate a random suffix for the service name
resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

resource "aws_apprunner_service" "service" {
  service_name = "${var.app_name}-${random_string.suffix.result}"
  
  source_configuration {
    authentication_configuration {
      connection_arn = "arn:aws:apprunner:us-east-1:436312947046:connection/sensing-garden-github/12345678-1234-1234-1234-123456789012"
    }
    
    code_repository {
      code_configuration {
        configuration_source = "API"
        
        code_configuration_values {
          runtime = "PYTHON_3"
          build_command = "pip install poetry && poetry config virtualenvs.create false && poetry install --no-dev"
          start_command = "./start.sh"
          port = var.port
          runtime_environment_variables = {
            "FLASK_APP"               = "app.py"
            "FLASK_ENV"               = "production"
            "SENSING_GARDEN_API_KEY"  = var.sensing_garden_api_key
            "API_BASE_URL"            = var.api_base_url
            "PORT"                    = tostring(var.port)
          }
        }
      }
      
      repository_url = var.repository_url
      source_code_version {
        type  = "BRANCH"
        value = var.source_code_branch
      }
    }
    
    auto_deployments_enabled = var.auto_deployments_enabled
  }
  
  instance_configuration {
    cpu    = var.instance_configuration.cpu
    memory = var.instance_configuration.memory
  }
  
  health_check_configuration {
    path     = "/health"
    protocol = "HTTP"
    interval = 10
    timeout  = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }
  
  tags = var.tags
  
  depends_on = [aws_iam_role_policy_attachment.app_runner_service_policy]
  
  # Use lifecycle block to ignore changes to the image identifier
  # This allows auto-deployments to work without Terraform trying to update the service
  lifecycle {
    ignore_changes = [
      source_configuration[0].image_repository[0].image_identifier
    ]
  }
}

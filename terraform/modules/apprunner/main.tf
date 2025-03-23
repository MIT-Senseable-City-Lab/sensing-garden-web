resource "aws_iam_role" "app_runner_service_role" {
  name = "${var.app_name}-apprunner-service-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "build.apprunner.amazonaws.com"
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

resource "aws_apprunner_service" "service" {
  service_name = var.app_name
  
  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.app_runner_service_role.arn
    }
    
    image_repository {
      image_configuration {
        port = var.port
        runtime_environment_variables = {
          "FLASK_APP"               = "app.py"
          "FLASK_ENV"               = "production"
          "SENSING_GARDEN_API_KEY"  = var.sensing_garden_api_key
          "API_BASE_URL"            = var.api_base_url
        }
      }
      image_identifier      = "${var.ecr_repository_url}:${var.image_tag}"
      image_repository_type = "ECR"
    }
    
    auto_deployments_enabled = var.auto_deployments_enabled
  }
  
  instance_configuration {
    cpu    = var.instance_configuration.cpu
    memory = var.instance_configuration.memory
  }
  
  health_check_configuration {
    path     = "/"
    protocol = "HTTP"
  }
  
  tags = var.tags
  
  depends_on = [aws_iam_role_policy_attachment.app_runner_service_policy]
}

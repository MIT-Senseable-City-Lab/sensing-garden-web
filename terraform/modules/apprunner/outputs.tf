output "service_url" {
  description = "The URL of the App Runner service"
  value       = aws_apprunner_service.service.service_url
}

output "service_arn" {
  description = "The ARN of the App Runner service"
  value       = aws_apprunner_service.service.arn
}

output "service_id" {
  description = "The ID of the App Runner service"
  value       = aws_apprunner_service.service.service_id
}

output "service_status" {
  description = "The status of the App Runner service"
  value       = aws_apprunner_service.service.status
}

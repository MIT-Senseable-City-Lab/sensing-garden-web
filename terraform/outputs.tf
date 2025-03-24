output "app_runner_service_url" {
  description = "The URL of the App Runner service"
  value       = module.apprunner.service_url
}

output "app_runner_service_status" {
  description = "The status of the App Runner service"
  value       = module.apprunner.service_status
}

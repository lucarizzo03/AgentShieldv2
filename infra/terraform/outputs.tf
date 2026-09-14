output "alb_dns_name" {
  value = module.ecs.alb_dns_name
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "postgres_dsn_secret_arn" {
  description = "Secrets Manager secret holding the full app DSN, composed at apply time."
  value       = aws_secretsmanager_secret.postgres_dsn.arn
}

output "elasticache_endpoint" {
  value = module.elasticache.primary_endpoint_address
}

output "ecr_repository_url" {
  value = module.ecs.ecr_repository_url
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "ecs_service_name" {
  value = module.ecs.service_name
}

output "migrate_task_definition" {
  value = module.ecs.migrate_task_definition
}

output "migrate_network_configuration" {
  value = module.ecs.task_network_configuration
}

output "cognito_user_pool_id" {
  value = module.cognito.user_pool_id
}

output "cognito_app_client_id" {
  value = module.cognito.app_client_id
}

output "cognito_hosted_ui_domain" {
  value = module.cognito.hosted_ui_domain
}

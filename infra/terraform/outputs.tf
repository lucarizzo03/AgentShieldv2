output "alb_dns_name" {
  value = module.ecs.alb_dns_name
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "rds_secret_arn" {
  value = module.rds.secret_arn
}

output "elasticache_endpoint" {
  value = module.elasticache.primary_endpoint_address
}

output "ecr_repository_url" {
  value = module.ecs.ecr_repository_url
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

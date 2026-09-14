output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "migrate_task_definition" {
  value = aws_ecs_task_definition.migrate.family
}

output "task_network_configuration" {
  description = "Ready-made --network-configuration value for `aws ecs run-task` with the migrate task definition."
  value       = "awsvpcConfiguration={subnets=[${join(",", var.private_subnet_ids)}],securityGroups=[${var.sg_ecs_tasks_id}],assignPublicIp=DISABLED}"
}

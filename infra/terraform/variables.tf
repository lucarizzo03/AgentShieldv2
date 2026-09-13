variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
}

variable "project_name" {
  description = "Project name, used as a prefix for resource naming."
  type        = string
  default     = "agentshield"
}

variable "environment" {
  description = "Deployment environment name (e.g. prod, staging)."
  type        = string
  default     = "prod"
}

variable "rds_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_allocated_storage" {
  description = "RDS initial allocated storage, in GB."
  type        = number
  default     = 20
}

variable "rds_multi_az" {
  description = "Whether the RDS instance is deployed Multi-AZ."
  type        = bool
  default     = false
}

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "ecs_task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 512
}

variable "ecs_task_memory" {
  description = "Fargate task memory, in MiB."
  type        = number
  default     = 1024
}

variable "ecs_desired_count" {
  description = "Desired count of running ECS tasks."
  type        = number
  default     = 2
}

variable "dashboard_origin" {
  description = "Origin (scheme + host, no trailing slash) the dashboard is served from. Used to build Cognito callback/logout URLs."
  type        = string
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for the ALB HTTPS listener. Required only if enable_https is true."
  type        = string
  default     = ""
}

variable "enable_https" {
  description = "Whether to configure the ALB with an HTTPS (443) listener using acm_certificate_arn. When false, falls back to a plain HTTP (80) listener."
  type        = bool
  default     = false
}

variable "api_public_url" {
  description = "Public URL the API is reached at (e.g. https://api.example.com), used for the API_PUBLIC_URL container env var. The ALB's own DNS name isn't usable here — it's only known after this same apply creates the ALB, and there's no custom domain/Route53 wired up yet (see enable_https). Leave blank on first apply; once you know the ALB DNS name (or a custom domain pointed at it) from `terraform output alb_dns_name`, set this and re-apply."
  type        = string
  default     = ""
}

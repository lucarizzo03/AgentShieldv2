variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "sg_alb_id" {
  type = string
}

variable "sg_ecs_tasks_id" {
  type = string
}

variable "task_cpu" {
  type = number
}

variable "task_memory" {
  type = number
}

variable "desired_count" {
  type = number
}

variable "acm_certificate_arn" {
  type    = string
  default = ""
}

variable "enable_https" {
  type    = bool
  default = false
}

variable "container_environment" {
  description = "Non-secret environment variables for the api container."
  type        = map(string)
  default     = {}
}

variable "app_secret_arns" {
  description = "Map of container env var name -> Secrets Manager secret ARN, injected via the task definition's secrets block (e.g. POSTGRES_DSN, REDIS_DSN, WEBHOOK_HMAC_SECRET, AGENT_HMAC_SECRET, ANTHROPIC_API_KEY, SENDGRID_API_KEY). These secrets are not created by this module — see root main.tf."
  type        = map(string)
  default     = {}
}

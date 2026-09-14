variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "dashboard_origin" {
  description = "Origin (scheme + host, no trailing slash) the dashboard is served from."
  type        = string
}

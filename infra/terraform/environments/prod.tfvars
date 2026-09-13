aws_region   = "us-east-2"
project_name = "agentshield"
environment  = "prod"

rds_instance_class    = "db.t4g.micro"
rds_allocated_storage = 20
rds_multi_az          = false

redis_node_type = "cache.t4g.micro"

ecs_task_cpu      = 512
ecs_task_memory   = 1024
ecs_desired_count = 2

# Required — fill in with the actual dashboard origin (e.g. "https://app.agentshield.example.com").
dashboard_origin = "https://CHANGEME.example.com"

acm_certificate_arn = ""
enable_https        = false

# Leave blank on first apply — the ALB DNS name doesn't exist yet. Set this
# after the first apply (see `terraform output alb_dns_name`) and re-apply.
api_public_url = ""

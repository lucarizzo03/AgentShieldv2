aws_region   = "us-east-2"
project_name = "agentshield"
environment  = "prod"

rds_instance_class    = "db.t4g.micro"
rds_allocated_storage = 20
rds_multi_az          = false

redis_node_type          = "cache.t4g.micro"
redis_num_cache_clusters = 2

ecs_task_cpu      = 512
ecs_task_memory   = 1024
ecs_desired_count = 2

# Vercel-hosted dashboard. Also feeds the Cognito callback/logout URLs, so it must
# match the origin the browser actually loads (no trailing slash).
dashboard_origin = "https://agent-shieldv2.vercel.app"

# image_tag is deliberately not set here: it changes every build. Pass it on
# the command line, e.g.
#   terraform apply -var-file=environments/prod.tfvars -var image_tag=$(git rev-parse --short HEAD)

hitl_email_from = ""
hitl_email_to   = ""

acm_certificate_arn = ""
enable_https        = false

# Leave blank on first apply — the ALB DNS name doesn't exist yet. Set this
# after the first apply (see `terraform output alb_dns_name`) and re-apply.
api_public_url = ""

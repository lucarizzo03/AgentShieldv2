locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

module "network" {
  source = "./modules/network"

  project_name = var.project_name
  environment  = var.environment
}

resource "random_password" "postgres" {
  length = 32
  # URL-safe only: this password is interpolated into the DSN below, and
  # percent-encoding it there would have to be undone by every consumer.
  special = false
}

module "rds" {
  source = "./modules/rds"

  project_name       = var.project_name
  environment        = var.environment
  instance_class     = var.rds_instance_class
  allocated_storage  = var.rds_allocated_storage
  multi_az           = var.rds_multi_az
  password           = random_password.postgres.result
  private_subnet_ids = module.network.private_subnet_ids
  sg_rds_id          = module.network.sg_rds_id
}

module "elasticache" {
  source = "./modules/elasticache"

  project_name       = var.project_name
  environment        = var.environment
  node_type          = var.redis_node_type
  num_cache_clusters = var.redis_num_cache_clusters
  private_subnet_ids = module.network.private_subnet_ids
  sg_elasticache_id  = module.network.sg_elasticache_id
}

module "cognito" {
  source = "./modules/cognito"

  project_name     = var.project_name
  environment      = var.environment
  aws_region       = var.aws_region
  dashboard_origin = var.dashboard_origin
}

# The actual connection strings depend on the rds/elasticache modules'
# outputs, so they're composed here at the root rather than inside the ecs
# module, and stored in Secrets Manager for the task definition's `secrets`
# block to reference. POSTGRES_DSN/REDIS_DSN are fully populated and
# Terraform-owned; the remaining app secrets are created empty placeholders —
# fill them in via `aws secretsmanager put-secret-value` (or the console)
# after apply, since their values (API keys, HMAC secrets) don't come from
# any Terraform-managed resource.
resource "aws_secretsmanager_secret" "postgres_dsn" {
  name = "${local.name_prefix}/postgres-dsn"
}

# module.rds.endpoint carries the :5432 suffix already. sslmode=require is
# explicit rather than relying on libpq's `prefer`, which silently falls back
# to plaintext if the TLS handshake fails.
resource "aws_secretsmanager_secret_version" "postgres_dsn" {
  secret_id     = aws_secretsmanager_secret.postgres_dsn.id
  secret_string = "postgresql://${module.rds.username}:${random_password.postgres.result}@${module.rds.endpoint}/${module.rds.db_name}?sslmode=require"
}

resource "aws_secretsmanager_secret" "redis_dsn" {
  name = "${local.name_prefix}/redis-dsn"
}

resource "aws_secretsmanager_secret_version" "redis_dsn" {
  secret_id     = aws_secretsmanager_secret.redis_dsn.id
  secret_string = "redis://${module.elasticache.primary_endpoint_address}:6379/0"
}

resource "aws_secretsmanager_secret" "webhook_hmac_secret" {
  name = "${local.name_prefix}/webhook-hmac-secret"
}

resource "aws_secretsmanager_secret_version" "webhook_hmac_secret" {
  secret_id     = aws_secretsmanager_secret.webhook_hmac_secret.id
  secret_string = "CHANGEME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "agent_hmac_secret" {
  name = "${local.name_prefix}/agent-hmac-secret"
}

resource "aws_secretsmanager_secret_version" "agent_hmac_secret" {
  secret_id     = aws_secretsmanager_secret.agent_hmac_secret.id
  secret_string = "CHANGEME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name = "${local.name_prefix}/anthropic-api-key"
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = "CHANGEME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "sendgrid_api_key" {
  name = "${local.name_prefix}/sendgrid-api-key"
}

resource "aws_secretsmanager_secret_version" "sendgrid_api_key" {
  secret_id     = aws_secretsmanager_secret.sendgrid_api_key.id
  secret_string = "CHANGEME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# Outside dev, /metrics and /metrics.json 404 unless this bearer token is set,
# so the endpoint is unreachable — including by a scraper — until it's filled in.
resource "aws_secretsmanager_secret" "metrics_auth_token" {
  name = "${local.name_prefix}/metrics-auth-token"
}

resource "aws_secretsmanager_secret_version" "metrics_auth_token" {
  secret_id     = aws_secretsmanager_secret.metrics_auth_token.id
  secret_string = "CHANGEME"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

module "ecs" {
  source = "./modules/ecs"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids
  sg_alb_id          = module.network.sg_alb_id
  sg_ecs_tasks_id    = module.network.sg_ecs_tasks_id

  image_tag     = var.image_tag
  task_cpu      = var.ecs_task_cpu
  task_memory   = var.ecs_task_memory
  desired_count = var.ecs_desired_count

  acm_certificate_arn = var.acm_certificate_arn
  enable_https        = var.enable_https

  container_environment = {
    APP_ENV               = var.environment
    CORS_ALLOWED_ORIGINS  = var.dashboard_origin
    COGNITO_REGION        = var.aws_region
    COGNITO_USER_POOL_ID  = module.cognito.user_pool_id
    COGNITO_APP_CLIENT_ID = module.cognito.app_client_id
    ANTHROPIC_MODEL_NAME  = "claude-haiku-4-5-20251001"
    API_PUBLIC_URL        = var.api_public_url

    # Shadow evaluation runs inline, so a sampled hard-deny pays up to the SLM
    # deadline in extra latency. 0 disables it.
    SHADOW_EVAL_SAMPLE_RATE = tostring(var.shadow_eval_sample_rate)
    HITL_EMAIL_FROM         = var.hitl_email_from
    HITL_EMAIL_TO           = var.hitl_email_to
  }

  app_secret_arns = {
    POSTGRES_DSN        = aws_secretsmanager_secret.postgres_dsn.arn
    REDIS_DSN           = aws_secretsmanager_secret.redis_dsn.arn
    WEBHOOK_HMAC_SECRET = aws_secretsmanager_secret.webhook_hmac_secret.arn
    AGENT_HMAC_SECRET   = aws_secretsmanager_secret.agent_hmac_secret.arn
    ANTHROPIC_API_KEY   = aws_secretsmanager_secret.anthropic_api_key.arn
    SENDGRID_API_KEY    = aws_secretsmanager_secret.sendgrid_api_key.arn
    METRICS_AUTH_TOKEN  = aws_secretsmanager_secret.metrics_auth_token.arn
  }
}

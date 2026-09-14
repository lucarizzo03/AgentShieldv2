locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${local.name_prefix}-cache-subnet-group"
  subnet_ids = var.private_subnet_ids
}

# Redis is not a cache here: it holds daily budget counters, outstanding
# budget reservations, idempotency records and the sweeper/reconciler locks.
# Evicting a budget key silently resets an agent's daily spend, so the policy
# is noeviction — the app must see OOM errors rather than lose spend state.
resource "aws_elasticache_parameter_group" "this" {
  name   = "${local.name_prefix}-redis7"
  family = "redis7"

  parameter {
    name  = "maxmemory-policy"
    value = "noeviction"
  }
}

# TLS (rediss://) is a documented fast-follow, not part of v1 — keeping the
# DSN swap from Railway purely mechanical for the initial migration.
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "AgentShield ${var.environment} Redis"

  engine         = "redis"
  engine_version = "7.1"
  node_type      = var.node_type

  # A single node means a replacement loses every reservation and resets all
  # daily budgets to zero (budget fail-open), so the default is a replica with
  # automatic failover plus daily snapshots.
  num_cache_clusters         = var.num_cache_clusters
  automatic_failover_enabled = var.num_cache_clusters > 1
  multi_az_enabled           = var.num_cache_clusters > 1
  snapshot_retention_limit   = var.snapshot_retention_limit

  parameter_group_name = aws_elasticache_parameter_group.this.name
  subnet_group_name    = aws_elasticache_subnet_group.this.name
  security_group_ids   = [var.sg_elasticache_id]

  tags = {
    Name = "${local.name_prefix}-redis"
  }
}

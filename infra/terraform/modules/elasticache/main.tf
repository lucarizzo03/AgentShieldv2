locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_elasticache_subnet_group" "this" {
  name       = "${local.name_prefix}-cache-subnet-group"
  subnet_ids = var.private_subnet_ids
}

# TLS (rediss://) is a documented fast-follow, not part of v1 — keeping the
# DSN swap from Railway purely mechanical for the initial migration.
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "AgentShield ${var.environment} Redis"

  engine         = "redis"
  engine_version = "7.1"
  node_type      = var.node_type

  num_cache_clusters = 1

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [var.sg_elasticache_id]

  tags = {
    Name = "${local.name_prefix}-redis"
  }
}

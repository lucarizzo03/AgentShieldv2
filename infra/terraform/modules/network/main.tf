locals {
  name_prefix = "${var.project_name}-${var.environment}"
  azs         = ["${data.aws_region.current.name}a", "${data.aws_region.current.name}b"]
}

data "aws_region" "current" {}

resource "aws_vpc" "this" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet("10.0.0.0/16", 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-${count.index}"
  }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet("10.0.0.0/16", 8, count.index + 10)
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${local.name_prefix}-private-${count.index}"
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-nat-eip"
  }
}

# Single NAT gateway (not one per AZ) — keeps cost down for a single-service
# app; private subnets share it for outbound internet access.
resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name = "${local.name_prefix}-nat"
  }

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this.id
  }

  tags = {
    Name = "${local.name_prefix}-private-rt"
  }
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# The four security groups are declared with no inline ingress/egress blocks
# and wired up via standalone aws_vpc_security_group_*_rule resources below.
# sg_alb and sg_ecs_tasks reference each other (ALB -> tasks on 8000, tasks
# ingress from ALB), which is a circular reference if expressed as inline
# blocks on the aws_security_group resources themselves — Terraform can't
# resolve a cycle between two resources that each embed the other's rules.
# Standalone rule resources break the cycle because they depend on both
# security groups' ids without either group's own resource depending on the
# other's.
resource "aws_security_group" "alb" {
  name_prefix = "${local.name_prefix}-alb-"
  description = "ALB — public ingress on 80/443"
  vpc_id      = aws_vpc.this.id

  tags = {
    Name = "${local.name_prefix}-sg-alb"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "ecs_tasks" {
  name_prefix = "${local.name_prefix}-ecs-tasks-"
  description = "ECS tasks — ingress from ALB only"
  vpc_id      = aws_vpc.this.id

  tags = {
    Name = "${local.name_prefix}-sg-ecs-tasks"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "rds" {
  name_prefix = "${local.name_prefix}-rds-"
  description = "RDS — ingress from ECS tasks only"
  vpc_id      = aws_vpc.this.id

  tags = {
    Name = "${local.name_prefix}-sg-rds"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "elasticache" {
  name_prefix = "${local.name_prefix}-elasticache-"
  description = "ElastiCache — ingress from ECS tasks only"
  vpc_id      = aws_vpc.this.id

  tags = {
    Name = "${local.name_prefix}-sg-elasticache"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --- sg_alb rules ---

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from internet"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from internet"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_ecs_tasks" {
  security_group_id            = aws_security_group.alb.id
  description                  = "To ECS tasks only"
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.ecs_tasks.id
}

# --- sg_ecs_tasks rules ---

resource "aws_vpc_security_group_ingress_rule" "ecs_tasks_from_alb" {
  security_group_id            = aws_security_group.ecs_tasks.id
  description                  = "App port from ALB"
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "ecs_tasks_to_rds" {
  security_group_id            = aws_security_group.ecs_tasks.id
  description                  = "Postgres to RDS"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.rds.id
}

resource "aws_vpc_security_group_egress_rule" "ecs_tasks_to_elasticache" {
  security_group_id            = aws_security_group.ecs_tasks.id
  description                  = "Redis to ElastiCache"
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.elasticache.id
}

resource "aws_vpc_security_group_egress_rule" "ecs_tasks_to_internet_https" {
  security_group_id = aws_security_group.ecs_tasks.id
  description       = "HTTPS to internet (Anthropic, SendGrid, Secrets Manager, ECR, etc.)"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

# --- sg_rds rules ---

resource "aws_vpc_security_group_ingress_rule" "rds_from_ecs_tasks" {
  security_group_id            = aws_security_group.rds.id
  description                  = "Postgres from ECS tasks"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.ecs_tasks.id
}

# --- sg_elasticache rules ---

resource "aws_vpc_security_group_ingress_rule" "elasticache_from_ecs_tasks" {
  security_group_id            = aws_security_group.elasticache.id
  description                  = "Redis from ECS tasks"
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.ecs_tasks.id
}

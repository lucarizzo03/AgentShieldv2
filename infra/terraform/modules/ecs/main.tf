locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

# --- ECR ---

resource "aws_ecr_repository" "this" {
  name                 = "${local.name_prefix}-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${local.name_prefix}-api"
  }
}

# --- ECS cluster ---

resource "aws_ecs_cluster" "this" {
  name = "${local.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${local.name_prefix}-cluster"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# --- IAM ---

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${local.name_prefix}-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "task_execution_secrets" {
  count = length(var.app_secret_arns) > 0 ? 1 : 0

  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = values(var.app_secret_arns)
  }
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  count  = length(var.app_secret_arns) > 0 ? 1 : 0
  name   = "${local.name_prefix}-task-execution-secrets"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution_secrets[0].json
}

# Task role is intentionally near-empty: the app never makes AWS SDK calls at
# runtime. Postgres/Redis are reached over the network via DSN, Anthropic and
# SendGrid are plain HTTPS calls, and container logs are shipped by the
# awslogs driver, which runs under the execution role — not the task role.
resource "aws_iam_role" "task" {
  name               = "${local.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
}

# --- CloudWatch logs ---

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/agentshield-api"
  retention_in_days = 30
}

# --- Task definition ---

resource "aws_ecs_task_definition" "this" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  # On first apply this image tag does not exist yet — the ECR repo is
  # created empty. Build and push the image (see repo Dockerfile), then
  # force a new deployment; the service will not stabilize until a matching
  # tag is pushed. The repo is IMMUTABLE, so var.image_tag must be a fresh
  # tag per build (a git SHA), never a moving `latest`.
  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        for name, value in var.container_environment : {
          name  = name
          value = value
        }
      ]

      secrets = [
        for name, arn in var.app_secret_arns : {
          name      = name
          valueFrom = arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])

  tags = {
    Name = "${local.name_prefix}-api"
  }
}

# Same image, run as a one-off `aws ecs run-task` before each deploy. Alembic
# owns the Postgres schema — the app no longer creates tables at startup — so
# this task is the only thing that migrates the database.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "migrate"
      image     = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
      essential = true
      command   = ["alembic", "upgrade", "head"]

      environment = [
        for name, value in var.container_environment : {
          name  = name
          value = value
        }
      ]

      secrets = [
        for name, arn in var.app_secret_arns : {
          name      = name
          valueFrom = arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "migrate"
        }
      }
    }
  ])

  tags = {
    Name = "${local.name_prefix}-migrate"
  }
}

# --- ALB ---

resource "aws_lb" "this" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.sg_alb_id]
  subnets            = var.public_subnet_ids

  tags = {
    Name = "${local.name_prefix}-alb"
  }
}

resource "aws_lb_target_group" "this" {
  name        = "${local.name_prefix}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  # The health router is mounted without a prefix (app/main.py), so liveness
  # is /health, not /v1/health. /ready additionally pings Postgres and Redis;
  # it is deliberately not the target-group check, because a Redis blip would
  # then take every task out of service instead of degrading requests.
  health_check {
    path                = "/health"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name = "${local.name_prefix}-api-tg"
  }
}

resource "aws_lb_listener" "https" {
  count             = var.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

resource "aws_lb_listener" "http" {
  count             = var.enable_https ? 0 : 1
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

# --- ECS service ---

resource "aws_ecs_service" "this" {
  name            = "${local.name_prefix}-api"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 60
  enable_execute_command            = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.sg_ecs_tasks_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https, aws_lb_listener.http]

  tags = {
    Name = "${local.name_prefix}-api"
  }
}

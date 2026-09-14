locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name_prefix}-db-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "${local.name_prefix}-db-subnet-group"
  }
}

resource "aws_db_instance" "this" {
  identifier     = "${local.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = "16"

  instance_class        = var.instance_class
  allocated_storage     = var.allocated_storage
  max_allocated_storage = 100
  storage_type          = "gp3"

  db_name  = "agentshield"
  username = "agentshield"

  # Not `manage_master_user_password`: AWS would generate the password into a
  # secret of its own and rotate it, while the app reads a separate DSN secret
  # that would then go stale. The password is passed in so the DSN can be
  # composed from it at apply time with no manual step.
  password = var.password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.sg_rds_id]
  publicly_accessible    = false

  multi_az            = var.multi_az
  skip_final_snapshot = true

  tags = {
    Name = "${local.name_prefix}-postgres"
  }
}

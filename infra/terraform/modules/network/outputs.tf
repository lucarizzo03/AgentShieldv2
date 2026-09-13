output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "sg_alb_id" {
  value = aws_security_group.alb.id
}

output "sg_ecs_tasks_id" {
  value = aws_security_group.ecs_tasks.id
}

output "sg_rds_id" {
  value = aws_security_group.rds.id
}

output "sg_elasticache_id" {
  value = aws_security_group.elasticache.id
}

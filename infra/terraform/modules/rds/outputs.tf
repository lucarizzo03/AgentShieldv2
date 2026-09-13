output "endpoint" {
  value = aws_db_instance.this.endpoint
}

output "secret_arn" {
  value = aws_db_instance.this.master_user_secret[0].secret_arn
}

variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "node_type" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "sg_elasticache_id" {
  type = string
}

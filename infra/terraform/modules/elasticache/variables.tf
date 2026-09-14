variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "node_type" {
  type = string
}

variable "num_cache_clusters" {
  description = "Nodes in the replication group. 2+ enables automatic failover; 1 makes Redis a single point of spend-state loss."
  type        = number
  default     = 2
}

variable "snapshot_retention_limit" {
  type    = number
  default = 5
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "sg_elasticache_id" {
  type = string
}

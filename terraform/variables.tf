variable "aws_region" {
  description = "AWS region for the demo instance."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name used for AWS resource names and tags."
  type        = string
  default     = "relay-ops"
}

variable "instance_type" {
  description = "EC2 instance size; verify current AWS pricing and free-tier eligibility."
  type        = string
  default     = "t3.micro"
}

variable "ssh_key_name" {
  description = "Name of an existing EC2 key pair used for SSH access."
  type        = string

  validation {
    condition     = length(trimspace(var.ssh_key_name)) > 0
    error_message = "Set ssh_key_name to an existing EC2 key pair."
  }
}

variable "admin_cidr" {
  description = "Your public IPv4 CIDR, used to restrict SSH and Grafana (for example 203.0.113.10/32)."
  type        = string

  validation {
    condition     = can(cidrnetmask(var.admin_cidr))
    error_message = "admin_cidr must be a valid IPv4 CIDR block."
  }
}

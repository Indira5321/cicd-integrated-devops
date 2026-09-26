terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_security_group" "relay_ops" {
  name        = "${var.project_name}-service"
  description = "Relay Ops API, Grafana, and administrator SSH"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH from administrator IP only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  ingress {
    description = "Demo API and dashboard"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Grafana from administrator IP only"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-service"
    Project = var.project_name
  }
}

resource "aws_instance" "relay_ops" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = var.instance_type
  key_name                    = var.ssh_key_name
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.relay_ops.id]
  associate_public_ip_address = true
  user_data_replace_on_change = true

  user_data = <<-BOOTSTRAP
    #!/bin/bash
    set -euxo pipefail
    dnf update -y
    dnf install -y docker curl
    systemctl enable --now docker
    usermod -aG docker ec2-user
    curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose
    chmod 0755 /usr/local/bin/docker-compose
    mkdir -p /opt/relay-ops
    chown ec2-user:ec2-user /opt/relay-ops
  BOOTSTRAP

  root_block_device {
    volume_size           = 20
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name    = var.project_name
    Project = var.project_name
  }
}

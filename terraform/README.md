# Terraform deployment

This directory provisions a single Amazon Linux EC2 instance and a security group in the account's default VPC. The instance bootstrap installs Docker and the standalone Compose binary. No AWS resources are created until you run `terraform apply`.

Copy `terraform.tfvars.example` to `terraform.tfvars`, set an existing EC2 key pair and your current public IP as `/32`, then run `terraform init`, `terraform plan`, and `terraform apply`. AWS credentials must already be configured in your shell. The app is exposed on port 8080; SSH (22) and Grafana (3000) are restricted to `admin_cidr`.

Terraform outputs the app URL, Grafana URL, and public IP. Set the public IP as the GitHub Actions `DEPLOY_HOST` secret and install the matching private key as `DEPLOY_SSH_KEY`. Destroy the demo with `terraform destroy` when finished. Review AWS costs before applying.

output "public_ip" {
  description = "EC2 public IPv4 address."
  value       = aws_instance.relay_ops.public_ip
}

output "app_url" {
  description = "Application and dashboard URL (HTTP demo endpoint)."
  value       = "http://${aws_instance.relay_ops.public_ip}:8080"
}

output "grafana_url" {
  description = "Grafana URL, reachable from admin_cidr."
  value       = "http://${aws_instance.relay_ops.public_ip}:3000"
}

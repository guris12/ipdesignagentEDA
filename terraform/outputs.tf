# =============================================================================
# outputs.tf — Key values needed after terraform apply
# =============================================================================

# ---------------------------------------------------------------------------
# Domain URLs
# ---------------------------------------------------------------------------

output "train_url" {
  description = "Streamlit training UI"
  value       = "https://train.${var.domain_name}"
}

output "api_url" {
  description = "FastAPI endpoint"
  value       = "https://api.${var.domain_name}"
}

# ---------------------------------------------------------------------------
# ALB
# ---------------------------------------------------------------------------

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.main.dns_name
}

# ---------------------------------------------------------------------------
# ECR
# ---------------------------------------------------------------------------

output "ecr_repository_url" {
  description = "ECR repository URL for agent Docker image"
  value       = aws_ecr_repository.app.repository_url
}

output "ecr_login_command" {
  description = "Command to authenticate Docker with ECR"
  value       = "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

# ---------------------------------------------------------------------------
# RDS
# ---------------------------------------------------------------------------

output "rds_endpoint" {
  description = "RDS PostgreSQL endpoint (host:port)"
  value       = aws_db_instance.main.endpoint
}

output "rds_hostname" {
  description = "RDS hostname only (without port)"
  value       = aws_db_instance.main.address
}

output "database_connection_string" {
  description = "PostgreSQL connection string (password not shown)"
  value       = "postgresql://${var.db_username}:****@${aws_db_instance.main.address}:5432/${var.db_name}"
  sensitive   = false
}

# ---------------------------------------------------------------------------
# ECS
# ---------------------------------------------------------------------------

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.app.name
}

# ---------------------------------------------------------------------------
# CloudWatch
# ---------------------------------------------------------------------------

output "cloudwatch_dashboard_url" {
  description = "URL to the CloudWatch dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${var.project_name}-dashboard"
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group for ECS container logs"
  value       = aws_cloudwatch_log_group.ecs.name
}

# ---------------------------------------------------------------------------
# Secrets Manager ARNs
# ---------------------------------------------------------------------------

output "secret_arns" {
  description = "ARNs of Secrets Manager secrets"
  value = {
    openai_api_key    = aws_secretsmanager_secret.openai_api_key.arn
    langchain_api_key = aws_secretsmanager_secret.langchain_api_key.arn
    db_credentials    = aws_secretsmanager_secret.db_credentials.arn
  }
}

# ---------------------------------------------------------------------------
# Cost Estimate Summary
# ---------------------------------------------------------------------------

output "estimated_monthly_cost" {
  description = "Rough monthly cost estimate for this infrastructure"
  value       = <<-EOT
    Estimated monthly cost (eu-west-1, dev, NO NAT Gateway):
    -------------------------------------------------------
    ALB:                  ~$18  (fixed + LCU hours)
    Agent (0.5 vCPU, 1GB): ~$15  (24/7)
    OpenROAD (off by default): $0  (start manually for training)
    RDS (t4g.micro):      ~$14  (may be free tier eligible)
    EFS:                  ~$1   (minimal storage)
    CloudWatch:           ~$6   (logs + dashboard + alarms)
    Secrets Manager:      ~$1   (3 secrets)
    ECR:                  ~$1   (image storage)
    Route53:              ~$0.50 (hosted zone)
    ACM Certificate:      Free
    -------------------------------------------------------
    TOTAL:                ~$57/mo (agent always-on)

    To reduce costs:
    - Set ecs_desired_count = 0 when not demoing  (~$15/mo saved)
    - OpenROAD runner is OFF by default (start for training sessions)
    - terraform destroy when done ($0)
  EOT
}

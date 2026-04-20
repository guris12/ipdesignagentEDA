# =============================================================================
# variables.tf — All configurable variables with sensible defaults
# =============================================================================

# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------

variable "project_name" {
  description = "Name prefix for all resources"
  type        = string
  default     = "ip-design-agent"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "aws_region" {
  description = "AWS region — eu-west-1 is Dublin, Ireland"
  type        = string
  default     = "eu-west-1"
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

# ---------------------------------------------------------------------------
# ECS / Fargate — Agent (Streamlit + FastAPI)
# ---------------------------------------------------------------------------

variable "ecs_task_cpu" {
  description = "CPU units for agent ECS task (1024 = 1 vCPU)"
  type        = number
  default     = 512
}

variable "ecs_task_memory" {
  description = "Memory (MiB) for agent ECS task"
  type        = number
  default     = 1024
}

variable "ecs_desired_count" {
  description = "Number of agent ECS tasks to run"
  type        = number
  default     = 1
}

variable "container_image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

# ---------------------------------------------------------------------------
# ECS / Fargate — OpenROAD runner (Phase 2)
# ---------------------------------------------------------------------------

variable "openroad_task_cpu" {
  description = "CPU units for OpenROAD ECS task (1024 = 1 vCPU)"
  type        = number
  default     = 2048
}

variable "openroad_task_memory" {
  description = "Memory (MiB) for OpenROAD ECS task"
  type        = number
  default     = 4096
}

variable "openroad_image_tag" {
  description = "Docker image tag for OpenROAD runner"
  type        = string
  default     = "latest"
}

# ---------------------------------------------------------------------------
# RDS
# ---------------------------------------------------------------------------

variable "db_instance_class" {
  description = "RDS instance class — db.t4g.micro is free tier eligible"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB for RDS"
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Name of the PostgreSQL database"
  type        = string
  default     = "ip_agent_db"
}

variable "db_username" {
  description = "Master username for RDS"
  type        = string
  default     = "ip_agent"
}

# ---------------------------------------------------------------------------
# Secrets (provide via terraform.tfvars or -var flag, never commit)
# ---------------------------------------------------------------------------

variable "db_password" {
  description = "Master password for RDS (min 8 chars)"
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key for embeddings and generation"
  type        = string
  sensitive   = true
}

variable "langchain_api_key" {
  description = "LangChain/LangSmith API key for tracing"
  type        = string
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Domain / HTTPS
# ---------------------------------------------------------------------------

variable "domain_name" {
  description = "Root domain name (e.g., viongen.in)"
  type        = string
  default     = "viongen.in"
}

variable "route53_zone_id" {
  description = "Route53 hosted zone ID for the domain"
  type        = string
  default     = "Z03876111LTMIY2UWC6KV"
}

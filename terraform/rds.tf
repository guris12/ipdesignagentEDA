# =============================================================================
# rds.tf — RDS PostgreSQL 16 with pgvector extension
# =============================================================================
# Estimated monthly cost:
#   db.t4g.micro:  ~$12/mo (free tier eligible for 12 months)
#   db.t4g.small:  ~$24/mo
#   Storage (20GB): ~$2.30/mo (gp3)
#   Total:          ~$14-26/mo depending on instance class
# =============================================================================

# ---------------------------------------------------------------------------
# DB Subnet Group — RDS will be placed in private subnets
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${var.project_name}-db-subnet-group"
  }
}

# ---------------------------------------------------------------------------
# Parameter Group — enables pgvector and tunes PostgreSQL for vector workloads
# ---------------------------------------------------------------------------

resource "aws_db_parameter_group" "postgres16" {
  name   = "${var.project_name}-postgres16-params"
  family = "postgres16"

  # shared_preload_libraries is set at the cluster level for pgvector.
  # The pgvector extension is installed via CREATE EXTENSION in the app code:
  #   CREATE EXTENSION IF NOT EXISTS vector;
  #
  # pgvector doesn't need shared_preload_libraries — it's a regular extension.
  # These parameters tune PostgreSQL for vector similarity search workloads:

  parameter {
    name  = "work_mem"
    value = "256000" # 256MB — helps with large vector sorts (default is 4MB)
  }

  parameter {
    name  = "maintenance_work_mem"
    value = "512000" # 512MB — speeds up CREATE INDEX on vector columns
  }

  parameter {
    name         = "max_connections"
    value        = "100"
    apply_method = "pending-reboot"
  }

  tags = {
    Name = "${var.project_name}-db-params"
  }
}

# ---------------------------------------------------------------------------
# RDS Instance
# ---------------------------------------------------------------------------

resource "aws_db_instance" "main" {
  identifier = "${var.project_name}-db"

  # Engine
  engine               = "postgres"
  engine_version       = "16.6"
  instance_class       = var.db_instance_class
  parameter_group_name = aws_db_parameter_group.postgres16.name

  # Storage
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 2 # Autoscaling up to 2x
  storage_type          = "gp3"
  storage_encrypted     = true

  # Database
  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  # Networking — private subnets only, NOT publicly accessible
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  port                   = 5432

  # Backup & Maintenance
  backup_retention_period = 7
  backup_window           = "03:00-04:00"         # 3-4 AM UTC
  maintenance_window      = "sun:04:00-sun:05:00" # Sunday 4-5 AM UTC

  # For a demo project — skip final snapshot for easy cleanup
  # In production, set this to false and provide a final_snapshot_identifier
  skip_final_snapshot      = true
  delete_automated_backups = true
  deletion_protection      = false # Set to true in production

  # Performance Insights (free tier includes 7 days retention)
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # Monitoring
  monitoring_interval = 0 # Set to 60 for enhanced monitoring (requires IAM role)

  tags = {
    Name = "${var.project_name}-postgres"
  }
}

# ---------------------------------------------------------------------------
# NOTE: After RDS is created, connect and run:
#   CREATE EXTENSION IF NOT EXISTS vector;
#
# This is done in the application code (ingest.py) or you can run it manually:
#   psql -h <rds-endpoint> -U ip_agent -d ip_agent_db -c "CREATE EXTENSION vector;"
# ---------------------------------------------------------------------------

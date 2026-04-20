# =============================================================================
# secrets.tf — AWS Secrets Manager
# =============================================================================
# Estimated monthly cost:
#   $0.40/secret/month + $0.05 per 10,000 API calls
#   3 secrets = ~$1.20/mo
# =============================================================================

# ---------------------------------------------------------------------------
# OpenAI API Key
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "openai_api_key" {
  name                    = "${var.project_name}/${var.environment}/openai-api-key"
  description             = "OpenAI API key for embeddings (text-embedding-3-small) and generation (GPT-4o)"
  recovery_window_in_days = 0 # Set to 30 for production; 0 allows immediate delete during dev

  tags = {
    Name = "${var.project_name}-openai-key"
  }
}

resource "aws_secretsmanager_secret_version" "openai_api_key" {
  secret_id     = aws_secretsmanager_secret.openai_api_key.id
  secret_string = var.openai_api_key
}

# ---------------------------------------------------------------------------
# LangChain / LangSmith API Key
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "langchain_api_key" {
  name                    = "${var.project_name}/${var.environment}/langchain-api-key"
  description             = "LangSmith API key for agent tracing and observability"
  recovery_window_in_days = 0

  tags = {
    Name = "${var.project_name}-langchain-key"
  }
}

resource "aws_secretsmanager_secret_version" "langchain_api_key" {
  secret_id     = aws_secretsmanager_secret.langchain_api_key.id
  secret_string = var.langchain_api_key
}

# ---------------------------------------------------------------------------
# Database Credentials (stored as JSON with username + password)
# ---------------------------------------------------------------------------

resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "${var.project_name}/${var.environment}/db-credentials"
  description             = "PostgreSQL credentials for pgvector database"
  recovery_window_in_days = 0

  tags = {
    Name = "${var.project_name}-db-credentials"
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = var.db_username
    password = var.db_password
    host     = aws_db_instance.main.address
    port     = 5432
    dbname   = var.db_name
    # Full connection string for convenience
    url = "postgresql://${var.db_username}:${var.db_password}@${aws_db_instance.main.address}:5432/${var.db_name}"
  })
}

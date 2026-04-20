# =============================================================================
# ecs.tf — ECS Fargate Cluster, Agent Task, Service, ALB with HTTPS
# =============================================================================
# Cost estimate (t4g.small equivalent on Fargate):
#   Agent (0.5 vCPU, 1GB):    ~$15/mo
#   ALB:                       ~$18/mo
#   Total:                     ~$33/mo
# =============================================================================

# ---------------------------------------------------------------------------
# ECS Cluster
# ---------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-cluster"
  }
}

# ---------------------------------------------------------------------------
# IAM — Task Execution Role (pulls images, gets secrets)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ecs_execution" {
  name = "${var.project_name}-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_basic" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "${var.project_name}-ecs-secrets-policy"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.openai_api_key.arn,
          aws_secretsmanager_secret.langchain_api_key.arn,
          aws_secretsmanager_secret.db_credentials.arn,
        ]
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# IAM — Task Role (running container's AWS access)
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "${var.project_name}-ecs-task-s3-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.dashboards.arn}/*",
          aws_s3_bucket.dashboards.arn
        ]
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Agent Task Definition (Streamlit + FastAPI)
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "app" {
  family                   = var.project_name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  volume {
    name = "shared-data"

    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.shared.id
      transit_encryption      = "ENABLED"
      authorization_config {
        access_point_id = aws_efs_access_point.shared.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name  = var.project_name
      image = "${aws_ecr_repository.app.repository_url}:${var.container_image_tag}"

      portMappings = [
        {
          containerPort = 8501
          protocol      = "tcp"
          name          = "streamlit"
        },
        {
          containerPort = 8001
          protocol      = "tcp"
          name          = "fastapi"
        }
      ]

      mountPoints = [
        {
          sourceVolume  = "shared-data"
          containerPath = "/shared"
          readOnly      = false
        }
      ]

      secrets = [
        {
          name      = "OPENAI_API_KEY"
          valueFrom = aws_secretsmanager_secret.openai_api_key.arn
        },
        {
          name      = "LANGCHAIN_API_KEY"
          valueFrom = aws_secretsmanager_secret.langchain_api_key.arn
        },
        {
          name      = "DB_CREDENTIALS"
          valueFrom = aws_secretsmanager_secret.db_credentials.arn
        }
      ]

      environment = [
        {
          name  = "LANGCHAIN_TRACING_V2"
          value = "true"
        },
        {
          name  = "LANGCHAIN_PROJECT"
          value = var.project_name
        },
        {
          name  = "ENVIRONMENT"
          value = var.environment
        },
        {
          name  = "DB_HOST"
          value = aws_db_instance.main.address
        },
        {
          name  = "DB_PORT"
          value = "5432"
        },
        {
          name  = "DB_NAME"
          value = var.db_name
        },
        {
          name  = "SHARED_DATA_PATH"
          value = "/shared"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "agent"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8001/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }

      essential = true
    }
  ])

  tags = {
    Name = "${var.project_name}-agent-task"
  }
}

# ---------------------------------------------------------------------------
# Application Load Balancer
# ---------------------------------------------------------------------------

resource "aws_lb" "main" {
  name               = "${var.project_name}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  tags = {
    Name = "${var.project_name}-alb"
  }
}

# ---------------------------------------------------------------------------
# Target Groups
# ---------------------------------------------------------------------------

resource "aws_lb_target_group" "streamlit" {
  name        = "${var.project_name}-streamlit"
  port        = 8501
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/_stcore/health"
    port                = "8501"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "${var.project_name}-streamlit-tg"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project_name}-api"
  port        = 8001
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "8001"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name = "${var.project_name}-api-tg"
  }
}

# ---------------------------------------------------------------------------
# ALB Listeners — HTTPS with HTTP redirect
# ---------------------------------------------------------------------------

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.main.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.streamlit.arn
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Route api.viongen.in to FastAPI
resource "aws_lb_listener_rule" "api_host" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 90

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    host_header {
      values = ["api.${var.domain_name}"]
    }
  }
}

# Route /api/*, /docs, /health paths to FastAPI (fallback)
resource "aws_lb_listener_rule" "api_path" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/api/*", "/docs", "/health", "/.well-known/*", "/a2a"]
    }
  }
}

# ---------------------------------------------------------------------------
# ECS Service
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "app" {
  name                   = var.project_name
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.app.arn
  desired_count          = var.ecs_desired_count
  launch_type            = "FARGATE"
  enable_execute_command = true

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.streamlit.arn
    container_name   = var.project_name
    container_port   = 8501
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = var.project_name
    container_port   = 8001
  }

  force_new_deployment = true

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  depends_on = [
    aws_lb_listener.https,
    aws_lb_listener.http,
    aws_lb_listener_rule.api_host,
    aws_lb_listener_rule.api_path,
    aws_efs_mount_target.shared,
  ]

  tags = {
    Name = "${var.project_name}-service"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

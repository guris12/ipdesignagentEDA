# =============================================================================
# ecs_openroad.tf — OpenROAD Runner ECS Task (Phase 2)
# =============================================================================
# A separate Fargate task running OpenROAD-flow-scripts + sky130 PDK.
# Shares EFS volume with the agent for report exchange.
#
# Cost: t4g.medium equivalent (2 vCPU, 4GB) ~$30/mo if running 24/7
#       Set desired_count=0 when not in use to save costs
# =============================================================================

# ---------------------------------------------------------------------------
# ECR Repository for OpenROAD image
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "openroad" {
  name                 = "${var.project_name}-openroad"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${var.project_name}-openroad-ecr"
  }
}

resource "aws_ecr_lifecycle_policy" "openroad" {
  repository = aws_ecr_repository.openroad.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep only last 5 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# OpenROAD Task Definition
# ---------------------------------------------------------------------------

resource "aws_ecs_task_definition" "openroad" {
  family                   = "${var.project_name}-openroad"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.openroad_task_cpu
  memory                   = var.openroad_task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  # OpenROAD images are x86 only — no ARM builds available
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

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
      name  = "${var.project_name}-openroad"
      image = "${aws_ecr_repository.openroad.repository_url}:${var.openroad_image_tag}"

      mountPoints = [
        {
          sourceVolume  = "shared-data"
          containerPath = "/shared"
          readOnly      = false
        }
      ]

      environment = [
        {
          name  = "DESIGN_DIR"
          value = "/shared/designs"
        },
        {
          name  = "REPORTS_DIR"
          value = "/shared/reports"
        },
        {
          name  = "FLOW_HOME"
          value = "/OpenROAD-flow-scripts/flow"
        },
        {
          name  = "ENVIRONMENT"
          value = var.environment
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.openroad.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "openroad"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name = "${var.project_name}-openroad-task"
  }
}

# ---------------------------------------------------------------------------
# CloudWatch Log Group for OpenROAD
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "openroad" {
  name              = "/ecs/${var.project_name}-openroad"
  retention_in_days = 7

  tags = {
    Name = "${var.project_name}-openroad-logs"
  }
}

# ---------------------------------------------------------------------------
# OpenROAD ECS Service (set desired_count=0 to save costs when not training)
# ---------------------------------------------------------------------------

resource "aws_ecs_service" "openroad" {
  name            = "${var.project_name}-openroad"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.openroad.arn
  desired_count   = 0
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  force_new_deployment = true

  depends_on = [
    aws_efs_mount_target.shared,
  ]

  tags = {
    Name = "${var.project_name}-openroad-service"
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "openroad_ecr_url" {
  description = "ECR repository URL for OpenROAD image"
  value       = aws_ecr_repository.openroad.repository_url
}

output "openroad_service_name" {
  description = "ECS service name for OpenROAD runner"
  value       = aws_ecs_service.openroad.name
}

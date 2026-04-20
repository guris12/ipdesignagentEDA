# =============================================================================
# ecr.tf — Elastic Container Registry
# =============================================================================
# Estimated monthly cost:
#   Storage: $0.10/GB-month (a typical Python AI image is ~2-3 GB)
#   Data transfer: $0.09/GB outbound (intra-region ECS pulls are free)
# =============================================================================

resource "aws_ecr_repository" "app" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"
  force_delete         = true # Allow terraform destroy to clean up images

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "${var.project_name}-ecr"
  }
}

# Lifecycle policy — keep only the last 10 images to control storage costs
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep only last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

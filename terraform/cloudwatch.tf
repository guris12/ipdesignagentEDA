# =============================================================================
# cloudwatch.tf — Log Groups, Dashboard with Key Metrics
# =============================================================================
# Estimated monthly cost:
#   Log ingestion:  $0.57/GB
#   Log storage:    $0.03/GB-month
#   Dashboard:      $3.00/month per dashboard
#   Total:          ~$4-6/mo for a demo workload
# =============================================================================

# ---------------------------------------------------------------------------
# Log Group for ECS container output
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 14 # Keep 2 weeks of logs; increase for production

  tags = {
    Name = "${var.project_name}-ecs-logs"
  }
}

# ---------------------------------------------------------------------------
# CloudWatch Dashboard — single pane of glass for the application
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      # --- Row 1: ECS Metrics ---
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ECS CPU Utilization (%)"
          region = var.aws_region
          metrics = [
            [
              "AWS/ECS", "CPUUtilization",
              "ClusterName", aws_ecs_cluster.main.name,
              "ServiceName", var.project_name,
              { stat = "Average", period = 300 }
            ]
          ]
          view = "timeSeries"
          yAxis = {
            left = { min = 0, max = 100 }
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ECS Memory Utilization (%)"
          region = var.aws_region
          metrics = [
            [
              "AWS/ECS", "MemoryUtilization",
              "ClusterName", aws_ecs_cluster.main.name,
              "ServiceName", var.project_name,
              { stat = "Average", period = 300 }
            ]
          ]
          view = "timeSeries"
          yAxis = {
            left = { min = 0, max = 100 }
          }
        }
      },

      # --- Row 2: ALB Metrics ---
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "ALB Request Count"
          region = var.aws_region
          metrics = [
            [
              "AWS/ApplicationELB", "RequestCount",
              "LoadBalancer", aws_lb.main.arn_suffix,
              { stat = "Sum", period = 300 }
            ]
          ]
          view = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "ALB Target Response Time (seconds)"
          region = var.aws_region
          metrics = [
            [
              "AWS/ApplicationELB", "TargetResponseTime",
              "LoadBalancer", aws_lb.main.arn_suffix,
              { stat = "Average", period = 300 }
            ],
            [
              "AWS/ApplicationELB", "TargetResponseTime",
              "LoadBalancer", aws_lb.main.arn_suffix,
              { stat = "p99", period = 300 }
            ]
          ]
          view = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "ALB HTTP 5xx Errors"
          region = var.aws_region
          metrics = [
            [
              "AWS/ApplicationELB", "HTTPCode_Target_5XX_Count",
              "LoadBalancer", aws_lb.main.arn_suffix,
              { stat = "Sum", period = 300 }
            ],
            [
              "AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count",
              "LoadBalancer", aws_lb.main.arn_suffix,
              { stat = "Sum", period = 300 }
            ]
          ]
          view = "timeSeries"
        }
      },

      # --- Row 3: RDS Metrics ---
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 8
        height = 6
        properties = {
          title  = "RDS Database Connections"
          region = var.aws_region
          metrics = [
            [
              "AWS/RDS", "DatabaseConnections",
              "DBInstanceIdentifier", aws_db_instance.main.identifier,
              { stat = "Average", period = 300 }
            ]
          ]
          view = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 12
        width  = 8
        height = 6
        properties = {
          title  = "RDS CPU Utilization (%)"
          region = var.aws_region
          metrics = [
            [
              "AWS/RDS", "CPUUtilization",
              "DBInstanceIdentifier", aws_db_instance.main.identifier,
              { stat = "Average", period = 300 }
            ]
          ]
          view = "timeSeries"
          yAxis = {
            left = { min = 0, max = 100 }
          }
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 12
        width  = 8
        height = 6
        properties = {
          title  = "RDS Free Storage (bytes)"
          region = var.aws_region
          metrics = [
            [
              "AWS/RDS", "FreeStorageSpace",
              "DBInstanceIdentifier", aws_db_instance.main.identifier,
              { stat = "Average", period = 300 }
            ]
          ]
          view = "timeSeries"
        }
      },

      # --- Row 4: ECS Task Count + Logs ---
      {
        type   = "metric"
        x      = 0
        y      = 18
        width  = 12
        height = 6
        properties = {
          title  = "ECS Running Task Count"
          region = var.aws_region
          metrics = [
            [
              "ECS/ContainerInsights", "RunningTaskCount",
              "ClusterName", aws_ecs_cluster.main.name,
              "ServiceName", var.project_name,
              { stat = "Average", period = 300 }
            ]
          ]
          view = "timeSeries"
        }
      },
      {
        type   = "log"
        x      = 12
        y      = 18
        width  = 12
        height = 6
        properties = {
          title  = "Recent Application Logs"
          region = var.aws_region
          query  = "SOURCE '${aws_cloudwatch_log_group.ecs.name}' | fields @timestamp, @message | sort @timestamp desc | limit 50"
          view   = "table"
        }
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# CloudWatch Alarms (optional but good practice)
# ---------------------------------------------------------------------------

# Alert if CPU > 80% for 5 minutes
resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  alarm_name          = "${var.project_name}-ecs-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "ECS CPU utilization is above 80% for 10 minutes"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = var.project_name
  }

  # Uncomment to send to SNS topic for email/Slack notifications
  # alarm_actions = [aws_sns_topic.alerts.arn]

  tags = {
    Name = "${var.project_name}-cpu-alarm"
  }
}

# Alert if no healthy targets behind the ALB
resource "aws_cloudwatch_metric_alarm" "alb_unhealthy" {
  alarm_name          = "${var.project_name}-alb-unhealthy-targets"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  alarm_description   = "No healthy targets behind the ALB"

  dimensions = {
    TargetGroup  = aws_lb_target_group.streamlit.arn_suffix
    LoadBalancer = aws_lb.main.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-unhealthy-alarm"
  }
}

# Alert if RDS free storage drops below 2GB
resource "aws_cloudwatch_metric_alarm" "rds_storage_low" {
  alarm_name          = "${var.project_name}-rds-storage-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 2000000000 # 2 GB in bytes
  alarm_description   = "RDS free storage is below 2 GB"

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.identifier
  }

  tags = {
    Name = "${var.project_name}-storage-alarm"
  }
}

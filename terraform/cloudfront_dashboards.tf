# CloudFront Distribution for Dashboard Hosting
#
# Serves dashboard HTML files from S3 with global CDN caching
# Provides HTTPS access and fast load times worldwide
#
# Cost: ~$0.50-2.00/month (low traffic)

# Origin Access Identity for CloudFront → S3
resource "aws_cloudfront_origin_access_identity" "dashboards" {
  comment = "OAI for IP Design Agent dashboards"
}

# CloudFront Distribution
resource "aws_cloudfront_distribution" "dashboards" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "IP Design Agent - Timing Dashboards CDN"
  price_class         = "PriceClass_100"  # Use only North America and Europe

  # Origin: S3 bucket
  origin {
    domain_name = aws_s3_bucket.dashboards.bucket_regional_domain_name
    origin_id   = "S3-dashboards"

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.dashboards.cloudfront_access_identity_path
    }
  }

  # Default cache behavior
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-dashboards"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    # Cache settings optimized for HTML
    min_ttl     = 0
    default_ttl = 3600    # 1 hour
    max_ttl     = 86400   # 24 hours

    forwarded_values {
      query_string = false

      cookies {
        forward = "none"
      }

      headers = [
        "Origin",
        "Access-Control-Request-Headers",
        "Access-Control-Request-Method"
      ]
    }
  }

  # Cache behavior for HTML files (shorter cache)
  ordered_cache_behavior {
    path_pattern           = "*.html"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "S3-dashboards"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    min_ttl     = 0
    default_ttl = 300     # 5 minutes (dashboards update frequently)
    max_ttl     = 3600    # 1 hour

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  # Restrictions
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # SSL Certificate
  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  # Custom error responses
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/index.html"
    error_caching_min_ttl = 300
  }

  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/index.html"
    error_caching_min_ttl = 300
  }

  tags = {
    Name        = "IP Design Agent Dashboards CDN"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}

# CloudWatch alarm for CloudFront errors (optional but good practice)
resource "aws_cloudwatch_metric_alarm" "cloudfront_errors" {
  alarm_name          = "${var.project_name}-cloudfront-errors-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "5xxErrorRate"
  namespace           = "AWS/CloudFront"
  period              = "300"
  statistic           = "Average"
  threshold           = "5"  # Alert if 5xx error rate > 5%
  alarm_description   = "This metric monitors CloudFront 5xx errors"
  treat_missing_data  = "notBreaching"

  dimensions = {
    DistributionId = aws_cloudfront_distribution.dashboards.id
  }

  tags = {
    Name        = "CloudFront Errors Alarm"
    Environment = var.environment
  }
}

# Outputs
output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID"
  value       = aws_cloudfront_distribution.dashboards.id
}

output "cloudfront_domain_name" {
  description = "CloudFront domain name"
  value       = aws_cloudfront_distribution.dashboards.domain_name
}

output "dashboard_url" {
  description = "Public URL for dashboards"
  value       = "https://${aws_cloudfront_distribution.dashboards.domain_name}"
}

output "sample_dashboard_url" {
  description = "Sample dashboard URL"
  value       = "https://${aws_cloudfront_distribution.dashboards.domain_name}/sample_timing_dashboard.html"
}

# Create a pretty output summary
output "dashboard_deployment_summary" {
  description = "Dashboard deployment summary"
  value = {
    cdn_url           = "https://${aws_cloudfront_distribution.dashboards.domain_name}"
    s3_bucket         = aws_s3_bucket.dashboards.id
    region            = var.aws_region
    sample_dashboard  = "https://${aws_cloudfront_distribution.dashboards.domain_name}/sample_timing_dashboard.html"
    index_page        = "https://${aws_cloudfront_distribution.dashboards.domain_name}/index.html"
  }
}

# =============================================================================
# dns.tf — ACM Certificate + Route53 Records for viongen.in
# =============================================================================
# Subdomains:
#   train.viongen.in  → Streamlit UI (port 8501)
#   api.viongen.in    → FastAPI (port 8001)
# =============================================================================

# ---------------------------------------------------------------------------
# ACM Certificate (eu-west-1 — for ALB)
# ---------------------------------------------------------------------------

resource "aws_acm_certificate" "main" {
  domain_name               = "*.${var.domain_name}"
  subject_alternative_names = [var.domain_name]
  validation_method         = "DNS"

  tags = {
    Name = "${var.project_name}-cert"
  }

  lifecycle {
    create_before_destroy = true
  }
}

# DNS validation records
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = var.route53_zone_id
}

resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

# ---------------------------------------------------------------------------
# Route53 Records — point subdomains to ALB
# ---------------------------------------------------------------------------

resource "aws_route53_record" "train" {
  zone_id = var.route53_zone_id
  name    = "train.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_record" "api" {
  zone_id = var.route53_zone_id
  name    = "api.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

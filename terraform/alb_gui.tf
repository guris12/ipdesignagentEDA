# =============================================================================
# alb_gui.tf — gui.viongen.in → ALB → OpenROAD noVNC on port 6080
# =============================================================================
# Students launch the OpenROAD GUI from the Lab tab; the iframe loads
# https://gui.viongen.in/vnc.html which terminates TLS at the ALB and
# forwards to the OpenROAD Fargate task on container port 6080 (websockify).
#
# Apply targets (first-time bring-up):
#   terraform apply \
#     -target=aws_lb_target_group.openroad_gui \
#     -target=aws_lb_listener_rule.gui_host \
#     -target=aws_security_group_rule.alb_to_openroad_gui \
#     -target=aws_route53_record.gui
# =============================================================================

# ---------------------------------------------------------------------------
# Target group — ALB → OpenROAD task :6080 (noVNC over HTTP)
# ---------------------------------------------------------------------------

resource "aws_lb_target_group" "openroad_gui" {
  name        = "${var.project_name}-gui-tg"
  port        = 6080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/vnc.html"
    protocol            = "HTTP"
    matcher             = "200-399"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  # noVNC uses long-lived websocket connections. Give them room.
  stickiness {
    type            = "lb_cookie"
    cookie_duration = 3600
    enabled         = true
  }

  deregistration_delay = 30

  tags = {
    Name = "${var.project_name}-gui-tg"
  }
}

# ---------------------------------------------------------------------------
# Listener rule — host gui.viongen.in matches first, routes to GUI TG
# ---------------------------------------------------------------------------

resource "aws_lb_listener_rule" "gui_host" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 50

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.openroad_gui.arn
  }

  condition {
    host_header {
      values = ["gui.${var.domain_name}"]
    }
  }

  tags = {
    Name = "${var.project_name}-gui-rule"
  }
}

# ---------------------------------------------------------------------------
# Security group — allow ALB → OpenROAD task on 6080
# The ecs_tasks SG already allows 8001/8501 from ALB; this adds 6080 only.
# ---------------------------------------------------------------------------

resource "aws_security_group_rule" "alb_to_openroad_gui" {
  type                     = "ingress"
  from_port                = 6080
  to_port                  = 6080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.ecs_tasks.id
  source_security_group_id = aws_security_group.alb.id
  description              = "ALB to OpenROAD noVNC port 6080 (gui.viongen.in)"
}

# ---------------------------------------------------------------------------
# Route53 — gui.viongen.in → ALB
# ---------------------------------------------------------------------------

resource "aws_route53_record" "gui" {
  zone_id = var.route53_zone_id
  name    = "gui.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

output "gui_url" {
  description = "Student-facing noVNC URL for the OpenROAD GUI"
  value       = "https://gui.${var.domain_name}/vnc.html?autoconnect=1&resize=scale"
}

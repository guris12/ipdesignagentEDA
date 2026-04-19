# Dashboard Deployment Guide — AWS S3 + CloudFront

**Complete step-by-step guide to deploy timing dashboards to AWS**

This guide covers both **quick static deployment** (S3 + CloudFront) and **full stack deployment** (ECS + API + Dashboards).

---

## Overview

### **What Gets Deployed:**

```
┌─────────────────────────────────────────────────────────────┐
│  CloudFront CDN (Global)                                    │
│  https://d1234567890.cloudfront.net                         │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  S3 Bucket (eu-west-1 Dublin)                               │
│  ip-design-agent-dashboards-prod                            │
│  ├── index.html                    ← Dashboard listing      │
│  ├── sample_timing_dashboard.html  ← Sample                 │
│  ├── gcd_sky130hd_dashboard.html   ← Real dashboards        │
│  └── ibex_sky130hd_dashboard.html                           │
└─────────────────────────────────────────────────────────────┘
```

**Cost:** ~$1-2/month for static dashboards

---

## Prerequisites

### **1. AWS Account**
- Sign up at https://aws.amazon.com
- Note your AWS Account ID

### **2. AWS CLI Installed**
```bash
# macOS
brew install awscli

# Verify
aws --version
```

### **3. AWS Credentials Configured**
```bash
# Configure AWS credentials
aws configure

# Enter:
# AWS Access Key ID: <your-key>
# AWS Secret Access Key: <your-secret>
# Default region: eu-west-1
# Default output format: json

# Verify
aws sts get-caller-identity
```

### **4. Terraform Installed**
```bash
# macOS
brew install terraform

# Verify
terraform version
```

### **5. Generate Sample Dashboard**
```bash
cd ~/Documents/JobhuntAI/ip-design-agent
python3 test_dashboard_standalone.py

# Creates: reports/sample_timing_dashboard.html
```

---

## Deployment Option 1: Static Dashboards (Quick)

**Time:** 15 minutes  
**Cost:** ~$1/month  
**Best for:** Interview demo, quick sharing

### **Step 1: Navigate to Terraform Directory**
```bash
cd ~/Documents/JobhuntAI/ip-design-agent-terraform
```

### **Step 2: Initialize Terraform**
```bash
terraform init

# You should see:
# Terraform has been successfully initialized!
```

### **Step 3: Review What Will Be Created**
```bash
terraform plan \
  -target=aws_s3_bucket.dashboards \
  -target=aws_cloudfront_distribution.dashboards

# Review output:
# + aws_s3_bucket.dashboards
# + aws_cloudfront_distribution.dashboards
# + aws_s3_object.sample_dashboard
# + aws_s3_object.dashboard_index
```

### **Step 4: Deploy Dashboard Hosting**
```bash
terraform apply \
  -target=aws_s3_bucket.dashboards \
  -target=aws_cloudfront_distribution.dashboards

# Type 'yes' when prompted

# Wait ~5-10 minutes for CloudFront distribution
```

### **Step 5: Get Your Dashboard URL**
```bash
terraform output dashboard_url
terraform output sample_dashboard_url

# Output:
# dashboard_url = "https://d1234567890.cloudfront.net"
# sample_dashboard_url = "https://d1234567890.cloudfront.net/sample_timing_dashboard.html"
```

### **Step 6: Test Access**
```bash
# Copy the URL and open in browser
DASHBOARD_URL=$(terraform output -raw sample_dashboard_url)
open $DASHBOARD_URL

# Or test with curl
curl -I $DASHBOARD_URL
# Should return: HTTP/2 200
```

### **Step 7: Upload New Dashboards**
```bash
# After generating new dashboards locally
cd ~/Documents/JobhuntAI/ip-design-agent

# Generate a dashboard
python3 demo_timing_dashboard.py --quick

# Upload to S3
aws s3 cp reports/gcd_sky130hd_dashboard.html \
  s3://ip-design-agent-dashboards-prod/ \
  --content-type "text/html" \
  --cache-control "public, max-age=300"

# Invalidate CloudFront cache (make it available immediately)
DISTRIBUTION_ID=$(terraform output -raw cloudfront_distribution_id)
aws cloudfront create-invalidation \
  --distribution-id $DISTRIBUTION_ID \
  --paths "/*"

# Wait ~1 minute, then access:
# https://d1234567890.cloudfront.net/gcd_sky130hd_dashboard.html
```

---

## Deployment Option 2: Full Stack (Complete System)

**Time:** 30-45 minutes  
**Cost:** ~$50-70/month  
**Best for:** Production demo, API access, dynamic generation

### **Architecture:**
```
User → ALB → ECS Fargate
              ├── FastAPI (port 8001)
              │   └── GET /dashboards/gcd/sky130hd → Generates HTML
              ├── Streamlit (port 8501)
              │   └── MCMM UI
              └── RDS PostgreSQL
                  └── pgvector (timing data)
                  
S3 + CloudFront
  └── Static dashboard hosting
```

### **Step 1: Review Variables**
```bash
cd ~/Documents/JobhuntAI/ip-design-agent-terraform

# Create terraform.tfvars
cat > terraform.tfvars <<EOF
project_name = "ip-design-agent"
environment  = "prod"
aws_region   = "eu-west-1"  # Dublin

# Database
db_password = "$(openssl rand -base64 32)"

# API
openai_api_key = "sk-..."  # Your OpenAI key
EOF
```

### **Step 2: Deploy Everything**
```bash
# Initialize
terraform init

# Plan (review what will be created)
terraform plan

# Apply (deploy to AWS)
terraform apply

# Type 'yes' when prompted
# Wait ~15-20 minutes for complete deployment
```

### **Step 3: Get Endpoints**
```bash
# Get all output URLs
terraform output

# Output includes:
# alb_url = "ip-design-agent-alb-123456.eu-west-1.elb.amazonaws.com"
# api_endpoint = "http://ip-design-agent-alb-123456.eu-west-1.elb.amazonaws.com:8001"
# streamlit_url = "http://ip-design-agent-alb-123456.eu-west-1.elb.amazonaws.com:8501"
# dashboard_url = "https://d1234567890.cloudfront.net"
# rds_endpoint = "ip-design-agent-db.xxx.eu-west-1.rds.amazonaws.com"
```

### **Step 4: Test API Endpoints**
```bash
API_URL=$(terraform output -raw api_endpoint)

# Health check
curl $API_URL/health

# List dashboards
curl $API_URL/dashboards

# Get specific dashboard
curl $API_URL/dashboards/gcd/sky130hd

# Get dashboard data (JSON)
curl $API_URL/dashboards/gcd/sky130hd/data
```

### **Step 5: Upload Dashboards to S3**
```bash
# Generate dashboard locally
cd ~/Documents/JobhuntAI/ip-design-agent
python3 demo_timing_dashboard.py --quick

# Upload via API
API_URL=$(terraform output -raw api_endpoint)
curl -X POST $API_URL/dashboards/gcd/sky130hd/upload

# Response:
# {
#   "success": true,
#   "url": "https://d1234567890.cloudfront.net/gcd_sky130hd_dashboard.html"
# }
```

---

## Environment Variables for API

The ECS task needs these environment variables (set via Secrets Manager):

```bash
# Required
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Optional
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_TRACING_V2=true
DASHBOARD_S3_BUCKET=ip-design-agent-dashboards-prod
CLOUDFRONT_DOMAIN=d1234567890.cloudfront.net
OPENROAD_PATH=/app/OpenROAD-flow-scripts
```

These are already configured in `terraform/secrets.tf`.

---

## Monitoring & Logs

### **CloudWatch Logs**
```bash
# View API logs
aws logs tail /ecs/ip-design-agent-api --follow

# View dashboard access logs
aws logs tail /aws/cloudfront/dashboards --follow
```

### **CloudWatch Dashboard**
```bash
# Get dashboard URL
terraform output cloudwatch_dashboard_url

# Open in browser
open "https://console.aws.amazon.com/cloudwatch/..."
```

**Widgets:**
- ECS task count
- API request rate
- CloudFront requests
- S3 upload rate
- RDS connections

### **Alarms**
Three CloudWatch alarms are configured:
1. **ECS Task Count = 0** — Alert if service is down
2. **API 5xx Errors > 5%** — Alert if API is failing
3. **CloudFront 5xx Errors > 5%** — Alert if CDN is failing

---

## Cost Breakdown

### **Static Dashboard Hosting (S3 + CloudFront):**
| Resource | Cost/Month |
|----------|-----------|
| S3 storage (10 MB) | $0.023/GB × 0.01 GB = $0.0002 |
| S3 requests (1000 GET) | $0.0004/request × 1000 = $0.40 |
| CloudFront data transfer (1 GB) | $0.085/GB × 1 GB = $0.09 |
| **Total** | **~$0.50-1.00** |

### **Full Stack (ECS + RDS + ALB + S3 + CloudFront):**
| Resource | Cost/Month |
|----------|-----------|
| ECS Fargate (0.25 vCPU, 0.5 GB) | ~$10 |
| NAT Gateway | ~$32 |
| RDS t3.micro (PostgreSQL) | ~$15 |
| ALB | ~$16 |
| S3 + CloudFront | ~$1 |
| **Total** | **~$74/month** |

**For 1 month (May 2026):** $74 is worth it for landing a principal role!

---

## Interview Demo Workflow

### **Preparation (Week Before):**
```bash
# 1. Deploy static dashboards
cd ~/Documents/JobhuntAI/ip-design-agent-terraform
terraform apply -target=module.dashboard_hosting

# 2. Generate 3-4 sample dashboards
cd ~/Documents/JobhuntAI/ip-design-agent
python3 demo_timing_dashboard.py --quick
python3 demo_timing_dashboard.py --design aes --pdk sky130hd --quick

# 3. Upload all dashboards
aws s3 sync reports/ s3://ip-design-agent-dashboards-prod/ \
  --exclude "*" --include "*.html" \
  --content-type "text/html" \
  --cache-control "public, max-age=300"

# 4. Get final URLs
terraform output dashboard_deployment_summary
```

### **During Interview:**

**Script:**
> "Let me show you how I validate timing closure improvements. I've deployed a dashboard system to AWS..."

*[Opens browser]*

> "Here's the live URL: https://d1234567890.cloudfront.net"

*[Shows index page with dashboard list]*

> "Each dashboard tracks 5 key parameters across multiple ECO iterations..."

*[Clicks on gcd dashboard]*

> "This chart shows WNS trending from -0.52ns baseline to +0.08ns after 2 ECO iterations. Violations dropped from 8 to 0. The system automatically detects convergence..."

*[Points to trend chart]*

> "The dashboard is deployed on S3 + CloudFront for fast global access. It's in the Dublin region — same as your office. The full system can also generate dashboards on-demand via the FastAPI endpoint..."

**Interviewer reaction:** 🤯 "This is production-grade!"

---

## Troubleshooting

### **Issue: CloudFront distribution creation takes forever**
**Solution:** CloudFront can take 15-30 minutes to fully propagate. Be patient.

```bash
# Check status
aws cloudfront get-distribution --id $(terraform output -raw cloudfront_distribution_id) \
  --query 'Distribution.Status'

# Should eventually return: "Deployed"
```

### **Issue: 403 Forbidden when accessing dashboard**
**Solution:** Check S3 bucket policy and OAI configuration.

```bash
# Verify OAI has access
aws s3api get-bucket-policy --bucket ip-design-agent-dashboards-prod

# Should see CloudFront OAI in the policy
```

### **Issue: Dashboard shows old content**
**Solution:** Invalidate CloudFront cache.

```bash
DISTRIBUTION_ID=$(terraform output -raw cloudfront_distribution_id)
aws cloudfront create-invalidation \
  --distribution-id $DISTRIBUTION_ID \
  --paths "/*"
```

### **Issue: Terraform state locked**
**Solution:** Force unlock (use with caution).

```bash
terraform force-unlock <lock-id>
```

### **Issue: ECS task fails to start**
**Solution:** Check CloudWatch logs.

```bash
aws logs tail /ecs/ip-design-agent-api --follow

# Common issues:
# - Missing environment variables
# - Database connection failed
# - OpenAI API key invalid
```

---

## Cleanup / Tear Down

### **Remove Static Dashboard Hosting:**
```bash
cd ~/Documents/JobhuntAI/ip-design-agent-terraform

terraform destroy \
  -target=aws_cloudfront_distribution.dashboards \
  -target=aws_s3_bucket.dashboards

# Type 'yes' to confirm
```

### **Remove Everything:**
```bash
cd ~/Documents/JobhuntAI/ip-design-agent-terraform

terraform destroy

# Type 'yes' to confirm
# Wait ~10-15 minutes for complete teardown
```

**Cost after teardown:** $0 (no ongoing charges)

---

## Next Steps

✅ **Phase 1 (Today):** Deploy static dashboards to S3 + CloudFront  
✅ **Phase 2 (This Week):** Test dashboard access, upload multiple designs  
✅ **Phase 3 (Next Week):** Deploy full stack (optional)  
✅ **Phase 4 (Before Interview):** Practice demo workflow  

---

## Files Created

```
ip-design-agent-terraform/
├── s3_dashboards.tf              ← S3 bucket for dashboard storage (NEW)
├── cloudfront_dashboards.tf      ← CDN distribution (NEW)
└── DASHBOARD_DEPLOYMENT.md       ← This file (NEW)

ip-design-agent/src/ip_agent/
└── api.py                        ← Added /dashboards endpoints (UPDATED)
```

---

## Summary

**What You Can Now Do:**

✅ Deploy timing dashboards to AWS S3 + CloudFront  
✅ Share live URLs: `https://d1234567890.cloudfront.net/sample_timing_dashboard.html`  
✅ Generate dashboards on-demand via API  
✅ Upload new dashboards automatically  
✅ Monitor access via CloudWatch  
✅ Demo live during interview  

**Cost:** $0.50-1.00/month (static) or $74/month (full stack)  
**Time to deploy:** 15 minutes (static) or 45 minutes (full)  
**Interview impact:** 🚀🚀🚀 **"This is deployed and LIVE!"**

---

**Ready to deploy?** Follow **Deployment Option 1** for the quick win! 💪

#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Build, push to ECR, and deploy to ECS Fargate
# =============================================================================
# Usage:
#   ./deploy.sh                  # Build and deploy with tag "latest"
#   ./deploy.sh v1.2.3           # Build and deploy with a specific tag
#   ./deploy.sh --skip-build     # Just trigger ECS redeployment (no Docker build)
#
# Prerequisites:
#   - AWS CLI v2 configured with appropriate credentials
#   - Docker running locally
#   - Terraform has been applied (terraform apply)
#   - You are in the ip-design-agent project root (where the Dockerfile is)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — pulled from Terraform outputs
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="${SCRIPT_DIR}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()   { echo -e "${BLUE}[deploy]${NC} $*"; }
ok()    { echo -e "${GREEN}[deploy]${NC} $*"; }
warn()  { echo -e "${YELLOW}[deploy]${NC} $*"; }
error() { echo -e "${RED}[deploy]${NC} $*" >&2; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

IMAGE_TAG="${1:-latest}"
SKIP_BUILD=false

if [[ "${1:-}" == "--skip-build" ]]; then
    SKIP_BUILD=true
    IMAGE_TAG="${2:-latest}"
fi

# ---------------------------------------------------------------------------
# Read Terraform outputs
# ---------------------------------------------------------------------------

log "Reading Terraform outputs from ${TF_DIR}..."

if ! cd "${TF_DIR}" || ! terraform output -json > /dev/null 2>&1; then
    error "Failed to read Terraform outputs. Have you run 'terraform apply'?"
    exit 1
fi

ECR_REPO_URL=$(terraform output -raw ecr_repository_url)
AWS_REGION=$(terraform output -json | python3 -c "
import json, sys, re
# Parse region from ECR URL: account.dkr.ecr.REGION.amazonaws.com/repo
url = json.load(sys.stdin).get('ecr_repository_url', {}).get('value', '')
match = re.search(r'ecr\.([^.]+)\.amazonaws', url)
print(match.group(1) if match else 'eu-west-1')
" 2>/dev/null || echo "eu-west-1")
ECS_CLUSTER=$(terraform output -raw ecs_cluster_name)
ECS_SERVICE=$(terraform output -raw ecs_service_name)
AWS_ACCOUNT_ID=$(echo "${ECR_REPO_URL}" | cut -d'.' -f1)

log "ECR Repository: ${ECR_REPO_URL}"
log "ECS Cluster:    ${ECS_CLUSTER}"
log "ECS Service:    ${ECS_SERVICE}"
log "AWS Region:     ${AWS_REGION}"
log "Image Tag:      ${IMAGE_TAG}"

# ---------------------------------------------------------------------------
# Step 1: Authenticate Docker with ECR
# ---------------------------------------------------------------------------

log "Authenticating Docker with ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login --username AWS --password-stdin \
      "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ok "ECR authentication successful"

# ---------------------------------------------------------------------------
# Step 2: Build and push Docker image
# ---------------------------------------------------------------------------

if [[ "${SKIP_BUILD}" == "false" ]]; then
    # Navigate to the application directory (one level up from terraform)
    APP_DIR="$(dirname "${SCRIPT_DIR}")/ip-design-agent"

    if [[ ! -f "${APP_DIR}/Dockerfile" ]]; then
        # Try current directory or parent
        if [[ -f "./Dockerfile" ]]; then
            APP_DIR="."
        elif [[ -f "../Dockerfile" ]]; then
            APP_DIR=".."
        else
            error "Cannot find Dockerfile. Expected at: ${APP_DIR}/Dockerfile"
            error "Run this script from the ip-design-agent project root, or ensure"
            error "the project is at: $(dirname "${SCRIPT_DIR}")/ip-design-agent/"
            exit 1
        fi
    fi

    log "Building Docker image from ${APP_DIR}..."
    docker build \
        --platform linux/amd64 \
        -t "${ECR_REPO_URL}:${IMAGE_TAG}" \
        -t "${ECR_REPO_URL}:$(git -C "${APP_DIR}" rev-parse --short HEAD 2>/dev/null || echo 'nogit')" \
        "${APP_DIR}"
    ok "Docker build complete"

    log "Pushing image to ECR..."
    docker push "${ECR_REPO_URL}:${IMAGE_TAG}"

    # Also push the git-sha tagged version
    GIT_TAG=$(git -C "${APP_DIR}" rev-parse --short HEAD 2>/dev/null || echo "")
    if [[ -n "${GIT_TAG}" ]]; then
        docker push "${ECR_REPO_URL}:${GIT_TAG}"
        ok "Pushed images: ${IMAGE_TAG}, ${GIT_TAG}"
    else
        ok "Pushed image: ${IMAGE_TAG}"
    fi
else
    warn "Skipping Docker build (--skip-build)"
fi

# ---------------------------------------------------------------------------
# Step 3: Force new deployment on ECS
# ---------------------------------------------------------------------------

log "Triggering ECS service update (force new deployment)..."
aws ecs update-service \
    --cluster "${ECS_CLUSTER}" \
    --service "${ECS_SERVICE}" \
    --force-new-deployment \
    --region "${AWS_REGION}" \
    > /dev/null

ok "ECS deployment triggered"

# ---------------------------------------------------------------------------
# Step 4: Wait for deployment to stabilize
# ---------------------------------------------------------------------------

log "Waiting for ECS service to stabilize (this may take 2-5 minutes)..."
if aws ecs wait services-stable \
    --cluster "${ECS_CLUSTER}" \
    --services "${ECS_SERVICE}" \
    --region "${AWS_REGION}" 2>/dev/null; then
    ok "Deployment complete and stable!"
else
    warn "Timed out waiting for stability. Check the AWS console for status."
    warn "Dashboard: $(terraform output -raw cloudwatch_dashboard_url 2>/dev/null || echo 'N/A')"
fi

# ---------------------------------------------------------------------------
# Done — print access URLs
# ---------------------------------------------------------------------------

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN} Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Streamlit UI:  ${BLUE}$(terraform output -raw streamlit_url 2>/dev/null)${NC}"
echo -e "FastAPI Docs:  ${BLUE}$(terraform output -raw api_url 2>/dev/null)${NC}"
echo -e "Dashboard:     ${BLUE}$(terraform output -raw cloudwatch_dashboard_url 2>/dev/null)${NC}"
echo -e "Logs:          ${BLUE}$(terraform output -raw cloudwatch_log_group 2>/dev/null)${NC}"
echo ""

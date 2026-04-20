#!/bin/bash
set -e

ECR="710387906612.dkr.ecr.eu-west-1.amazonaws.com"
IMAGE="$ECR/ip-design-agent:latest"
CLUSTER="ip-design-agent-cluster"
SERVICE="ip-design-agent"
REGION="eu-west-1"

echo "=== [1/5] Changing to project directory ==="
cd ~/Documents/JobhuntAI/ip-design-agent

echo "=== [2/5] Logging into ECR ==="
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ECR
echo "ECR login successful"

echo "=== [3/5] Building Docker image (linux/amd64) ==="
docker build --platform linux/amd64 -t $IMAGE .
echo "Build complete"

echo "=== [4/5] Pushing image to ECR ==="
docker push $IMAGE
echo "Push complete"

echo "=== [5/6] Forcing new ECS deployment ==="
aws ecs update-service --cluster $CLUSTER --service $SERVICE --force-new-deployment --region $REGION
echo "ECS deployment triggered — waiting 60s for container to start..."
sleep 60

echo "=== [6/6] Running ingest inside ECS container ==="
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER --service-name $SERVICE --region $REGION --query 'taskArns[0]' --output text)
echo "Running ingest on task: $TASK_ARN"
aws ecs execute-command \
  --cluster $CLUSTER \
  --task $TASK_ARN \
  --container ip-design-agent \
  --command "python -m ip_agent.ingest" \
  --interactive \
  --region $REGION
echo "Ingest complete"

echo ""
echo "=== DONE ==="
echo "API:       https://api.viongen.in/health"
echo "UI:        https://train.viongen.in"
echo "Dashboard: https://d15ismshdmx2su.cloudfront.net"
echo ""
echo "Test with:"
echo "  curl -s -X POST https://api.viongen.in/query -H 'Content-Type: application/json' -d '{\"question\": \"show violated paths with negative slack\"}' | python3 -m json.tool"

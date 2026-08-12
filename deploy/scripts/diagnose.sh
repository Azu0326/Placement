#!/bin/sh
# Print Scrapos production diagnostics after a failed deploy/verify.

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

log "Service events"
aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_WEB_SERVICE" \
    --query 'services[0].events[0:8].[createdAt,message]' --output table || true

log "Running tasks"
TASKS=$(aws ecs list-tasks --cluster "$ECS_CLUSTER" --service-name "$ECS_WEB_SERVICE" \
    --desired-status RUNNING --query 'taskArns' --output text)
if [ -n "$TASKS" ] && [ "$TASKS" != "None" ]; then
    aws ecs describe-tasks --cluster "$ECS_CLUSTER" --tasks $TASKS \
        --query 'tasks[*].{arn:taskArn,last:lastStatus,health:healthStatus,stopped:stoppedReason}' \
        --output table || true
fi

if [ -n "${TARGET_GROUP_ARN:-}" ]; then
    log "Target health"
    aws elbv2 describe-target-health --target-group-arn "$TARGET_GROUP_ARN" --output table || true
fi

log "Recent logs from $WEB_LOG_GROUP"
aws logs tail "$WEB_LOG_GROUP" --since 30m --format short 2>/dev/null | tail -n 80 || true

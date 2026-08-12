#!/bin/sh
# Deploy the Scrapos web service onto the immutable image for this commit.

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

ROLLBACK_FILE="${ROLLBACK_FILE:-$REPO_ROOT/rollback-state.env}"

current_task_def() {
    aws ecs describe-services \
        --cluster "$ECS_CLUSTER" \
        --services "$1" \
        --query 'services[0].taskDefinition' \
        --output text 2>/dev/null || printf 'none'
}

log "Recording current revision for rollback"
PREVIOUS_WEB=$(current_task_def "$ECS_WEB_SERVICE")
{
    printf 'PREVIOUS_WEB_TASK_DEFINITION=%s\n' "$PREVIOUS_WEB"
} >"$ROLLBACK_FILE"
cat "$ROLLBACK_FILE"

WEB_TASK_DEF=$("$SCRIPT_DIR/register-task-definition.sh" web)

log "Updating $ECS_WEB_SERVICE to $WEB_TASK_DEF"
aws ecs update-service \
    --cluster "$ECS_CLUSTER" \
    --service "$ECS_WEB_SERVICE" \
    --task-definition "$WEB_TASK_DEF" \
    --health-check-grace-period-seconds 60 \
    >/dev/null

log "Waiting for $ECS_WEB_SERVICE to reach a steady state (up to 10 minutes)"
if ! aws ecs wait services-stable \
    --cluster "$ECS_CLUSTER" \
    --services "$ECS_WEB_SERVICE"; then

    log "Service did not stabilise. Diagnostics follow."
    "$SCRIPT_DIR/diagnose.sh" || true
    fail "Deployment failed to stabilise. Roll back with deploy/scripts/rollback.sh"
fi

{
    printf 'WEB_TASK_DEFINITION=%s\n' "$WEB_TASK_DEF"
    printf 'IMAGE_URI=%s\n' "$(image_uri)"
} >>"$ROLLBACK_FILE"

ok "Service is stable"
ok "web: $WEB_TASK_DEF"

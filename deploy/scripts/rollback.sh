#!/bin/sh
# Roll Scrapos web back to the previous task definition revision.

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

ROLLBACK_FILE="${ROLLBACK_FILE:-$REPO_ROOT/rollback-state.env}"
[ -f "$ROLLBACK_FILE" ] || fail "Missing $ROLLBACK_FILE from a prior deploy_production job"

# shellcheck disable=SC1090
. "$ROLLBACK_FILE"

require_var PREVIOUS_WEB_TASK_DEFINITION "rollback-state.env has no PREVIOUS_WEB_TASK_DEFINITION"

if [ "$PREVIOUS_WEB_TASK_DEFINITION" = "none" ] || [ -z "$PREVIOUS_WEB_TASK_DEFINITION" ]; then
    fail "No previous web task definition recorded"
fi

log "Rolling $ECS_WEB_SERVICE back to $PREVIOUS_WEB_TASK_DEFINITION"
aws ecs update-service \
    --cluster "$ECS_CLUSTER" \
    --service "$ECS_WEB_SERVICE" \
    --task-definition "$PREVIOUS_WEB_TASK_DEFINITION" \
    >/dev/null

aws ecs wait services-stable --cluster "$ECS_CLUSTER" --services "$ECS_WEB_SERVICE"
ok "Rolled back to $PREVIOUS_WEB_TASK_DEFINITION"

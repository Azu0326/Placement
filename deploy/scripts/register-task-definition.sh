#!/bin/sh
# Render and register the Scrapos web task definition.
#
#   register-task-definition.sh web
#
# Prints the registered task-definition ARN on stdout.

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

KIND="${1:-}"
case "$KIND" in
web) ;;
*) fail "Usage: $0 web" ;;
esac

if [ "${RENDER_ONLY:-0}" = "1" ]; then
    DJANGO_SECRET_ARN="${DJANGO_SECRET_ARN:-arn:aws:secretsmanager:$AWS_DEFAULT_REGION:000000000000:secret:render-check}"
    COGNITO_SECRET_ARN="${COGNITO_SECRET_ARN:-arn:aws:secretsmanager:$AWS_DEFAULT_REGION:000000000000:secret:render-check-cognito}"
    IMAGE_URI="${IMAGE_URI:-render-check:latest}"
else
    require_var DJANGO_SECRET_ARN "Set the ARN of the Secrets Manager secret holding secret_key."
    COGNITO_SECRET_ARN=$(resolve_cognito_secret_arn)
fi

IMAGE=$(image_uri)
TEMPLATE="$ECS_DIR/${KIND}-task-definition.json"
RENDERED="$ECS_DIR/${KIND}-task-definition.rendered.json"

[ -f "$TEMPLATE" ] || fail "Template not found: $TEMPLATE"

log "Rendering $KIND task definition for image $IMAGE" >&2

sed \
    -e "s|__IMAGE__|${IMAGE}|g" \
    -e "s|__WEB_FAMILY__|${ECS_WEB_TASK_DEFINITION}|g" \
    -e "s|__TASK_ROLE_ARN__|${TASK_ROLE_ARN}|g" \
    -e "s|__EXECUTION_ROLE_ARN__|${EXECUTION_ROLE_ARN}|g" \
    -e "s|__WEB_LOG_GROUP__|${WEB_LOG_GROUP}|g" \
    -e "s|__AWS_REGION__|${AWS_DEFAULT_REGION}|g" \
    -e "s|__PRODUCTION_DOMAIN__|${PRODUCTION_DOMAIN}|g" \
    -e "s|__DJANGO_SECRET_ARN__|${DJANGO_SECRET_ARN}|g" \
    -e "s|__COGNITO_SECRET_ARN__|${COGNITO_SECRET_ARN}|g" \
    -e "s|__COGNITO_USER_POOL_ID__|${COGNITO_USER_POOL_ID}|g" \
    -e "s|__COGNITO_DOMAIN__|${COGNITO_DOMAIN}|g" \
    -e "s|__BOOTSTRAP_ADMIN_ENABLED__|${BOOTSTRAP_ADMIN_ENABLED}|g" \
    -e "s|__WEB_MEMORY_RESERVATION__|${WEB_MEMORY_RESERVATION}|g" \
    "$TEMPLATE" >"$RENDERED"

[ -n "$PYTHON" ] || fail "No python interpreter found; required to validate rendered JSON."
"$PYTHON" - "$RENDERED" <<'PY'
import json
import re
import sys

path = sys.argv[1]
with open(path) as handle:
    data = json.load(handle)

data.pop("_comment", None)

leftover = sorted(set(re.findall(r"__[A-Z0-9_]+__", json.dumps(data))))
if leftover:
    sys.exit(f"Unsubstituted placeholders remain: {leftover}")

for key in ("family", "networkMode", "taskRoleArn", "executionRoleArn", "containerDefinitions"):
    if not data.get(key):
        sys.exit(f"Rendered task definition is missing {key}")

container = data["containerDefinitions"][0]
for key in ("name", "image", "memoryReservation", "logConfiguration"):
    if not container.get(key):
        sys.exit(f"Container definition is missing {key}")

for secret in container.get("secrets", []):
    if not secret.get("valueFrom", "").startswith("arn:aws:"):
        sys.exit(f"Secret {secret.get('name')} does not reference an ARN")

with open(path, "w") as handle:
    json.dump(data, handle, indent=2)
PY

log "Validated rendered JSON" >&2

if [ "${RENDER_ONLY:-0}" = "1" ]; then
    ok "Render check passed for $KIND (nothing registered)" >&2
    exit 0
fi

ARN=$(aws ecs register-task-definition \
    --cli-input-json "file://$RENDERED" \
    --query 'taskDefinition.taskDefinitionArn' \
    --output text)

ok "Registered $ARN" >&2
printf '%s\n' "$ARN"

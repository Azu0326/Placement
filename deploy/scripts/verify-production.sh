#!/bin/sh
# Verify a Scrapos production deployment.

set -eu

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/common.sh"

FAILURES=0
check_failed() {
    printf '✗ %s\n' "$*" >&2
    FAILURES=$((FAILURES + 1))
}

log "Checking ECS service counts and rollout state"
DESIRED=$(aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_WEB_SERVICE" \
    --query 'services[0].desiredCount' --output text)
RUNNING=$(aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_WEB_SERVICE" \
    --query 'services[0].runningCount' --output text)
ROLLOUT=$(aws ecs describe-services --cluster "$ECS_CLUSTER" --services "$ECS_WEB_SERVICE" \
    --query 'services[0].deployments[0].rolloutState' --output text)

if [ "$DESIRED" = "$RUNNING" ] && [ "$RUNNING" != "0" ]; then
    ok "$ECS_WEB_SERVICE running $RUNNING/$DESIRED"
else
    check_failed "$ECS_WEB_SERVICE running $RUNNING/$DESIRED"
fi

case "$ROLLOUT" in
COMPLETED | None) ok "$ECS_WEB_SERVICE rollout state $ROLLOUT" ;;
*) check_failed "$ECS_WEB_SERVICE rollout state is $ROLLOUT" ;;
esac

if [ -n "${TARGET_GROUP_ARN:-}" ]; then
    log "Checking ALB target health"
    UNHEALTHY=$(aws elbv2 describe-target-health --target-group-arn "$TARGET_GROUP_ARN" \
        --query "length(TargetHealthDescriptions[?TargetHealth.State!='healthy'])" --output text)
    HEALTHY=$(aws elbv2 describe-target-health --target-group-arn "$TARGET_GROUP_ARN" \
        --query "length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])" --output text)

    if [ "$HEALTHY" -ge 1 ] && [ "$UNHEALTHY" -eq 0 ]; then
        ok "$HEALTHY healthy target(s), 0 unhealthy"
    else
        check_failed "$HEALTHY healthy / $UNHEALTHY unhealthy targets"
    fi
else
    log "TARGET_GROUP_ARN not set; skipping ALB target health check"
fi

HEALTH_URL="${PRODUCTION_HEALTHCHECK_URL:-https://${PRODUCTION_DOMAIN}/healthz}"
log "Checking $HEALTH_URL"
STATUS=$(curl -s -o /tmp/healthz.out -w '%{http_code}' --max-time 20 "$HEALTH_URL" || printf '000')
if [ "$STATUS" = "200" ]; then
    ok "healthz returned 200: $(cat /tmp/healthz.out)"
else
    check_failed "healthz returned HTTP $STATUS"
fi

LOGIN_URL="https://${PRODUCTION_DOMAIN}/login/"
log "Checking $LOGIN_URL"
LOGIN_STATUS=$(curl -s -o /tmp/login.out -w '%{http_code}' --max-time 30 "$LOGIN_URL" || printf '000')
if [ "$LOGIN_STATUS" = "200" ]; then
    ok "login page returned 200"
else
    check_failed "login page returned HTTP $LOGIN_STATUS"
fi

if grep -q 'name="csrfmiddlewaretoken"' /tmp/login.out 2>/dev/null; then
    ok "login form is CSRF protected"
else
    check_failed "login page has no CSRF token"
fi

# The application is closed by default: an unauthenticated request to any
# application page must redirect to the login screen, never render it.
HOME_URL="https://${PRODUCTION_DOMAIN}/"
log "Checking $HOME_URL redirects when unauthenticated"
HOME_STATUS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$HOME_URL" || printf '000')
if [ "$HOME_STATUS" = "302" ]; then
    ok "unauthenticated home redirects (HTTP 302)"
else
    check_failed "unauthenticated home returned HTTP $HOME_STATUS, expected 302"
fi

DASHBOARD_URL="https://${PRODUCTION_DOMAIN}/dashboard/"
log "Checking $DASHBOARD_URL redirects when unauthenticated"
DASH_STATUS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$DASHBOARD_URL" || printf '000')
if [ "$DASH_STATUS" = "302" ]; then
    ok "unauthenticated dashboard redirects (HTTP 302)"
else
    check_failed "unauthenticated dashboard returned HTTP $DASH_STATUS, expected 302"
fi

# The classic Django admin must not be reachable as the product interface.
ADMIN_STATUS=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://${PRODUCTION_DOMAIN}/admin/" || printf '000')
if [ "$ADMIN_STATUS" = "404" ] || [ "$ADMIN_STATUS" = "302" ]; then
    ok "classic Django admin is not served (HTTP $ADMIN_STATUS)"
else
    check_failed "/admin/ returned HTTP $ADMIN_STATUS; the Django admin must not be exposed"
fi

log "Confirming CloudWatch log group is receiving events"
STREAMS=$(aws logs describe-log-streams --log-group-name "$WEB_LOG_GROUP" \
    --order-by LastEventTime --descending --max-items 1 \
    --query 'length(logStreams)' --output text 2>/dev/null || printf '0')
if [ "$STREAMS" != "0" ] && [ "$STREAMS" != "None" ]; then
    ok "$WEB_LOG_GROUP has log streams"
else
    check_failed "$WEB_LOG_GROUP has no log streams"
fi

if [ "$FAILURES" -ne 0 ]; then
    printf '\n%s verification check(s) failed. Diagnostics:\n' "$FAILURES" >&2
    "$SCRIPT_DIR/diagnose.sh" || true
    exit 1
fi

ok "All production verification checks passed"

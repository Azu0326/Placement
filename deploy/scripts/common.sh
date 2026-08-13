#!/bin/sh
# Shared configuration for Scrapos deployment scripts.
# Sourced, not executed. POSIX sh for GitLab alpine/aws-cli jobs.

set -eu

AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-southeast-2}"
export AWS_DEFAULT_REGION

ECS_CLUSTER="${ECS_CLUSTER:-outvier-ecs-cluster-production}"

ECR_REPOSITORY="${ECR_REPOSITORY:-738765516909.dkr.ecr.ap-southeast-2.amazonaws.com/dncouncil}"
ECR_IMAGE_TAG="${ECR_IMAGE_TAG:-scrapos}"

ECS_WEB_SERVICE="${ECS_WEB_SERVICE:-outvier-scrapos-production}"
ECS_WEB_TASK_DEFINITION="${ECS_WEB_TASK_DEFINITION:-outvier-scrapos-production}"

WEB_LOG_GROUP="${WEB_LOG_GROUP:-/ecs/outvier-scrapos-production}"

EXECUTION_ROLE_ARN="${EXECUTION_ROLE_ARN:-arn:aws:iam::738765516909:role/outvier-ecs-execution-role-production}"
TASK_ROLE_ARN="${TASK_ROLE_ARN:-arn:aws:iam::738765516909:role/outvier-scrapos-task-production}"

PRODUCTION_DOMAIN="${PRODUCTION_DOMAIN:-scrapos.dncouncil.org}"
TARGET_GROUP_ARN="${TARGET_GROUP_ARN:-}"

DJANGO_SECRET_ARN="${DJANGO_SECRET_ARN:-}"

# Cognito. The user pool and app client are owned by Terraform in
# outvier-infrastructure (modules/cognito). COGNITO_SECRET_ARN is resolved from
# the secret name at deploy time when it is not supplied as a CI variable —
# Secrets Manager ARNs carry a random suffix, so they cannot be hardcoded.
COGNITO_USER_POOL_ID="${COGNITO_USER_POOL_ID:-ap-southeast-2_8MQhnosSO}"
COGNITO_DOMAIN="${COGNITO_DOMAIN:-auth.dncouncil.org}"
COGNITO_SECRET_NAME="${COGNITO_SECRET_NAME:-outvier-scrapos-cognito-production}"
COGNITO_SECRET_ARN="${COGNITO_SECRET_ARN:-}"

# The bootstrap superadmin is a development/recovery mechanism. Set this to
# false once Cognito administration is stable — see docs/authentication.md.
BOOTSTRAP_ADMIN_ENABLED="${BOOTSTRAP_ADMIN_ENABLED:-true}"

WEB_MEMORY_RESERVATION="${WEB_MEMORY_RESERVATION:-256}"

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
ECS_DIR="$REPO_ROOT/deploy/ecs"

if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    PYTHON=""
fi

log() { printf '%s %s\n' "▶" "$*"; }
ok() { printf '%s %s\n' "✓" "$*"; }
fail() {
    printf '%s %s\n' "✗" "$*" >&2
    exit 1
}

require_var() {
    eval "value=\${$1:-}"
    if [ -z "$value" ]; then
        fail "Required variable $1 is not set. $2"
    fi
}

resolve_cognito_secret_arn() {
    if [ -n "$COGNITO_SECRET_ARN" ]; then
        printf '%s' "$COGNITO_SECRET_ARN"
        return 0
    fi

    ARN=$(aws secretsmanager describe-secret \
        --secret-id "$COGNITO_SECRET_NAME" \
        --query 'ARN' --output text 2>/dev/null) || ARN=""

    if [ -z "$ARN" ] || [ "$ARN" = "None" ]; then
        fail "Could not resolve $COGNITO_SECRET_NAME. Apply the Cognito Terraform in outvier-infrastructure, or set COGNITO_SECRET_ARN as a CI variable."
    fi

    printf '%s' "$ARN"
}

image_uri() {
    if [ -n "${IMAGE_URI:-}" ]; then
        printf '%s' "$IMAGE_URI"
    else
        require_var CI_COMMIT_SHA "Run inside GitLab CI, or set IMAGE_URI explicitly."
        printf '%s:%s-%s' "$ECR_REPOSITORY" "$ECR_IMAGE_TAG" "$CI_COMMIT_SHA"
    fi
}

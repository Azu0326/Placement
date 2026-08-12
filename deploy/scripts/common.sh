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

image_uri() {
    if [ -n "${IMAGE_URI:-}" ]; then
        printf '%s' "$IMAGE_URI"
    else
        require_var CI_COMMIT_SHA "Run inside GitLab CI, or set IMAGE_URI explicitly."
        printf '%s:%s-%s' "$ECR_REPOSITORY" "$ECR_IMAGE_TAG" "$CI_COMMIT_SHA"
    fi
}

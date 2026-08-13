# GitLab CI/CD variables for Scrapos

Set these under **Settings → CI/CD → Variables** in the Scrapos project.

| Variable | Protected | Masked | Value |
|---|---|---|---|
| `AWS_DEFAULT_REGION` | no | no | `ap-southeast-2` |
| `AWS_ACCESS_KEY_ID` | yes | yes | IAM deployer (same pattern as `dnc_sc`) |
| `AWS_SECRET_ACCESS_KEY` | yes | yes | IAM deployer |
| `ECR_REPOSITORY` | no | no | `738765516909.dkr.ecr.ap-southeast-2.amazonaws.com/dncouncil` |
| `ECR_IMAGE_TAG` | no | no | `scrapos` |
| `ECS_CLUSTER` | no | no | `outvier-ecs-cluster-production` |
| `ECS_WEB_SERVICE` | no | no | `outvier-scrapos-production` |
| `ECS_WEB_TASK_DEFINITION` | no | no | `outvier-scrapos-production` |
| `EXECUTION_ROLE_ARN` | no | no | `arn:aws:iam::738765516909:role/outvier-ecs-execution-role-production` |
| `TASK_ROLE_ARN` | no | no | `arn:aws:iam::738765516909:role/outvier-scrapos-task-production` |
| `TARGET_GROUP_ARN` | no | no | arn:aws:elasticloadbalancing:ap-southeast-2:738765516909:targetgroup/outvier-scrapos/4e98bbcea224ad1f |
| `WEB_LOG_GROUP` | no | no | `/ecs/outvier-scrapos-production` |
| `PRODUCTION_DOMAIN` | no | no | `scrapos.dncouncil.org` |
| `PRODUCTION_HEALTHCHECK_URL` | no | no | `https://scrapos.dncouncil.org/healthz` |
| `DJANGO_SECRET_ARN` | yes | no | `arn:aws:secretsmanager:ap-southeast-2:738765516909:secret:outvier-scrapos-django-production-HaeaQZ` |

Production build/deploy/verify run automatically on every successful `main`
pipeline. Only `rollback_production` is manual.

## Authentication variables

Cognito configuration has sensible defaults in `deploy/scripts/common.sh` and
does not normally need CI variables. Override only to point a pipeline at a
different pool.

| Variable | Default | Purpose |
|---|---|---|
| `COGNITO_USER_POOL_ID` | `ap-southeast-2_8MQhnosSO` | Shared DNC user pool |
| `COGNITO_DOMAIN` | `auth.dncouncil.org` | Hosted UI domain |
| `COGNITO_SECRET_NAME` | `outvier-scrapos-cognito-production` | Secrets Manager entry holding the app client id and secret |
| `COGNITO_SECRET_ARN` | resolved at deploy time | Set this only if the deploy role lacks `secretsmanager:DescribeSecret` |
| `BOOTSTRAP_ADMIN_ENABLED` | `true` | Set to `false` to switch off the non-Cognito superadmin |

The Cognito app client and its secret are created by Terraform in
`outvier-infrastructure/terraform/modules/cognito`. The deploy script resolves
the secret ARN from `COGNITO_SECRET_NAME` because Secrets Manager ARNs carry a
random suffix and cannot be hardcoded.

**No credential belongs in this file or in `.gitlab-ci.yml`.** The Django
secret key, the Cognito client secret and the bootstrap superadmin hash all
reach the container through Secrets Manager, referenced by ARN in the task
definition. See `docs/authentication.md` for rotation.

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
| `DJANGO_SECRET_ARN` | yes | no | Secrets Manager ARN for `outvier-scrapos-django-production` |

Production jobs are manual on `main`, matching `dnc_sc`.

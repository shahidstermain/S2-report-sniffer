# Rollback Procedure

## Overview
This document outlines the steps to revert a production deployment of the S2 Report Sniffer application in case of a critical failure or regression.

## 1. Revert the Container Image
If the deployment uses an orchestrator (e.g., Kubernetes, ECS, Docker Compose):
1. Identify the previous stable image tag (e.g., `s2rs-prod:v1.0.4`).
2. Update the deployment configuration to use the previous tag.
3. Trigger a rolling restart or redeployment.

Example (Docker Compose):
```bash
# Edit docker-compose.yml to use the older tag
docker-compose up -d
```

## 2. Revert Database Migrations
If the bad deployment included an Alembic database migration that broke functionality, you must downgrade the schema before reverting the application code.

1. Exec into the running container (or run the command in the app environment):
```bash
# Revert the last migration
alembic downgrade -1

# Or revert to a specific revision
alembic downgrade <revision_id>
```
2. Verify the schema state:
```bash
alembic current
```

## 3. Verify Rollback Success
After the application and database have been reverted, verify the system health using the deep health check endpoint:

```bash
curl -s http://localhost:8000/api/health/deep
```

Expected output:
```json
{
  "status": "healthy",
  "db": "ok",
  "s3": "not_configured"
}
```

## 4. Post-Rollback
1. Document the incident and the reason for the rollback.
2. Investigate the root cause in the reverted code/migration.
3. Fix the issue, add necessary tests, and proceed with a new deployment cycle.
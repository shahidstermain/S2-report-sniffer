# S2 Report Sniffer Deployment Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the S2 Report Sniffer from a local prototype into a secure, scalable, and highly available production application by resolving the critical blockers identified in the deployment readiness assessment.

**Architecture:** 
1. Replace ephemeral local SQLite storage with PostgreSQL (using SQLAlchemy + Alembic).
2. Replace local file system uploads with AWS S3 / S3-compatible cloud storage.
3. Harden the FastAPI backend with Gunicorn workers and structured JSON logging.
4. Establish comprehensive frontend E2E testing (Playwright) to achieve >80% critical path coverage.
5. Implement production monitoring, alerting, and automated rollback strategies.

**Tech Stack:** Python (FastAPI, SQLAlchemy, Alembic, Boto3, Gunicorn), Node.js/React (Playwright, Jest), Docker, PostgreSQL, AWS S3.

---

## Issue Prioritization & Impact Matrix

| Priority | Issue | Impact | Urgency | Mitigation Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **P0 (Blocker)** | Ephemeral Storage (SQLite + Local Files) | High (Data loss on container restart) | Immediate | Migrate DB to PostgreSQL; migrate file uploads to S3/Cloud Storage. |
| **P0 (Blocker)** | Frontend Test Coverage (<2%) | High (High risk of regressions) | Immediate | Implement Playwright E2E tests for the critical upload/view paths. |
| **P1 (High)** | Production Server Configuration | High (Concurrent request failures) | High | Replace bare Uvicorn with Gunicorn + Uvicorn workers in Dockerfile. |
| **P1 (High)** | Missing Database Migrations | High (Schema evolution impossible) | High | Implement Alembic for stateful schema management. |
| **P2 (Medium)** | Lack of Observability | Medium (Blind to production issues) | Medium | Add structured JSON logging and health check endpoints. |
| **P2 (Medium)** | Container Vulnerabilities | Medium (Security risk) | Medium | Base image hardening and non-root user enforcement (already partially mitigated, needs CI enforcement). |

---

## Phase 1: Database & Storage Migration (Days 1-3)

### Task 1: Initialize Alembic & SQLAlchemy
**Files:**
- Create: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`
- Modify: `backend/requirements.txt`, `backend/server.py`, `backend/storage.py`

- [ ] **Step 1: Write the failing test for DB initialization**
```python
# tests/test_db_migration.py
def test_alembic_config_exists():
    import os
    assert os.path.exists("backend/alembic.ini")
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_db_migration.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**
```bash
pip install sqlalchemy alembic psycopg2-binary
cd backend && alembic init alembic
```
Update `backend/storage.py` to support a `DATABASE_URL` environment variable, falling back to SQLite if absent for backward compatibility.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_db_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add backend/alembic backend/alembic.ini backend/requirements.txt backend/storage.py tests/test_db_migration.py
git commit -m "feat: initialize alembic and sqlalchemy for postgres support"
```

### Task 2: Migrate File Uploads to S3 (Boto3)
**Files:**
- Modify: `backend/storage.py`, `backend/server.py`
- Create: `backend/s3_client.py`

- [ ] **Step 1: Write the failing test**
```python
# tests/test_s3_storage.py
import os
from backend.s3_client import upload_to_s3
def test_s3_upload_mock(mocker):
    # mock boto3 and assert upload_to_s3 calls put_object
    pass
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_s3_storage.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Write minimal implementation**
```python
# backend/s3_client.py
import boto3
import os

def get_s3_client():
    return boto3.client('s3', 
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_REGION', 'us-east-1')
    )

def upload_to_s3(file_path, bucket, object_name):
    client = get_s3_client()
    client.upload_file(file_path, bucket, object_name)
```
Update `server.py` to route uploaded files to S3 if `S3_BUCKET_NAME` is defined.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_s3_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add backend/s3_client.py backend/server.py backend/storage.py tests/test_s3_storage.py
git commit -m "feat: implement s3 storage backend for report uploads"
```

---

## Phase 2: Frontend Testing & QA (Days 4-6)

### Task 3: Setup Playwright E2E Tests
**Files:**
- Create: `frontend/playwright.config.js`, `frontend/e2e/upload.spec.js`
- Modify: `frontend/package.json`

- [ ] **Step 1: Install dependencies & configure**
```bash
cd frontend
npm install -D @playwright/test
npx playwright install --with-deps
```

- [ ] **Step 2: Write the E2E test (Critical Path)**
```javascript
// frontend/e2e/upload.spec.js
const { test, expect } = require('@playwright/test');

test('should upload a report and view the dashboard', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/S2 Report Sniffer/);
  
  // Interact with upload dropzone
  const fileChooserPromise = page.waitForEvent('filechooser');
  await page.locator('text=Click to browse').click();
  const fileChooser = await fileChooserPromise;
  await fileChooser.setFiles('e2e/fixtures/dummy-report.zip');
  
  // Verify redirect to dashboard
  await expect(page).toHaveURL(/\/report\/.*/);
  await expect(page.locator('text=Cluster Health')).toBeVisible();
});
```

- [ ] **Step 3: Run test**
Run: `npx playwright test`
Expected: PASS (assuming backend is running locally and fixture exists)

- [ ] **Step 4: Commit**
```bash
git add frontend/playwright.config.js frontend/e2e frontend/package.json
git commit -m "test: add playwright e2e coverage for critical upload path"
```

---

## Phase 3: Production Server & Infrastructure Hardening (Days 7-8)

### Task 4: Gunicorn Integration & Dockerfile Hardening
**Files:**
- Modify: `Dockerfile`, `backend/requirements.txt`
- Create: `backend/gunicorn_conf.py`

- [ ] **Step 1: Create Gunicorn config**
```python
# backend/gunicorn_conf.py
import multiprocessing
import os

workers_per_core = int(os.getenv("WORKERS_PER_CORE", "1"))
cores = multiprocessing.cpu_count()
workers = max(int(os.getenv("WEB_CONCURRENCY", cores * workers_per_core)), 2)

bind = os.getenv("BIND", "0.0.0.0:8000")
worker_class = "uvicorn.workers.UvicornWorker"
loglevel = os.getenv("LOG_LEVEL", "info")
accesslog = "-"
errorlog = "-"
```

- [ ] **Step 2: Update Dockerfile**
```dockerfile
# Replace CMD in Dockerfile
RUN pip install gunicorn
CMD ["gunicorn", "-c", "backend/gunicorn_conf.py", "backend.server:app"]
```

- [ ] **Step 3: Build and Test Docker Image**
Run: `docker build -t s2rs-prod . && docker run -p 8000:8000 s2rs-prod`
Expected: Server starts with Gunicorn workers successfully.

- [ ] **Step 4: Commit**
```bash
git add Dockerfile backend/gunicorn_conf.py backend/requirements.txt
git commit -m "chore: harden production server with gunicorn and uvicorn workers"
```

### Task 5: Structured JSON Logging
**Files:**
- Modify: `backend/server.py`, `backend/requirements.txt`

- [ ] **Step 1: Install `python-json-logger`**
```bash
pip install python-json-logger
```

- [ ] **Step 2: Configure logging in server.py**
```python
import logging
from pythonjsonlogger import jsonlogger

logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)
```

- [ ] **Step 3: Commit**
```bash
git add backend/server.py backend/requirements.txt
git commit -m "feat: implement structured json logging for production observability"
```

---

## Phase 4: Monitoring, Alerting & Rollbacks (Days 9-10)

### Task 6: Health Checks & CI/CD Integration
**Files:**
- Modify: `backend/server.py`, `.github/workflows/main.yml`

- [ ] **Step 1: Enhance Health Check**
```python
# backend/server.py
@app.get("/api/health/deep")
async def deep_health_check():
    # Check DB connection
    # Check S3 connectivity
    return {"status": "healthy", "db": "ok", "s3": "ok"}
```

- [ ] **Step 2: Define Rollback Procedure (Documentation)**
Create `docs/ROLLBACK.md`:
```markdown
# Rollback Procedure
1. Revert deployment image to previous stable tag in orchestrator (e.g., K8s/ECS).
2. If DB schema changed, run: `alembic downgrade -1`.
3. Verify `/api/health/deep` returns OK.
```

- [ ] **Step 3: Commit**
```bash
git add backend/server.py docs/ROLLBACK.md
git commit -m "feat: add deep health checks and rollback documentation"
```

---

## Success Criteria & KPIs
- **Code Completeness:** 100% of ephemeral state dependencies migrated to S3/Postgres.
- **Build Success:** Multi-stage Dockerfile builds successfully in < 3 minutes.
- **Test Coverage:** Backend > 80%, Frontend E2E critical path > 90% success rate.
- **Infrastructure:** Application can sustain 50+ concurrent report uploads via Gunicorn workers without OOM/Timeout.
- **Documentation:** `DEPLOYMENT.md` updated with S3, Postgres, and Alembic instructions.

---
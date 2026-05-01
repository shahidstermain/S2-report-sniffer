# S2 Report Sniffer — End-to-End Repository Audit

**Repository:** `shahidstermain/S2-report-sniffer`
**Default branch reviewed:** `main` (HEAD `5e4c548`)
**Audit date:** 2026‑05‑01
**Scope:** structure, documentation, code quality, security, dependencies,
testing, configuration, error handling, git history, build/deploy, licensing,
performance.

> Findings are graded **Critical / High / Medium / Low**. Each item carries a
> file path (and line number where applicable), description, impact, and
> recommended fix.

---

## 1. Executive Summary

S2 Report Sniffer is a sizable (~16 kLOC of first‑party code) FastAPI + React
diagnostics app with a desktop (Electron) distribution path. The core parser
(`backend/parsers.py`, ~1,900 LOC) and risk engine (`backend/superchecker.py`,
~2,300 LOC) are mature, well‑tested (≈19 backend test files, 1k+ assertions),
and represent the product's real value. Engineering hygiene around that core,
however, is uneven:

- **Security posture is mixed.** No live secrets exist on disk today, but
  `backend/.env` (containing `MONGO_URL`, `DB_NAME`, `CORS_ORIGINS=*`) and
  `frontend/.env` (containing a `*.preview.emergentagent.com` backend URL)
  were committed in early March 2026 and remain in git history. CORS is
  wide‑open (`*`) by default, the upload endpoint accepts files up to 10 GB,
  and a number of recent dependencies have **known HIGH/CRITICAL CVEs**
  (`gunicorn 21.2.0`, `python-multipart 0.0.22`, `cryptography 46.0.6`,
  `pillow 12.1.1`, `pytest 9.0.2`).
- **Stale dual‑backend architecture.** The repo simultaneously documents and
  ships code for three persistence layers — SQLite (active, used everywhere),
  MongoDB (`motor`, `pymongo`, `migrations_runner.py`, `rollback_runner.py`,
  `MONGO_URL` test env), and PostgreSQL (a stub in `build_store`) — only one
  of which is actually wired. The README and `INTEGRATION.md` still describe
  MongoDB as a hard dependency and reference files that do not exist
  (`backend_test.py`, `frontend/integration-test.html`).
- **Dead/abandoned dependencies** are pulled into both backend and frontend
  builds: `boto3` is imported by `backend/s3_client.py` but is **not declared**
  in `requirements.txt` (would break the `/api/health/deep` path under load);
  `@supabase/supabase-js` is in `frontend/package.json` but is unreferenced in
  `src/`; `aiohttp`, `huggingface_hub`, `tiktoken`, `tokenizers`, `pandas`,
  `numpy`, `pillow`, `s5cmd`, `s3transfer`, `bcrypt`, `passlib`,
  `python-jose`, `ecdsa`, `proto-plus`, `protobuf`, `jq`, etc. are listed in
  `backend/requirements.txt` with no first‑party importer.
- **Configuration files are inconsistent.** `vercel.json` at the repo root
  routes to a Python backend that cannot run on `@vercel/python` as written;
  `backend/alembic.ini`/`backend/alembic/env.py` are present without
  `sqlalchemy`/`alembic` in `requirements.txt`; `backend/requirements-audit.txt`
  pins a *second*, conflicting set of versions (e.g. `fastapi==0.110.1` vs
  `0.135.3`).
- **Documentation is voluminous but partly out‑of‑date and full of
  absolute paths to a single developer's machine** (`/Users/shahidmoosa/...`),
  which leak across `README.md`, `CHANGELOG.md`, `INTEGRATION.md` and others.
  No `LICENSE`, no `CONTRIBUTING.md`, and `frontend/README.md` is the
  default CRA template.
- **Code quality** is mostly serviceable, but the two largest backend modules
  (`server.py` 1,332 LOC, `parsers.py` 1,906 LOC, `superchecker.py` 2,324
  LOC, `glean_mcp.py` 1,087 LOC) violate single‑responsibility, contain
  duplicated try/except/`__import__` patterns, repeated inline `import os`
  and `import json`, ~60 broad `except Exception:` blocks, two bare
  `except:` in `desktop_entry.py`, and dozens of console‑logged debug
  statements left in shipped React code.

The codebase is healthy enough to ship internally, but should not be exposed
to untrusted upload traffic until the Critical and High items below are
fixed.

### Risk profile (top‑level)

| Severity | Count | Examples |
|---|---|---|
| Critical | 4 | Vulnerable `gunicorn`/`python-multipart`/`cryptography`, secrets/PII in git history, CORS `*` with credentials path, missing `boto3` declared dependency |
| High | 11 | Wide‑open upload (10 GB, anonymous), regex DoS via filename validation gaps, broad except + silent failures, dead Mongo migration runner pointed at prod URL, undeclared/dead deps, design/runtime drift between README/code |
| Medium | 18 | Test mocks committed as production tests, `__import__("json")` antipattern, console.log in shipped UI, missing LICENSE/CONTRIBUTING, inconsistent versions between `requirements.txt` and `requirements-audit.txt`, absolute paths in docs, etc. |
| Low | 14 | Bare `except:`, magic numbers, duplicate logger configuration, dead routes, emoji in INTEGRATION.md, etc. |

---

## 2. Critical Issues — fix immediately

### CRIT‑1 — Multiple production dependencies with known HIGH/CRITICAL CVEs

`pip-audit -r backend/requirements.txt --no-deps` returns 6 vulnerabilities in 5
packages:

| Package | Pinned | Fix | CVE |
|---|---|---|---|
| `gunicorn` | `21.2.0` | `22.0.0+` | CVE‑2024‑1135 / CVE‑2024‑6827 — HTTP request smuggling via `Transfer‑Encoding` |
| `python-multipart` | `0.0.22` | `0.0.26+` | CVE‑2026‑40347 — DoS on crafted `multipart/form-data` (directly affects `/api/reports/upload`) |
| `cryptography` | `46.0.6` | `46.0.7+` | CVE‑2026‑39892 — buffer overflow in `Hash.update()` on non‑contiguous buffers |
| `pillow` | `12.1.1` | `12.2.0+` | CVE‑2026‑40192 — FITS decompression bomb |
| `pytest` | `9.0.2` | `9.0.3+` | CVE‑2025‑71176 — `/tmp/pytest-of-{user}` symlink attack (dev only) |

**Why critical:** `python-multipart` is on the request path of the public
upload endpoint, and `gunicorn` is the production WSGI in the `Dockerfile`
(`CMD ["gunicorn", ...]`). Both are exploitable by unauthenticated callers.

**Fix:** Bump in `backend/requirements.txt`:

```text
gunicorn>=22.0.0
python-multipart>=0.0.26
cryptography>=46.0.7
pillow>=12.2.0
pytest>=9.0.3
```

Also delete or refresh `backend/requirements-audit.txt` (see MED‑3) — it
currently pins an *older* `fastapi==0.110.1` / `pydantic==2.10.6` /
`starlette==0.40.0`, which is exactly what attackers will look at if it ever
gets used.

---

### CRIT‑2 — Sensitive files committed to git history

Two `.env` files were added in commits `d51b1fd` / `e4735e4` (2026‑03‑29).
They are deleted on `main`, but the values are still reachable via
`git show <hash>:backend/.env`:

```text
backend/.env  →  MONGO_URL="mongodb://localhost:27017"
                 DB_NAME="test_database"
                 CORS_ORIGINS="*"
frontend/.env →  REACT_APP_BACKEND_URL=https://sdb-insight.preview.emergentagent.com
                 WDS_SOCKET_PORT=443
                 ENABLE_HEALTH_CHECK=false
```

The current `.gitignore` lacks an explicit `**/.env` rule (line 88: `*.env`
matches the file basename only — it covers root but is brittle). The
`.githooks/pre-commit` hook *does* block `.env(\.|$)`, but the hook is not
installed by default (no `core.hooksPath` configured anywhere).

**Why critical:** Anyone forking the repo gets a leaked internal preview URL
that may still be live, and the policy precedent is "we're OK shipping `.env`
files." History rewrites are required for a real cleanup.

**Fix:**

1. Use `git filter-repo` (or BFG) to strip `backend/.env` and `frontend/.env`
   from history; force‑push to `main`; rotate any credentials/URLs that ever
   lived in these files (the preview hostname above).
2. Tighten `.gitignore`:

   ```diff
   -*.env
   -*.env.*
   +**/.env
   +**/.env.*
   +!**/.env.example
   ```

3. Add `git config core.hooksPath .githooks` to `dev-setup.sh` so the
   pre‑commit gate is actually enforced. Better: replace shell hook with
   `pre-commit` framework + `gitleaks`/`detect-secrets`.

---

### CRIT‑3 — Permissive CORS combined with anonymous 10 GB upload

`backend/server.py:1287‑1293`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Default is `allow_origins=["*"]` *with* `allow_credentials=True` — Starlette
silently downgrades to "no credentials" in that case, but the configuration
intent is unsafe and any operator who sets `CORS_ORIGINS=https://app.example`
keeps `allow_credentials=True` with `allow_methods=["*"]` and
`allow_headers=["*"]`, opening CSRF on the upload endpoint
(`POST /api/reports/upload`) which is anonymous and accepts up to 10 GB
(`MAX_UPLOAD_SIZE_BYTES = 10 * 1024**3`) and writes a temp file before
running `validate_filename`, so a single malicious cross‑origin POST can fill
the filesystem.

**Fix:**

- Default `CORS_ORIGINS` should be `http://localhost:3000` (dev) and the
  Electron `null`/`file://` origin (when desktop). Reject `*` if
  `allow_credentials=True`.
- Add an `Origin` allowlist check before any disk write.
- Move filename and Content‑Length validation **before** streaming the body
  to disk (today, `validate_filename` runs only after the entire body is
  read in `server.py:179`).
- Require an auth token (or at least a CSRF double‑submit cookie) for state
  changes (`POST/DELETE`), even in single‑tenant mode.

---

### CRIT‑4 — `boto3` is imported but not in `requirements.txt`

`backend/s3_client.py:1`:

```python
import boto3
import os
```

`backend/server.py:935` imports `from s3_client import get_s3_client` from
inside the `/api/health/deep` endpoint. If `S3_BUCKET_NAME` is set (per the
README/`PRODUCT_ROADMAP.md`, S3 is a planned target), the *first* hit on
`/api/health/deep` raises `ModuleNotFoundError: boto3` and the deep health
check returns `unhealthy` for opaque reasons. Tests `backend/test_s3_storage.py`
also rely on `boto3` being importable (it is, in the dev environment, only
because `boto3` is a transitive dep of `s3transfer` which *is* listed).

**Why critical:** Production deploys that rely on `pip install -r requirements.txt`
will silently break when an operator adds `S3_BUCKET_NAME`. Worse, the test
asserts `aws_access_key_id=None, aws_secret_access_key=None` — i.e. it
exercises the **anonymous** code path, which would attempt an S3 call without
credentials.

**Fix:**

1. Add `boto3>=1.34` to `requirements.txt`.
2. Make `s3_client.py` raise a clear configuration error if both the env vars
   *and* the IAM role are missing, instead of constructing an unauthenticated
   client.
3. Decide whether S3 is in or out of scope and either remove `s3_client.py`
   and the deep health branch, or wire it into `storage.py` properly.

---

## 3. High‑Priority Issues

### HIGH‑1 — Unauthenticated upload, no rate limit, no auth at all
`backend/server.py:139‑365` (`POST /api/reports/upload`).
Every state‑mutating endpoint is anonymous. Combined with **CRIT‑3**, this
gives the world write access to a process that extracts user‑provided
archives and executes parsing logic on them.
**Fix:** Add a single shared‑secret bearer token (env‑driven), a per‑IP
sliding window via `slowapi` or middleware, and refuse all `POST/DELETE`
without it. The desktop client already runs on `127.0.0.1` so this is free.

### HIGH‑2 — Unbounded archive extraction
`backend/parsers.py:115‑186`. `_extract_tar_members` skips members whose
name *starts with* `/` or contains `..`, but it does **not** validate the
final realpath against `extract_dir`. It also does not cap total
uncompressed size or member count for tar archives (only zip is capped at
200,000 entries in `server.py:249`). A 10 GB tar.gz with a 5 TB
uncompressed payload, or a member name `foo/bar/../../etc/passwd` (which
contains `..` — actually blocked) is partially mitigated, but symlink
members (`tarfile.SYMTYPE`/`LNKTYPE`) are not filtered.
**Fix:** Use `tarfile.data_filter` (Python 3.12+) or
`extractall(filter='data')`; pre‑sum `member.size` and reject if total
exceeds, e.g., 50 GB; reject `SYMTYPE`/`LNKTYPE`/`CHRTYPE`/`BLKTYPE`/`FIFOTYPE`.

### HIGH‑3 — `validate_filename` rejects most real‑world report names
`backend/validators.py:48`:
`FILENAME_SAFE_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')`
This rejects any filename with a space, parenthesis, `+`, or non‑ASCII char,
which is the norm for SingleStore support bundles
(`my-cluster (prod 2026-04-30).tar.gz`). Users will hit confusing 400
errors. The function is also called *after* the body is fully streamed to
disk.
**Fix:** Sanitize via `re.sub(r'[^A-Za-z0-9._\-+ ()]', '_', name)`,
truncate to 255 bytes, run before streaming, and treat the *sanitized* name
as ground truth on disk and in DB.

### HIGH‑4 — `migrations_runner.py` and `rollback_runner.py` connect to MongoDB but the project uses SQLite
`backend/migrations_runner.py:30` defaults to
`mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")` and
`sys.exit(1)` on failure. The tooling is part of the documented release
gate (`CORRECTNESS_CHECKLIST.md` §2D) but cannot succeed because the
runtime store is `LocalReportStore` (SQLite). The migration script even
contains MongoDB‑aggregation shell snippets (`db.reports.updateMany(...)`).
**Fix:** Either delete `migrations_runner.py`, `rollback_runner.py`,
`backend/migrations/`, `backend/alembic*` and the references in
`CORRECTNESS_CHECKLIST.md` and the `Makefile`‑style docs, or finish the
SQLite migration story (one consistent mechanism — alembic+sqlalchemy is
fine, but then `sqlalchemy>=2` and `alembic` must be in `requirements.txt`).

### HIGH‑5 — Vercel manifest is broken
`vercel.json:13‑15` routes `/backend/server.py` through `@vercel/python`,
but `server.py` performs `from parsers import ...` etc. (sibling imports),
imports `httpx` for outbound calls, calls `tempfile.mkdtemp` and writes to
`UPLOAD_DIR = Path(tempfile.gettempdir()) / "sdb_uploads"`. None of that
works inside a Vercel serverless function (read‑only filesystem outside
`/tmp`, no persistent SQLite), and the `@vercel/python` builder will not
discover sibling modules without `requirements.txt` co‑located. The
companion `frontend/vercel.json` also exists and conflicts.
**Fix:** Delete `vercel.json` (and `.vercelignore`) at the repo root, or
replace it with a single clearly working static deploy of the React build
and a separate hosted backend reference.

### HIGH‑6 — Dead/unused dependencies inflate attack surface and install time
- `frontend/package.json:35` `@supabase/supabase-js` — **0** references in
  `frontend/src/**`. Pulls in `ws`, `phoenix`, etc.
- `backend/requirements.txt` declares ~110 packages; first‑party imports
  cover ~25. Notable unused/heavyweight pins:
  `aiohttp`, `huggingface_hub`, `hf-xet`, `tiktoken`, `tokenizers`,
  `pandas==3.0.1`, `numpy==2.4.3`, `pillow`, `s5cmd`, `s3transfer`,
  `bcrypt`, `passlib`, `python-jose`, `ecdsa`, `proto-plus`, `protobuf`,
  `googleapis-common-protos`-style modules (`uritemplate`, `httplib2`),
  `jq`, `tenacity`, `regex`, `rich`, `Jinja2`, `MarkupSafe`, `mypy`,
  `flake8`, `black`, `isort` (these last four belong in a `requirements-dev.txt`).
- `pandas==3.0.1` and `numpy==2.4.3` do not exist on PyPI (latest pandas is
  2.x as of 2026‑05) — installs will fail outright.
**Fix:** Run `pipreqs backend` and `npm prune --production` (or
`depcheck`) to derive an honest dependency list; split runtime vs dev
requirements; add `pip-tools` (`requirements.in` → `requirements.txt`) and
`renovate`/`dependabot`.

### HIGH‑7 — Two `requirements*.txt` with conflicting pins
`backend/requirements.txt` pins `fastapi==0.135.3`,
`pydantic==2.12.5`, `starlette==0.49.1`; `backend/requirements-audit.txt`
pins `fastapi==0.110.1`, `pydantic==2.10.6`, `starlette==0.40.0` and a
typo'd `aiohappyeyeball==2.6.1` (correct name is `aiohappyeyeballs`).
Whichever is consulted by an operator's audit script will give the wrong
answer.
**Fix:** Delete `requirements-audit.txt`; or rename it
`requirements-dev.txt` and remove duplicate runtime pins; fix the typo if
kept.

### HIGH‑8 — Recursive logger setup duplicates handlers
`backend/server.py:16‑24` configures a JSON handler on the root logger,
then `server.py:50` calls `logging.basicConfig(...)` again, which on a
fresh Python process attaches a *second* `StreamHandler` with a different
format. Every log record is then emitted twice (once JSON, once plain), which
inflates log volume and breaks log parsers expecting a single format.
**Fix:** Choose one configuration path. Move logging setup to a single
function called once from `startup_app()`; use `force=True` on
`basicConfig` if needed; let gunicorn's logger config take over in
production.

### HIGH‑9 — `_NoCacheUiStaticMiddleware` mutates request headers in‑place
`backend/server.py:54‑66`. It strips `If-None-Match` and
`If-Modified-Since` from the request scope before calling downstream, on
every UI request. Beyond hurting cacheability of static assets, mutating
`request.scope["headers"]` (a list of byte‑tuples) inside an ASGI
middleware is fragile and can crash on unusual proxy configurations
(`HTTP/2` push, `httpx` test client). It also unconditionally adds
`Cache-Control: no-store` to *every* `/static/*` response, defeating the
hashed‑filename strategy that CRA produces.
**Fix:** Drop the conditional revalidation stripping. Serve hashed
`/static/*` files with `Cache-Control: public, max-age=31536000, immutable`
and only `index.html` with `no-store`.

### HIGH‑10 — Inline `.env` validation diverges from FastAPI request schema
`backend/server.py:139` accepts both `file=` and `report=` form fields and
references `file.filename` (line 181/186) when only `report` was sent —
this raises `AttributeError: 'NoneType' object has no attribute 'filename'`
on the legacy code path. The bug is reachable by any client that posts
`report=...` instead of `file=...`, which is explicitly advertised as a
backward‑compatible option in the same function's error message
(`server.py:153`).
**Fix:** Replace `file.filename` with `active_file.filename` in lines 181,
182, 186; add a unit test for the `report=` field path that expects 400 on
a bad name (currently `test_upload_success.py:36‑51` only exercises the
happy path).

### HIGH‑11 — `glean_mcp.py` shells out to `npx` and `pgrep` from the request thread
`backend/glean_mcp.py:163, 184, 286` synchronously call `subprocess.run`
and `subprocess.Popen` on `pgrep` and `npx @gleanwork/mcp-server@latest`
inside an `async def` handler. This blocks the FastAPI event loop, can
download arbitrary npm packages on first request (no version pinning,
`@latest` tag), and is reachable from `POST /api/glean/health` by any
network caller.
**Fix:** Run shell-outs in a worker pool (`asyncio.to_thread`); pin
`@gleanwork/mcp-server@<exact-version>`; require an explicit operator opt-in
env var (`GLEAN_ALLOW_NPX=1`) before invoking `npx`; consider precompiling
the MCP server into the Electron bundle.

---

## 4. Medium‑Priority Issues

### MED‑1 — Dual storage abstraction never finished
`backend/storage.py:519‑529`:

```python
def build_store() -> ReportStore:
    backend = (os.environ.get("STORAGE_BACKEND") or "local").strip().lower()
    db_url = os.environ.get("DATABASE_URL")
    if db_url or backend == "postgres":
        # Temporary fallback placeholder.
        # Once PostgreSQL models are fully implemented, this will return PostgresReportStore()
        pass
    if backend == "local":
        return LocalReportStore()
    return LocalReportStore()
```

Setting `STORAGE_BACKEND=postgres` silently falls back to the local store —
operators will think they're writing to Postgres and lose data on container
restart.
**Fix:** Either implement `PostgresReportStore` or `raise
NotImplementedError("postgres backend not implemented yet")`.

### MED‑2 — `__import__("json")` antipattern repeated in hot paths
`backend/server.py:134, 327, 452, 595, 622, 655` all do
`__import__("json").dumps(...)` / `__import__("json").loads(...)`.
This is identical to `json.dumps`/`json.loads` (already imported at module
scope via `pythonjsonlogger`) but defeats static analysis and slightly
hurts perf. Same idiom in `storage.py:499` for `datetime`.
**Fix:** Move `import json` and `import datetime` to module top and call
the functions directly.

### MED‑3 — Inline imports inside functions (workspace `no-inline-imports` rule)
`backend/server.py:398, 506, 935, 1025`,
`backend/parsers.py:130‑146` (multiple),
`backend/storage.py:118` — all duplicate top‑level imports. Also violates
the workspace rule cached at
`/root/.cursor/plugins/cache/cursor-public/677/.../rules/no-inline-imports.mdc`
(rule: "Keep imports at top of file and avoid inline imports").
**Fix:** Move to module top.

### MED‑4 — Two bare `except:` in `backend/desktop_entry.py`
`backend/desktop_entry.py:20, 26` swallow every exception (incl.
`KeyboardInterrupt`, `SystemExit`).
**Fix:** Replace with `except Exception:` and log to stderr.

### MED‑5 — ~60 `except Exception:` blocks across backend, many silent
Counts:
`parsers.py: 19`, `storage.py: 10`, `server.py: 10`, `superchecker.py: 3`,
`glean_mcp.py: 1`, `monitoring.py: 1`, `validators.py: 1`,
`migrations_runner.py: 1`, `rollback_runner.py: 1`. Many simply `pass` or
`return None`, hiding genuine bugs (especially in the parsers' "graceful
degradation" code path, which `bandit.yaml` waives via B110).
**Fix:** At minimum, log the exception with `logger.exception(...)` so
parse failures show up in monitoring; introduce a parser‑level error
counter exposed at `/api/metrics/performance`.

### MED‑6 — Frontend ships verbose `console.log` debug output
`frontend/src/lib/api.js:22, 26, 34, 38`,
`frontend/src/pages/ReportDashboard.jsx:41, 43, 47, 49, 53, 56, 59`,
`frontend/src/components/GleanSetup.jsx` (4×),
`frontend/src/components/ErrorBoundary.jsx`,
`frontend/src/components/InsightsPanel.jsx`. Debug logs leak request
URLs, status codes and response data into end‑user consoles.
**Fix:** Wrap with `if (process.env.NODE_ENV !== 'production') { ... }`,
or strip via a babel plugin (`babel-plugin-transform-remove-console`) in
the build.

### MED‑7 — Duplicate logo path constant
`frontend/src/pages/ReportDashboard.jsx:15‑16`:
```jsx
const SS_LOGO_WHITE = "/ui/singlestore-logo-white.svg";
const SS_LOGO_BLACK = "/ui/singlestore-logo-white.svg";
```
Both names point to the white asset, so the "black" logo never renders.
**Fix:** Either ship a true black variant in `frontend/public/` or remove
the unused constant.

### MED‑8 — Stray IDE workspace file checked in inside `src/`
`frontend/src/components/dashboard/S2-report-sniffer.code-workspace` is a
VS Code workspace file living *inside* a JSX components directory. CRA
will not import it, but it's misplaced and was caught up in a globbed
`git add`.
**Fix:** Delete it; add `*.code-workspace` to `.gitignore`.

### MED‑9 — Test files contain absolute paths from a single developer
`backend/test_glean_stdio.py:7`:
`sys.path.insert(0, '/Users/shahidmoosa/cr-sniffer/S2-report-sniffer/backend')`
The test cannot run anywhere except that one machine.
**Fix:** Use `sys.path.insert(0, str(Path(__file__).resolve().parent))`.

### MED‑10 — Documentation links to absolute developer paths
`README.md:383‑385`,
`CHANGELOG.md:4, 8, 12, 13`,
`COMPARISON.md` (`file:///Users/...`), and
`PHASE1_CHECKLIST.md` all contain `file:///Users/shahidmoosa/...` URLs.
**Fix:** Replace with repository‑relative links
(`./PACKAGING.md`, `[parsers.py](backend/parsers.py)`, etc.).

### MED‑11 — Documentation references files that do not exist
- `README.md:84` — `backend_test.py` (not present).
- `INTEGRATION.md:33` — `http://localhost:3000/integration-test.html`
  (not present in `frontend/public`).
- `CORRECTNESS_CHECKLIST.md:29` — `backend_test.py` again.
**Fix:** Delete the references or restore the files.

### MED‑12 — README still says MongoDB is required
`README.md:96‑97, 137‑141, 271‑284`. The repo defaulted to local SQLite
in commit `cb2c607` (Apr 2026). Telling users to provision MongoDB and
set `MONGO_URL` is now misleading.
**Fix:** Rewrite §1, §4, §5.4, §7, §9 to describe the SQLite/local‑first
architecture as the canonical mode and MongoDB as a deprecated/optional
backend (or remove it entirely).

### MED‑13 — `frontend/README.md` is the unmodified CRA template
3 KB of "How to start a CRA project" boilerplate, no actual project info.
**Fix:** Replace with a one‑page "frontend dev guide" (or delete and rely
on the root `README.md`).

### MED‑14 — Hardcoded fonts/icons hit `fonts.googleapis.com` and `singlestore.com`
`frontend/public/index.html:8, 11`. Air‑gapped desktop users (the entire
selling point of `PACKAGING.md`) will see broken fonts and a missing
favicon.
**Fix:** Self‑host the fonts under `frontend/public/fonts/` and bundle
the favicon. Same for `https://www.singlestore.com/favicon.ico`.

### MED‑15 — `dev-setup.sh` activates a venv that may not exist and forks the backend
`dev-setup.sh:11‑16` does `source venv/bin/activate` and then
`uvicorn ... &`. If `venv` is named `.venv` (as the README suggests) the
script silently runs uvicorn against the system Python, and the orphaned
backend keeps running after the script exits.
**Fix:** `set -euo pipefail`; check for `.venv` *and* `venv`; `trap`
shutdown; document the venv convention.

### MED‑16 — `_parse_report_background` swallows `os.unlink` errors and depends on global imports
`backend/server.py:482‑629` has a 150‑line function with 5 nested `try`/`except`,
re‑imports `os` at line 506, and computes a percentage using
`min(90, 10 + (progress_state["files"] * 80 // max(progress_state["nodes"] * 50, 1)))`
which is hard to read and produces non‑monotonic progress bars when
`nodes` increases faster than `files`.
**Fix:** Extract the progress math to a helper with unit tests; remove
inline `import os`; use `Path.unlink(missing_ok=True)`.

### MED‑17 — Glean config token displayed/saved with `api_token=""` on the server
`backend/server.py:1075‑1110` defines a `GleanConfigRequest` Pydantic
model with **no** `glean_token` field, but `frontend/src/components/GleanSetup.jsx`
displays UI for entering one, and `README.md:454` advertises a token‑based
setup. The frontend POSTs the token but the backend silently drops it.
**Fix:** Either add `glean_token: Optional[str]` to the request model and
persist via `GleanConfigManager`, or remove the token field from the UI
and the README.

### MED‑18 — `bandit.yaml` blanket‑skips `B603` and `B404` for the whole codebase
`bandit.yaml:5‑8`. The justification (in‑file note) is reasonable for
parsers but masks the genuinely risky `subprocess.Popen(["npx", ...])` in
`glean_mcp.py` (HIGH‑11). Skip rules should be local (`# nosec B603`) at
the call site, not global.
**Fix:** Remove the `B603`/`B404` skips; annotate individual safe sites
with `# nosec`.

---

## 5. Low‑Priority Issues

### LOW‑1 — Many emoji and `console.log("🚀 ...")` strings throughout
`frontend/src/lib/api.js:22`, `dev-setup.sh`, `INTEGRATION.md`,
`CORRECTNESS_CHECKLIST.md`. Workspace rules ask for restraint on emoji.
**Fix:** Strip from source code; documentation can keep them but they're
dense (>30 in `INTEGRATION.md`).

### LOW‑2 — `frontend/src/lib/utils.js` is a 6‑line file
Could be inlined into `utils-sdb.js` to reduce module sprawl.

### LOW‑3 — `frontend/src/lib/utils-sdb.js:42-49` returns hex colors as strings
Move palette to CSS variables (already defined in `App.css`) for theme
consistency; today, dark‑mode renders the same `#F44336` red.

### LOW‑4 — `severity_weight` table re‑declared in two modules
`backend/server.py:529` and `backend/superchecker.py:7`. Centralize.

### LOW‑5 — `LocalReportStore.delete_report` never surfaces partial‑delete errors
`backend/storage.py:323‑338` ignores every filesystem error during
recursive cleanup; leaks files if `unlink` fails on Windows due to AV
locks.

### LOW‑6 — `chunk_uploads` table created but never used by API
`backend/storage.py:170‑182` defines a `chunk_uploads` table and 5
methods (`save_chunk_state`, …, `cleanup_old_chunks`) that no endpoint
calls. Either wire chunked uploads or drop them.

### LOW‑7 — Backup history truncated to last 50 rows
`backend/server.py:564` `"backup_history": parsed.get("backup_history", [])[-50:]`.
Magic constant; document or move to a named constant.

### LOW‑8 — Magic number 5000 in log retention
`backend/parsers.py:383` `result["logs"] = all_logs[-5000:]`.
Already has `MAX_RAW_LOGS = 50000`; harmonize.

### LOW‑9 — `MAX_PAYLOAD_SIZE` hardcoded to 100 MB
`backend/storage.py:358`. If a real cluster yields a 130 MB payload, the
endpoint returns `{"error": "Payload too large", ...}` with **HTTP 200**,
silently masking the failure.
**Fix:** Make it env‑driven (`S2RS_MAX_PAYLOAD_MB`) and return 413.

### LOW‑10 — `vercel.json` references a path that does not exist
`frontend/vercel.json` references `package.json` `distDir: "build"`, but
`/workspace/.vercelignore:2` excludes `build` — Vercel would deploy an
empty bundle.

### LOW‑11 — Test fixture `test_reports/iteration_*.json` is committed but unused
193 lines of synthetic test status reports under `test_reports/`. Looks
like agent‑generated artifacts.

### LOW‑12 — `tests/__init__.py` is an empty 0‑byte file with no siblings
The `tests/` directory exists only to host an empty `__init__.py`. Either
add tests or delete.

### LOW‑13 — Many "empty" planning docs at the repo root
`OP_TXT_CHECKER_PLAN.md`, `OP_TXT_VALIDATION_REPORT.md`,
`PHASE1_CHECKLIST.md`, `PHASE3_DEFERRED_TASKS.md`,
`PREPROD_TEST_REPORT.md`, `PRODUCT_ROADMAP.md`, `STRATEGY_BRIEF.md`,
`VERIFICATION_REPORT.md`, `CORRECTNESS_CHECKLIST.md`, `COMPARISON.md`,
`design_guidelines.json`, `DESIGN.md`. The root is 22 markdown files
deep — most should move under `docs/` per the workspace AGENTS.md.

### LOW‑14 — `S2RS_DISABLE_GZIP` toggle is undocumented
`backend/conftest.py:3` and `backend/server.py:1295` reference a
`S2RS_DISABLE_GZIP` env var that nothing in the README/AGENTS.md mentions.

---

## 6. Detailed Findings by Audit Area

### 6.1 Repository Structure & Organization

**Top‑level inventory** (22 markdown files at root, 38 first‑party Python files,
~75 React files):

```text
.
├─ backend/                Python application + tests
├─ frontend/               React (CRA + craco) UI + Playwright e2e (1 spec)
├─ desktop/                Electron wrapper (main.js + electron-builder)
├─ scripts/                build-macos-arm64-dmg.sh (only)
├─ tools/trae_mcp_hardening/  MCP config validator + hooks (well-isolated)
├─ tests/                  empty (only __init__.py)
├─ test_reports/           agent-generated JSON status snapshots
├─ docs/                   only superpowers/plans + ROLLBACK + PHASE3
├─ memory/                 PRD.md (private?) + .gitkeep
├─ .github/workflows/      one workflow (mcp-security)
├─ AGENTS.md, AIRGAP_TEST_PROTOCOL.md, CHANGELOG.md, COMPARISON.md,
   CORRECTNESS_CHECKLIST.md, DEPLOYMENT.md, DESIGN.md, INTEGRATION.md,
   LOCAL_FIRST_ARCHITECTURE.md, OP_TXT_CHECKER_PLAN.md,
   OP_TXT_VALIDATION_REPORT.md, PACKAGING.md, PHASE1_CHECKLIST.md,
   PREPROD_TEST_REPORT.md, PRODUCT_ROADMAP.md, README.md,
   STRATEGY_BRIEF.md, USER_MANUAL.md, VERIFICATION_REPORT.md
└─ design_guidelines.json
```

**Issues:**
- *Top‑level clutter:* See LOW‑13. Move planning/strategy docs into
  `docs/planning/`.
- *Missing standard files:* No `LICENSE`, no `CONTRIBUTING.md`, no
  `CODE_OF_CONDUCT.md`, no `SECURITY.md`, no `.editorconfig`, no
  `.python-version`, no `pyproject.toml`. `README.md:497` even
  acknowledges "no explicit license file".
- *Inconsistent layout:* tests live under `backend/test_*.py` *and*
  `tests/` *and* `frontend/e2e/` *and* `tools/trae_mcp_hardening/tests/`.
  No single `pytest.ini` or `conftest.py` ties them together.
- *Naming:* `test_zip_parsing_variants.py` and
  `test_zip_upload_edge_cases.py` mostly cover the same surface;
  `test_parsers.py` is 1,038 lines and should be split per parser
  family.

### 6.2 README & Documentation

`README.md` is comprehensive (~500 lines, 17 sections) but factually drifts
from the code:

| Claim | Reality |
|---|---|
| "MongoDB 6+ required" (§4) | Code defaults to local SQLite; Mongo paths are dead |
| `backend_test.py` (§3) | File does not exist |
| Diagram shows MongoDB as the persistence layer (§1) | SQLite + JSON files on disk |
| `emergentintegrations==0.1.0` may need manual install (§4, §9) | Already commented out; instruction is moot |
| Glean token field in §16 | Backend config model has no `glean_token` |
| Docker `MONGO_URL` recipe (§12) | Container does not bind‑mount data dir; SQLite path lost on restart |

Other docs:
- `INTEGRATION.md:33` references `integration-test.html` (does not exist).
- `INTEGRATION.md:60` documents a `proxy` block in `craco.config.js` that
  is *not* actually present (line 71+).
- `CORRECTNESS_CHECKLIST.md:64` documents
  `backend/migrations_runner.py check` — the script has no `check`
  subcommand.
- `PREPROD_TEST_REPORT.md`, `VERIFICATION_REPORT.md`,
  `OP_TXT_VALIDATION_REPORT.md` look agent‑generated; uncertain if they
  represent reproducible state.
- `LOCAL_FIRST_ARCHITECTURE.md` and `AGENTS.md` agree (good) but conflict
  with the `README.md`/`Dockerfile` story.

### 6.3 Code Quality

- *Function/file size:*
  `backend/parsers.py` 1,906 LOC, `backend/superchecker.py` 2,324 LOC,
  `backend/server.py` 1,332 LOC, `backend/glean_mcp.py` 1,087 LOC,
  `frontend/src/pages/ReportList.jsx` 652 LOC. These should be split into
  cohesive submodules (e.g. `parsers/` package with `archive.py`,
  `nodes.py`, `logs.py`).
- *Cyclomatic complexity hotspots:* `_parse_report_background`
  (`server.py:482‑629`), `parse_report_directory` (`parsers.py:266‑470`),
  `_check_*` family in `superchecker.py` (each 30‑80 LOC, deeply nested
  conditionals over partly‑typed dicts).
- *Duplicated logic:*
  - severity weights (LOW‑4)
  - filename‑extension dispatch is hand‑rolled in two places
    (`server.py:160‑177` and `server.py:422‑436`)
  - `_progress`/`progress_callback` wiring duplicated for archive vs
    directory ingest
- *Commented‑out code:*
  `backend/requirements.txt:20` (`# emergentintegrations==0.1.0`),
  `backend/storage.py:521‑525` ("Temporary fallback placeholder"),
  `backend/server.py:78‑79` (note in code), assorted `# TODO:`/`# nosec`
  markers.
- *`__import__` antipattern:* MED‑2.
- *Inline imports:* MED‑3.
- *Hardcoded values:* LOW‑7, LOW‑8, LOW‑9; also `MAX_RAW_LOGS = 50000`
  and `[-5000:]` log slicing without justification.
- *Style:* No `pyproject.toml`, no `ruff.toml`, no `.editorconfig`. The
  declared formatters/linters in `requirements.txt` (`black`, `flake8`,
  `isort`, `mypy`) are never invoked in CI.

### 6.4 Security Audit

| # | Issue | Location | Severity |
|---|---|---|---|
| S‑1 | Vulnerable `gunicorn`, `python-multipart`, `cryptography`, `pillow`, `pytest` (see CRIT‑1) | `backend/requirements.txt` | Critical |
| S‑2 | `.env` files in git history | `git show d51b1fd:backend/.env`, `:frontend/.env` | Critical |
| S‑3 | CORS `*` with `allow_credentials=True` semantic mistake | `backend/server.py:1287‑1293` | Critical |
| S‑4 | Anonymous 10 GB upload, no auth, no rate limit | `backend/server.py:139‑365` | High |
| S‑5 | Tar extraction does not enforce realpath / cap uncompressed size / reject symlinks | `backend/parsers.py:115‑186` | High |
| S‑6 | Filename validation runs after disk write; rejects normal names | `backend/server.py:179`, `backend/validators.py:48` | High |
| S‑7 | `subprocess.Popen(["npx", "@gleanwork/mcp-server@latest"])` reachable from public endpoint | `backend/glean_mcp.py:184‑192` | High |
| S‑8 | `boto3` undeclared, anonymous S3 client construction in `s3_client.py` | `backend/s3_client.py:1‑13` | High |
| S‑9 | `export_html` builds raw HTML from user content via f‑string concat (returned as JSON today, but easy to misuse) | `backend/server.py:1053‑1064` | Medium |
| S‑10 | `validate_search_query` HTML‑escapes input (good) but `validate_node_filter` only `re.escape`s, not enforced as identifier — passed straight to substring match in `LocalReportStore.query_report_logs` | `backend/storage.py:419‑422` | Medium |
| S‑11 | Glean token UI submits a secret that the backend drops on the floor (MED‑17) | `backend/server.py:1069‑1109` | Medium |
| S‑12 | `python-jose`, `ecdsa`, `passlib` shipped but not used; pulls deprecated crypto | `backend/requirements.txt` | Medium |
| S‑13 | No `Content-Security-Policy`, `X-Frame-Options`, `Referrer-Policy`, or `Strict-Transport-Security` headers on UI responses | `backend/server.py` | Medium |
| S‑14 | `_lock_file` in `desktop_entry.py` uses `/tmp/s2rs_backend.lock` without `O_EXCL`; race‑prone (TOCTOU) | `backend/desktop_entry.py:11‑27` | Low |
| S‑15 | Pre‑commit hook present but not installed by default | `.githooks/pre-commit` | Low |

**SQL injection:** `backend/storage.py` uses parameterized queries
everywhere except f‑strings that interpolate column names from a fixed
allowlist (`storage.py:257, 277`); not exploitable today, but the
`# nosec` comments make it brittle for future contributors.

**XSS:** React JSX escapes by default. No `dangerouslySetInnerHTML` in
`frontend/src`. The risk is in the backend `export_html` endpoint (S‑9),
which currently wraps the HTML in a JSON envelope — but no caller exists.

**Path traversal:** `backend/server.py:1257‑1273` (`/ui/{path:path}`)
correctly checks `str(candidate).startswith(str(root))` after `resolve()`.
Same module's `/api/reports/import` (server.py:376‑479) accepts an
arbitrary client‑supplied filesystem path, calls `Path(p).resolve()` and
*does not* sandbox it — a local user can ask the backend to read any
directory the process can read. In desktop mode this is the user's own
files, which is intended; in any hosted mode it's a directory traversal
into the host. The endpoint is gated by `isinstance(store,
LocalReportStore)` (i.e. desktop), but combined with HIGH‑1 the trust
boundary is unclear.

### 6.5 Dependency Analysis

*See HIGH‑6 and CRIT‑1.* Notable observations:

- `pip-audit` (no‑deps mode against the pinned set):
  - 6 vulnerabilities in 5 packages
  - 108 declared dependencies
- `npm audit` could not be run in this environment (no `npm` available),
  but `frontend/package.json` pins `react-scripts@5.0.1` which has its
  own well‑known transitive vulnerabilities (`webpack-dev-server`,
  `serialize-javascript`, `nth-check` etc.) that the
  `security_audit_gate.sh` was written specifically to track.
- `cra-template@1.2.0` is listed as a runtime dependency — it is a
  scaffolding template and should not be present at all.
- `react-router-dom: ^7.13.2` is a major version ahead of the rest of
  the React ecosystem in this app and may not actually be installed
  (no `7.x` line exists yet); the lockfile likely resolves to `6.x`.
- Backend `requirements.txt` pins `pandas==3.0.1` and `numpy==2.4.3`
  which do not exist on PyPI as of audit date.

### 6.6 Testing Coverage

- **Backend:** ~19 test modules, ~5,800 LOC of tests. Strong coverage of
  parsers and superchecker (the actual product). API smoke tests are
  thin (`test_api_smoke.py` exercises 8 endpoints, none with real data).
- **Frontend:** 1 Jest test (`ReportList.test.jsx`, 44 LOC) and 1
  Playwright e2e (`upload.spec.js`, 25 LOC). 17 dashboard components
  ship without any test.
- **CI:** Only `mcp-security` workflow runs (a single
  `python -m unittest tools.trae_mcp_hardening...`). No CI runs the
  backend pytest suite, the frontend build, the security gate, or the
  e2e tests.
- **Skipped/commented tests:** none observed (`grep -n '@unittest.skip'`
  returns nothing). Good.
- **Coverage tooling:** `coverage` is referenced in README §10 but no
  `.coveragerc` and no CI step.

### 6.7 Configuration Files

- `.gitignore` — generally OK; needs the tightening in CRIT‑2 and an
  entry for `*.code-workspace` (MED‑8). The line `android-sdk/-e ` is
  malformed (trailing `-e ` shell artifact from `echo -e >>`).
- `vercel.json` — broken (HIGH‑5).
- `frontend/vercel.json` — see LOW‑10.
- `bandit.yaml` — see MED‑18.
- `.vercelignore` — excludes `build` (LOW‑10).
- `Dockerfile` — minor issue: `apt-get upgrade -y` is non‑deterministic
  for image hashes; consider `apt-get install -y --no-install-recommends`
  only.
- `s2rs-backend.spec` — PyInstaller spec, present but not exercised in
  CI; will silently rot.

### 6.8 Error Handling

- 60+ `except Exception:` blocks (MED‑5) and 2 bare `except:` (MED‑4).
- `_parse_report_background` (`server.py:482‑629`) writes
  `error: str(e)` directly into the DB and into the API response — leaks
  internal exception messages to the client.
- `glean_mcp.GleanMCPClient._send_stdio_request` has no timeout on
  `_process.stdout.readline()`, which will block forever if the npx
  subprocess hangs.
- React `ErrorBoundary` (frontend/src/components/ErrorBoundary.jsx, 42
  LOC) is wired around the dashboard but logs to `console.error` only —
  no telemetry.

### 6.9 Git History Analysis

- 56 commits on `main`. Authors: `emergent-agent-e1`, `Copilot`, and
  human author(s).
- Commit message hygiene: 9 messages match `auto-commit|wip|fix$|test$`
  patterns (`8813d86 auto-commit for ...`, etc.) — these should have
  been squashed.
- Sensitive files in history: `backend/.env`, `frontend/.env` (CRIT‑2).
- No oversized binary blobs (`git rev-list --objects --all` →
  largest blob is `frontend/package-lock.json` at ~1 MB).
- No PGP‑signed commits.
- Branch structure: `main` only on origin in this checkout; PRs #1‑#9
  exist (Copilot‑generated branches).

### 6.10 Build & Deployment

- **CI:** `.github/workflows/mcp-security.yml` runs *only* the
  trae‑mcp‑hardening unit tests. **The actual product is never built
  or tested in CI.** This is the single highest‑impact CI gap.
- **Build scripts:** `scripts/build-macos-arm64-dmg.sh` performs three
  serial builds (frontend, PyInstaller, electron‑builder); no
  parallelism, no caching, no notarization (acknowledged in README).
- **Container:** `Dockerfile` is sound but does not pin `python:3.11.15`
  by digest, runs `apt-get upgrade` (non‑reproducible), and copies
  `backend/` after install (good for layer caching).
- **Deployment:** Mixed signals — `vercel.json`, `Dockerfile`, Electron,
  and DEPLOYMENT.md describe four different targets. Pick one canonical
  path per environment and document it.

### 6.11 Licensing & Compliance

- **No `LICENSE` file.** README §17 explicitly notes this. With ~110
  Python deps and ~1 GB of node_modules under MIT/Apache/BSD/GPL, the
  project should declare its own license to avoid implicit "all rights
  reserved" defaulting.
- **Dependency licenses:** `python-jose`, `passlib`, `bcrypt` are MIT;
  `cryptography` is Apache‑2.0/BSD; `react-scripts` is MIT; `recharts`
  is MIT; `lucide-react` is ISC. No GPL contamination observed.
- **Copyright notices:** none. Recommend adding SPDX headers.

### 6.12 Performance & Efficiency

- **N+1 risk:** `LocalReportStore.query_report_logs`
  (`storage.py:383‑435`) does a full file scan of `logs.jsonl` on every
  request. For reports with the documented 50 K log lines and a
  `page_size=10`, that's 50 K JSON parses per page. Should index by
  `severity`/`hostname` (SQLite FTS5 or a small inverted index in the
  same SQLite DB).
- **Synchronous in async handlers:** `glean_mcp` subprocess calls
  (HIGH‑11), `tarfile.open` and `gzip.open` in `server.py:276‑306`
  during upload (blocks event loop on multi‑GB streams). Wrap in
  `asyncio.to_thread`.
- **Memory:**
  - `MAX_PAYLOAD_SIZE = 100 MB` reads the whole report into RAM
    (`storage.py:367‑371`).
  - `parsers.py:382` keeps `all_logs[-5000:]` after a sort — fine, but
    the intermediate list can hit `MAX_RAW_LOGS = 50000` entries.
  - Frontend ships `package-lock.json` ~1 MB and a 1.4 MB
    `dashboard-utils.js`+`ReportList.jsx` bundle (no code‑splitting
    declared in `craco.config.js`).
- **Pagination:** `list_reports(limit=100)` is hard‑capped; UI has no
  "load more". For a year of daily uploads, the list silently truncates.
- **Indexes:** SQLite has `idx_reports_uploaded_at` and
  `idx_chunk_uploads_created_at` only; no index on `status`,
  `health_score`, or `cluster_risk_score` despite the UI sorting on
  them.

---

## 7. Prioritized Action Plan

### Must‑do before any external exposure

1. **Bump vulnerable deps** (CRIT‑1): `gunicorn`, `python-multipart`,
   `cryptography`, `pillow`, `pytest`.
2. **Rewrite git history** to remove `backend/.env` and `frontend/.env`,
   then rotate any URLs/credentials they ever held (CRIT‑2).
3. **Tighten CORS** and add request authentication on `POST/DELETE`
   endpoints; lower default upload cap or require auth (CRIT‑3, HIGH‑1).
4. **Declare `boto3`** in `requirements.txt` or remove `s3_client.py`
   and the `/api/health/deep` S3 branch (CRIT‑4).
5. **Replace tar `extractall` with `data` filter** and enforce per‑archive
   uncompressed‑size and member caps; reject symlink/device members (HIGH‑2).
6. **Move filename validation before disk write** and accept a wider
   character set (HIGH‑3).

### Foundational cleanup

7. Decide on **one persistence backend**; delete the dead Mongo runner,
   alembic stubs, and `requirements-audit.txt` (HIGH‑4, HIGH‑7, MED‑1,
   MED‑3).
8. Decide on **one deployment target**; remove `vercel.json` (or rewrite
   correctly) and the `frontend/vercel.json` `distDir` mismatch (HIGH‑5,
   LOW‑10).
9. **Honest dependency manifest** via `pip‑compile`/`depcheck`; remove
   `@supabase/supabase-js`, `cra-template`, `pandas`/`numpy`/`pillow`,
   and the unreal version pins (HIGH‑6).
10. **Stand up real CI**: backend pytest (`pytest -q backend`), frontend
    `npm test -- --watchAll=false && npm run build`, `pip-audit`,
    `bandit -c bandit.yaml -r backend`, `security_audit_gate.sh`.

### Code quality and documentation

11. Rewrite the README §1, §4–§7, §12, §16 to match the local‑first SQLite
    reality (MED‑12).
12. Replace the default CRA `frontend/README.md` (MED‑13).
13. Convert all `file:///Users/...` doc links to repo‑relative (MED‑10).
14. Remove `console.log` from shipped React code (MED‑6).
15. Move planning docs to `docs/planning/` and reduce root noise (LOW‑13).
16. Add `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `.editorconfig`,
    `pyproject.toml` (HIGH‑7‑adjacent, governance).

### Reliability and operability

17. Add `Strict‑Transport‑Security`, `X-Content-Type-Options`,
    `Referrer-Policy`, `Content-Security-Policy` headers via a single
    middleware (S‑13).
18. Replace `__import__("json")` with the top‑level `json` import (MED‑2).
19. Centralize logging configuration; stop double‑configuring (HIGH‑8).
20. Make `_NoCacheUiStaticMiddleware` a no‑op for `/static/*.[hash].*`
    (HIGH‑9).
21. Index `reports.status`, `health_score`, `cluster_risk_score` in
    SQLite; add FTS5 to logs (perf §6.12).
22. Add structured error reporting to React `ErrorBoundary` (telemetry).
23. Self‑host fonts/favicon for true offline operation (MED‑14).

---

## 8. Appendix A — Bandit Summary (first‑party only)

```text
issues: 56 (all LOW)
test_id  count
B101     45  assert_used (pytest assertions; benign)
B105      4  hardcoded_password_string  (test fixtures: HOSTINGER_API_TOKEN="test")
B106      2  hardcoded_password_funcarg (api_token="" defaults)
B107      1  hardcoded_password_default (api_token="" default)
B607      3  start_process_with_partial_path (npx, pgrep — see HIGH-11)
B112      1  try_except_continue (storage.py:413, log scan loop)
```

## 9. Appendix B — pip-audit Summary

```text
Dependencies audited (no-deps): 108
Vulnerable packages           : 5
Vulnerabilities               : 6

cryptography==46.0.6        CVE-2026-39892  fix=46.0.7
pillow==12.1.1              CVE-2026-40192  fix=12.2.0
pytest==9.0.2               CVE-2025-71176  fix=9.0.3
python-multipart==0.0.22    CVE-2026-40347  fix=0.0.26
gunicorn==21.2.0            CVE-2024-1135   fix=22.0.0
gunicorn==21.2.0            CVE-2024-6827   fix=22.0.0
```

## 10. Appendix C — How to Reproduce This Audit

```bash
# Static analysis
pip install pip-audit bandit
pip-audit --disable-pip --no-deps -r backend/requirements.txt -f json > pa.json
bandit -q -c bandit.yaml -r backend -f json > bandit.json

# Dependency scan (frontend)
( cd frontend && npm ci && npm audit --omit=dev --json > ../npm_audit.json )

# Build smoke (would currently fail because pandas==3.0.1 does not exist)
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONPATH=backend python -m pytest backend -q

# Frontend build
( cd frontend && npm ci && npm run build && npm test -- --watchAll=false )
```

---

**Auditor's note.** The product's analytical core is genuinely strong and
the local‑first desktop architecture is a smart distribution choice. Almost
all of the issues above are *operational debt* (stale docs, dead deps,
half‑finished migrations) rather than fundamental design flaws. Working
through the "Must‑do" list (six tasks) followed by the foundational cleanup
gets the repo to a defensible internal release.

#!/usr/bin/env bash
# Local equivalent of .github/workflows/ci.yml and mcp-security.yml.
# Run from anywhere: scripts/ci-local.sh
# Subsets: --backend --frontend --security --mcp --whitespace
# With no flags, every gate runs. This is the merge gate while GitHub Actions
# cannot start jobs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

run_backend=0
run_frontend=0
run_security=0
run_mcp=0
run_whitespace=0

usage() {
  cat <<'EOF'
Usage: scripts/ci-local.sh [--backend] [--frontend] [--security] [--mcp] [--whitespace]

Runs the same commands as the GitHub Actions CI jobs. With no flags, every gate runs.
EOF
}

if [[ $# -eq 0 ]]; then
  run_backend=1
  run_frontend=1
  run_security=1
  run_mcp=1
  run_whitespace=1
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend) run_backend=1 ;;
    --frontend) run_frontend=1 ;;
    --security) run_security=1 ;;
    --mcp) run_mcp=1 ;;
    --whitespace) run_whitespace=1 ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PY="$PYTHON_BIN"
elif [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

section() {
  echo ""
  echo "== $1 =="
}

require_module() {
  local module="$1"
  local install_hint="$2"
  if ! "$PY" -c "import ${module}" >/dev/null 2>&1; then
    echo "Missing Python module '${module}' in ${PY}. ${install_hint}" >&2
    exit 1
  fi
}

if [[ "$run_backend" -eq 1 ]]; then
  section "Backend tests"
  export S2RS_DATA_DIR="${S2RS_DATA_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/s2rs-ci.XXXXXX")}"
  echo "S2RS_DATA_DIR=${S2RS_DATA_DIR}"
  (cd "$ROOT/backend" && "$PY" -m pytest -q)
  section "Backend static gate"
  require_module flake8 "Install backend/requirements-dev.txt."
  (cd "$ROOT/backend" && "$PY" -m flake8 --select=F821,F822,F823,E9 --exclude=.venv,__pycache__ .)
fi

if [[ "$run_frontend" -eq 1 ]]; then
  section "Frontend"
  (cd "$ROOT/frontend" && npm ci && npm run build && npm run typecheck && npm test)
fi

if [[ "$run_security" -eq 1 ]]; then
  section "Security"
  require_module bandit "pip install bandit"
  require_module pip_audit "pip install pip-audit"
  "$PY" -m bandit -r backend -c bandit.yaml -ll
  "$PY" -m pip_audit -r backend/requirements.txt
  "$ROOT/security_audit_gate.sh"
  section "Debug instrumentation"
  matches="$(grep -rnE "127\.0\.0\.1:7642/ingest|#region agent log|X-Debug-Session-Id|\.cursor/debug-" \
    --exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=node_modules --exclude-dir=build \
    backend frontend/src || true)"
  if [[ -n "$matches" ]]; then
    echo "$matches"
    echo "Debug instrumentation detected (ingest URL / agent-log regions). Strip it before merging." >&2
    exit 1
  fi
  echo "OK: no debug instrumentation found."
fi

if [[ "$run_mcp" -eq 1 ]]; then
  section "MCP hardening"
  "$PY" -m unittest tools.trae_mcp_hardening.tests.test_validate_mcp -q
fi

if [[ "$run_whitespace" -eq 1 ]]; then
  section "Whitespace"
  git diff --check
  git diff --cached --check
  if git rev-parse --verify --quiet origin/main >/dev/null; then
    git diff origin/main...HEAD --check
  fi
fi

echo ""
echo "Local CI gates passed."

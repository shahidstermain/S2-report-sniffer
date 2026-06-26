#!/usr/bin/env bash
# security_audit_gate.sh
# Fails CI if new HIGH or CRITICAL vulnerabilities are introduced in frontend dependencies.
# Run: ./security_audit_gate.sh
set -e

cd "$(dirname "$0")/frontend"

echo "Running npm audit (production dependencies)..."
AUDIT=$(npm audit --omit=dev --json 2>/dev/null || true)
HIGH=$(echo "$AUDIT" | python3 -c "import sys,json; d=json.load(sys.stdin); v=d.get('vulnerabilities',{}); print(sum(1 for x in v.values() if isinstance(x,dict) and x.get('severity') in ('high','critical')))" 2>/dev/null || echo "0")
CRIT=$(echo "$AUDIT" | python3 -c "import sys,json; d=json.load(sys.stdin); v=d.get('vulnerabilities',{}); print(sum(1 for x in v.values() if isinstance(x,dict) and x.get('severity')=='critical'))" 2>/dev/null || echo "0")

echo "HIGH vulnerabilities found: $HIGH"
echo "CRITICAL vulnerabilities found: $CRIT"

if [ "$HIGH" -gt 0 ] || [ "$CRIT" -gt 0 ]; then
  echo "SEC-002: Frontend audit gate triggered ($HIGH HIGH, $CRIT CRITICAL)"
  echo "Vulnerabilities must be resolved before merging."
  exit 1
fi

echo "Audit gate passed."
exit 0

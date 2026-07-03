#!/usr/bin/env bash
# Create the feature PR after: git push -u origin feat/topology-incident-clusters-desktop-packaging
# Requires: brew install gh && gh auth login
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

BRANCH="${1:-feat/topology-incident-clusters-desktop-packaging}"
GH="${GH:-gh}"

if ! command -v "$GH" >/dev/null 2>&1; then
  echo "GitHub CLI not found. Install with: brew install gh" >&2
  exit 1
fi

if ! "$GH" auth status >/dev/null 2>&1; then
  echo "Not logged in. Run: gh auth login" >&2
  exit 1
fi

git fetch origin main
git push -u origin "$BRANCH" 2>/dev/null || git push origin "$BRANCH"

"$GH" pr create --base main --head "$BRANCH" \
  --title "feat: topology map, incident triage, and desktop packaging" \
  --body "$(cat <<'EOF'
## Summary
- **Phase 2.1 — Topology map:** SVG cluster layout (`TopologyMap.jsx`) in Cluster Overview (MA/CA/LEAF hierarchy, resource bars, partition heatmap).
- **Phase 2.2 — Animated gauges:** Health score ring, animated risk bars, detail-panel gauges in Recommendations.
- **Phase 2.3 — Incident clusters + triage:** Superchecker clustering, `GET /api/reports/{id}/triage`, and Recommendations UI (Act Now / Quick Wins / Act Soon / Backlog + incident cluster cards).
- **Phase 4 — Desktop packaging:** PyInstaller spec, Electron builder signing config, `scripts/build-desktop.sh`, portable launchers.
- **Fixes:** Mutually exclusive triage buckets; Python 3.11 union syntax; parser enrichments (THP fallback, MV_NODES aliases, OS metric backfill).

## Test plan
- [x] Backend: `pytest test_server_endpoints.py::TestReportTriage test_superchecker.py test_parsers.py` (127 passed locally)
- [x] Frontend: `npm test && npm run build` (5 passed locally)
- [ ] Upload bundle → verify topology map in Cluster Overview
- [ ] Recommendations → triage buckets + incident cluster filter
- [ ] Optional: `scripts/build-desktop.sh` unsigned build

## Commits
- feat: restore topology map, incident clusters, and desktop packaging
- fix(backend): use native 3.11 union syntax in server.py
- fix(api): make triage buckets mutually exclusive
- feat(frontend): wire triage buckets and incident clusters in Recommendations
- docs: add learned preferences and workspace facts to AGENTS.md
EOF
)"

echo ""
echo "PR created. View with: gh pr view --web"

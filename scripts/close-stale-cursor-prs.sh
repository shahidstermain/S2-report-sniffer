#!/usr/bin/env bash
# Close superseded Cursor bot PRs after the feature branch PR is open.
# Requires: gh auth login
set -euo pipefail

GH="${GH:-gh}"

if ! command -v "$GH" >/dev/null 2>&1; then
  echo "GitHub CLI not found. Install with: brew install gh" >&2
  exit 1
fi

if ! "$GH" auth status >/dev/null 2>&1; then
  echo "Not logged in. Run: gh auth login" >&2
  exit 1
fi

REPO="shahidstermain/S2-report-sniffer"
COMMENT="Superseded by feat/topology-incident-clusters-desktop-packaging (topology map, incident triage, desktop packaging, and related fixes). Closing to reduce PR noise."

echo "Fetching open cursor/* PRs in $REPO..."
PRS=$("$GH" pr list --repo "$REPO" --state open --limit 100 --json number,headRefName \
  --jq '[.[] | select(.headRefName | startswith("cursor/")) | .number] | join(" ")')

if [ -z "$PRS" ]; then
  echo "No open cursor/* PRs found."
  exit 0
fi

set -- $PRS
COUNT=$#
echo "Will close $COUNT PR(s): $PRS"
read -r -p "Continue? [y/N] " ans
if [[ ! "$ans" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

for num in "$@"; do
  echo "Closing #$num..."
  "$GH" pr comment "$num" --repo "$REPO" --body "$COMMENT" 2>/dev/null || true
  "$GH" pr close "$num" --repo "$REPO" --comment "Closed as superseded."
done

echo "Done. Remaining open PRs:"
"$GH" pr list --repo "$REPO" --state open

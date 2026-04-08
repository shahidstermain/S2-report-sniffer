#!/usr/bin/env bash
set -euo pipefail

SECRETS_FILE="$HOME/.trae-secrets.sh"
if [ ! -f "$SECRETS_FILE" ]; then
  echo "Missing $SECRETS_FILE" >&2
  exit 1
fi

source "$SECRETS_FILE"

vars=(
  GITHUB_PERSONAL_ACCESS_TOKEN
  HOSTINGER_API_TOKEN
  MINIMAX_API_KEY
)

for v in "${vars[@]}"; do
  val="${!v-}"
  if [ -n "$val" ]; then
    launchctl setenv "$v" "$val"
  fi
done

open -a "Trae" || open -a "Trae.app"


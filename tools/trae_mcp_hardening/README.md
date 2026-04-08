This directory contains tooling to harden Trae MCP configuration (`mcp.json`) and prevent secret leakage.

## What it enforces
- `mcp.json` must contain **only** the top-level key `mcpServers`.
- For any server with `enabled: true`, `command` must be a non-empty string and `args` must be a non-empty array.
- Secret-like values in `env` must be empty strings (e.g., `*_TOKEN`, `*_KEY`, `*_SECRET`, `*_PASSWORD`).

## Local usage
Validate your live Trae config:

```bash
python3 tools/trae_mcp_hardening/validate_mcp.py \
  --path "$HOME/Library/Application Support/Trae/User/mcp.json" \
  --strict
```

Auto-fix (creates a timestamped backup next to the file):

```bash
python3 tools/trae_mcp_hardening/harden_mcp.py \
  --path "$HOME/Library/Application Support/Trae/User/mcp.json"
```

## Hook install (recommended)
This repo includes a git hook under `.githooks/pre-commit` that blocks staging obvious secret files.
To enable it locally:

```bash
bash tools/trae_mcp_hardening/install-hooks.sh
```

## CI
The unit tests in `tools/trae_mcp_hardening/tests` validate the fixture config and enforce "no secrets".


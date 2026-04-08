import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SECRET_ENV_KEY_RE = re.compile(r"(TOKEN|KEY|SECRET|PASSWORD|PRIVATE|ACCESS)" , re.I)


@dataclass
class ValidationErrorItem:
    code: str
    message: str
    details: dict[str, Any]


def _is_secret_env_key(key: str) -> bool:
    if not key:
        return False
    return bool(SECRET_ENV_KEY_RE.search(key))


def validate_mcp_config(payload: dict[str, Any], *, strict_top_level: bool = True) -> list[ValidationErrorItem]:
    errors: list[ValidationErrorItem] = []

    top_keys = list(payload.keys())
    if strict_top_level:
        extra = [k for k in top_keys if k != "mcpServers"]
        if extra:
            errors.append(
                ValidationErrorItem(
                    code="MCP001",
                    message="mcp.json must contain only top-level key 'mcpServers'",
                    details={"extra_top_level_keys": extra},
                )
            )

    mcp_servers = payload.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        errors.append(
            ValidationErrorItem(
                code="MCP002",
                message="mcpServers must be an object",
                details={"type": type(mcp_servers).__name__},
            )
        )
        return errors

    non_compliant_enabled: list[str] = []
    secrets_found: list[dict[str, str]] = []

    for name, cfg in mcp_servers.items():
        if not isinstance(cfg, dict):
            errors.append(
                ValidationErrorItem(
                    code="MCP003",
                    message="Each mcpServers entry must be an object",
                    details={"server": name, "type": type(cfg).__name__},
                )
            )
            continue

        enabled = cfg.get("enabled") is True
        if enabled:
            cmd = cfg.get("command")
            args = cfg.get("args")
            if not isinstance(cmd, str) or not cmd.strip():
                non_compliant_enabled.append(name)
            elif not isinstance(args, list) or len(args) == 0:
                non_compliant_enabled.append(name)

        env = cfg.get("env")
        if isinstance(env, dict):
            for k, v in env.items():
                if not _is_secret_env_key(str(k)):
                    continue
                if isinstance(v, str) and len(v) > 0:
                    secrets_found.append({"server": name, "key": str(k)})

    if non_compliant_enabled:
        errors.append(
            ValidationErrorItem(
                code="MCP010",
                message="Enabled MCP servers must include non-empty 'command' and non-empty 'args'",
                details={"servers": sorted(set(non_compliant_enabled))},
            )
        )

    if secrets_found:
        errors.append(
            ValidationErrorItem(
                code="MCP020",
                message="Secret-like env values must be empty strings in mcp.json",
                details={"secrets": secrets_found},
            )
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    path = Path(os.path.expanduser(args.path)).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_mcp_config(payload, strict_top_level=args.strict)
    if errors:
        out = {
            "ok": False,
            "errors": [
                {"code": e.code, "message": e.message, "details": e.details}
                for e in errors
            ],
        }
        print(json.dumps(out, indent=2))
        return 1

    print(json.dumps({"ok": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_mcp import validate_mcp_config


SECRET_ENV_KEY_RE = re.compile(r"(TOKEN|KEY|SECRET|PASSWORD|PRIVATE|ACCESS)", re.I)


def _is_secret_env_key(key: str) -> bool:
    if not key:
        return False
    return bool(SECRET_ENV_KEY_RE.search(key))


def harden(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"mcpServers": {}}

    mcp = payload.get("mcpServers")
    if not isinstance(mcp, dict):
        mcp = {}

    hardened: dict[str, Any] = {"mcpServers": {}}

    for name, cfg in mcp.items():
        if not isinstance(cfg, dict):
            continue

        new_cfg = dict(cfg)

        for k in ["transport", "servers", "inputs"]:
            if k in new_cfg:
                del new_cfg[k]

        env = new_cfg.get("env")
        if isinstance(env, dict):
            env2 = dict(env)
            for k, v in env2.items():
                if _is_secret_env_key(str(k)):
                    env2[k] = ""
            new_cfg["env"] = env2

        hardened["mcpServers"][name] = new_cfg

    return hardened


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    args = parser.parse_args()

    path = Path(os.path.expanduser(args.path)).resolve()
    original = json.loads(path.read_text(encoding="utf-8"))
    new_payload = harden(original)

    errors = validate_mcp_config(new_payload, strict_top_level=True)
    if errors:
        print(json.dumps({
            "ok": False,
            "errors": [{"code": e.code, "message": e.message, "details": e.details} for e in errors]
        }, indent=2))
        return 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{ts}")
    shutil.copy2(path, backup)
    path.write_text(json.dumps(new_payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "backup": str(backup)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate the checked-in OpenAPI contract deterministically."""

import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("S2RS_DATA_DIR", tempfile.mkdtemp(prefix="s2rs-openapi-"))

from server import app  # noqa: E402


target = ROOT / "docs" / "api" / "openapi.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(target)

import json
import unittest
from pathlib import Path

from tools.trae_mcp_hardening.validate_mcp import validate_mcp_config


class TestMcpValidation(unittest.TestCase):
    def test_fixture_valid(self):
        fixture = Path(__file__).resolve().parent.parent / "fixtures" / "mcp.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        errors = validate_mcp_config(payload, strict_top_level=True)
        self.assertEqual(errors, [])

    def test_rejects_extra_top_level_keys(self):
        payload = {"mcpServers": {}, "servers": {}}
        errors = validate_mcp_config(payload, strict_top_level=True)
        self.assertTrue(any(e.code == "MCP001" for e in errors))

    def test_enabled_requires_command_and_args(self):
        payload = {"mcpServers": {"A": {"enabled": True, "command": "", "args": []}}}
        errors = validate_mcp_config(payload, strict_top_level=True)
        self.assertTrue(any(e.code == "MCP010" for e in errors))

    def test_secrets_must_be_empty(self):
        payload = {"mcpServers": {"A": {"command": "x", "args": ["y"], "env": {"API_TOKEN": "abc"}}}}
        errors = validate_mcp_config(payload, strict_top_level=True)
        self.assertTrue(any(e.code == "MCP020" for e in errors))


if __name__ == "__main__":
    unittest.main()

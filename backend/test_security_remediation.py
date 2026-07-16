"""Regression tests for SECURITY_REVIEW.md remediation (F1/F2/F7/F10/F14)."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_sec_")

with patch.dict(
    "os.environ",
    {"S2RS_DATA_DIR": TEST_DATA_DIR, "S2RS_DISABLE_GZIP": "1"},
    clear=False,
):
    import server


class TestSecurityHeadersAndRequestId(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def test_security_headers_present(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("x-frame-options"), "DENY")
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("camera=()", r.headers.get("permissions-policy", ""))
        csp = r.headers.get("content-security-policy", "")
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("font-src 'self'", csp)

    def test_request_id_generated(self):
        r = self.client.get("/api/health")
        self.assertTrue(r.headers.get("x-request-id"))

    def test_request_id_echoed(self):
        r = self.client.get("/api/health", headers={"X-Request-ID": "test-req-abc"})
        self.assertEqual(r.headers.get("x-request-id"), "test-req-abc")


class TestCorsWildcardRejected(unittest.TestCase):
    def test_wildcard_cors_env_raises(self):
        with patch.dict(os.environ, {"S2RS_CORS_ORIGINS": "*"}, clear=False):
            with self.assertRaises(ValueError):
                server._get_cors_origins()


class TestOriginCheck(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def test_mutating_cross_origin_forbidden(self):
        r = self.client.post(
            "/api/reports/import",
            json={"path": "/tmp"},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"], "origin_forbidden")

    def test_mutating_loopback_origin_allowed(self):
        r = self.client.post(
            "/api/reports/import",
            json={"path": "/tmp/does-not-exist"},
            headers={"Origin": "http://127.0.0.1:8000"},
        )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        self.assertNotEqual(body.get("error"), "origin_forbidden")
        self.assertIn(r.status_code, {400, 403, 404, 501})

    def test_get_ignores_cross_origin(self):
        r = self.client.get("/api/health", headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 200)


class TestRedactSensitive(unittest.TestCase):
    def test_redacts_home_paths(self):
        out = server._redact_sensitive("failed reading /Users/alice/secret/report.zip")
        self.assertNotIn("/Users/alice", out)
        self.assertIn("[path]", out)


if __name__ == "__main__":
    unittest.main()

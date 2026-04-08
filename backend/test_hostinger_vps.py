import unittest
import tempfile
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient


TEST_DATA_DIR = tempfile.mkdtemp(prefix="s2rs_test_")


with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR}):
    from server import app


class TestHostingerVpsVmList(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_missing_token_returns_503(self):
        with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR}, clear=False):
            r = self.client.get("/api/hostinger/vps/virtual-machines")
        self.assertEqual(r.status_code, 503)

    def test_unauthorized_returns_401(self):
        fake_response = type("Resp", (), {"status_code": 401, "json": lambda self: {"message": "Unauthenticated."}, "text": ""})()
        async_client_mock = AsyncMock()
        async_client_mock.__aenter__.return_value = async_client_mock
        async_client_mock.get.return_value = fake_response
        with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR, "HOSTINGER_API_TOKEN": "test"}, clear=False):
            with patch("server.httpx.AsyncClient", return_value=async_client_mock):
                r = self.client.get("/api/hostinger/vps/virtual-machines?page=1")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"]["error"], "Unauthorized")

    def test_rate_limit_returns_429(self):
        fake_response = type("Resp", (), {"status_code": 429, "json": lambda self: {"message": "Too many requests"}, "text": ""})()
        async_client_mock = AsyncMock()
        async_client_mock.__aenter__.return_value = async_client_mock
        async_client_mock.get.return_value = fake_response
        with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR, "HOSTINGER_API_TOKEN": "test"}, clear=False):
            with patch("server.httpx.AsyncClient", return_value=async_client_mock):
                r = self.client.get("/api/hostinger/vps/virtual-machines?page=1")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["detail"]["error"], "Too Many Requests")

    def test_timeout_returns_504(self):
        import httpx
        async_client_mock = AsyncMock()
        async_client_mock.__aenter__.return_value = async_client_mock
        async_client_mock.get.side_effect = httpx.TimeoutException("timeout")
        with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR, "HOSTINGER_API_TOKEN": "test"}, clear=False):
            with patch("server.httpx.AsyncClient", return_value=async_client_mock):
                r = self.client.get("/api/hostinger/vps/virtual-machines?page=1")
        self.assertEqual(r.status_code, 504)
        self.assertEqual(r.json()["detail"]["error"], "Gateway Timeout")

    def test_success_returns_payload(self):
        fake_response = type(
            "Resp",
            (),
            {"status_code": 200, "json": lambda self: {"data": [{"id": 1, "state": "running"}]}, "text": ""},
        )()

        async_client_mock = AsyncMock()
        async_client_mock.__aenter__.return_value = async_client_mock
        async_client_mock.get.return_value = fake_response

        with patch.dict("os.environ", {"S2RS_DATA_DIR": TEST_DATA_DIR, "HOSTINGER_API_TOKEN": "test"}, clear=False):
            with patch("server.httpx.AsyncClient", return_value=async_client_mock):
                r = self.client.get("/api/hostinger/vps/virtual-machines?page=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"][0]["state"], "running")


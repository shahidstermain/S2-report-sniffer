from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlparse

import httpx


def require_loopback_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Local model URL must be an HTTP(S) loopback URL")
    host = parsed.hostname.lower()
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback:
        raise ValueError("Remote model endpoints are forbidden by local-first policy")
    return url.rstrip("/")


class OllamaProvider:
    def __init__(self, url: str, model: str, timeout_seconds: float = 180) -> None:
        self.url = require_loopback_url(url)
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate(self, *, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.post(
                f"{self.url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            body = response.json()
        generated = body.get("response")
        if not isinstance(generated, str):
            raise ValueError("Local model returned no response")
        parsed = json.loads(generated)
        if not isinstance(parsed, dict):
            raise ValueError("Local model response must be a JSON object")
        return parsed

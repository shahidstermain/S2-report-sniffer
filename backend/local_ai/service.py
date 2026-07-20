from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import LocalAiResult
from .prompts import render_prompt
from .providers import OllamaProvider, require_loopback_url


class LocalAiDisabled(RuntimeError):
    pass


def _enabled() -> bool:
    return os.environ.get("S2RS_LOCAL_AI_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


class LocalAiService:
    def status(self) -> dict[str, Any]:
        url = os.environ.get("S2RS_OLLAMA_URL", "http://127.0.0.1:11434")
        return {
            "enabled": _enabled(),
            "provider": "ollama",
            "model": os.environ.get("S2RS_LOCAL_AI_MODEL", ""),
            "endpoint": require_loopback_url(url),
            "local_only": True,
        }

    @staticmethod
    def _bounded_findings(payload: dict[str, Any]) -> tuple[list[dict], set[str], set[str]]:
        max_findings = _bounded_env_int("S2RS_LOCAL_AI_MAX_FINDINGS", 20, 1, 50)
        max_evidence = _bounded_env_int(
            "S2RS_LOCAL_AI_MAX_EVIDENCE_CHARS", 20_000, 1_000, 100_000
        )
        selected: list[dict] = []
        finding_ids: set[str] = set()
        evidence_ids: set[str] = set()
        used = 0
        order = {"critical": 0, "warning": 1, "info": 2}
        findings = sorted(
            payload.get("recommendations") or [],
            key=lambda row: order.get(str(row.get("severity")), 3),
        )
        for index, finding in enumerate(findings[:max_findings]):
            finding_id = str(finding.get("id") or finding.get("checker_id") or f"finding-{index}")
            evidence_id = f"{finding_id}:evidence"
            evidence = str(finding.get("evidence") or "")
            remaining = max(0, max_evidence - used)
            evidence = evidence[:remaining]
            used += len(evidence)
            finding_ids.add(finding_id)
            evidence_ids.add(evidence_id)
            selected.append({
                "finding_id": finding_id,
                "evidence_id": evidence_id,
                "severity": finding.get("severity"),
                "basis": finding.get("basis"),
                "title": finding.get("title"),
                "description": finding.get("description"),
                "evidence": evidence,
                "remediation": finding.get("remediation"),
            })
        return selected, finding_ids, evidence_ids

    async def generate(
        self,
        payload: dict[str, Any],
        *,
        audience: str = "support engineers",
        incident_context: str = "",
        template_path: Path | None = None,
    ) -> LocalAiResult:
        if not _enabled():
            raise LocalAiDisabled("Local AI is disabled")
        findings, valid_findings, valid_evidence = self._bounded_findings(payload)
        prompt = render_prompt(
            findings,
            audience=audience,
            incident_context=incident_context,
            template_path=template_path,
        )
        provider = OllamaProvider(
            os.environ.get("S2RS_OLLAMA_URL", "http://127.0.0.1:11434"),
            os.environ.get("S2RS_LOCAL_AI_MODEL", "qwen2.5:7b-instruct"),
        )
        result = LocalAiResult.model_validate(
            await provider.generate(prompt=prompt, schema=LocalAiResult.model_json_schema())
        )
        for hypothesis in result.hypotheses:
            if not set(hypothesis.supporting_finding_ids) <= valid_findings:
                raise ValueError("Local model cited an unknown finding")
            if not set(hypothesis.supporting_evidence_ids) <= valid_evidence:
                raise ValueError("Local model cited unknown evidence")
        return result

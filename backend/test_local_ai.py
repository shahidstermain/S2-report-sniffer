import asyncio

import pytest

from local_ai.models import LocalAiResult
from local_ai.providers import require_loopback_url
from local_ai.service import LocalAiDisabled, LocalAiService


def test_provider_rejects_remote_endpoints():
    with pytest.raises(ValueError, match="Remote model endpoints"):
        require_loopback_url("https://models.example.com")
    assert require_loopback_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert require_loopback_url("http://[::1]:11434") == "http://[::1]:11434"


def test_local_ai_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("S2RS_LOCAL_AI_ENABLED", raising=False)
    with pytest.raises(LocalAiDisabled):
        asyncio.run(LocalAiService().generate({"recommendations": []}))


def test_evidence_selection_is_bounded_and_prioritized(monkeypatch):
    monkeypatch.setenv("S2RS_LOCAL_AI_MAX_FINDINGS", "2")
    monkeypatch.setenv("S2RS_LOCAL_AI_MAX_EVIDENCE_CHARS", "1000")
    payload = {
        "recommendations": [
            {"id": "info", "severity": "info", "evidence": "i"},
            {"id": "critical", "severity": "critical", "evidence": "c" * 2000},
            {"id": "warning", "severity": "warning", "evidence": "w"},
        ]
    }
    selected, finding_ids, evidence_ids = LocalAiService._bounded_findings(payload)
    assert [row["finding_id"] for row in selected] == ["critical", "warning"]
    assert sum(len(row["evidence"]) for row in selected) <= 1000
    assert finding_ids == {"critical", "warning"}
    assert evidence_ids == {"critical:evidence", "warning:evidence"}


def test_structured_result_forbids_unknown_fields():
    with pytest.raises(ValueError):
        LocalAiResult.model_validate({"summary": "x", "unexpected": True})

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RootCauseHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    confidence: Literal["low", "medium", "high"]
    supporting_finding_ids: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)


class LocalAiResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    hypotheses: list[RootCauseHypothesis] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Locally generated hypotheses are not a verified SingleStore diagnosis."
    )

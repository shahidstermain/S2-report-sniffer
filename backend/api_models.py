"""Typed public API contracts.

Saved reports contain compatibility fields from multiple releases. Response
models therefore allow additional properties while strongly typing the stable
envelope used by the desktop and web clients.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompatibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ApiError(CompatibleModel):
    error: str
    message: str | None = None
    detail: Any | None = None


class Progress(CompatibleModel):
    stage: str
    pct: int = Field(ge=0, le=100)
    message: str
    nodes_discovered: int = 0
    files_processed: int = 0
    log_lines_indexed: int = 0


class UploadResponse(CompatibleModel):
    id: UUID
    status: Literal["processing"]
    file_size: int = Field(ge=0)
    detected_format: str
    anonymized: bool
    message: str


class ReportStatusResponse(CompatibleModel):
    id: UUID | None = None
    status: Literal["queued", "processing", "ready", "error"]
    progress: Progress | None = None
    error: str | None = None


class LogMatch(CompatibleModel):
    timestamp: str = ""
    severity: str = ""
    hostname: str = ""
    source: str = ""
    message: str = ""
    line: str = ""
    line_number: int | None = None
    context_before: list[str] = Field(default_factory=list)
    context_after: list[str] = Field(default_factory=list)


class LogSearchParams(CompatibleModel):
    keyword: str
    regex: bool
    severity: str | None = None
    case_sensitive: bool


class LogSearchResponse(CompatibleModel):
    matches: list[LogMatch]
    total: int = Field(ge=0)
    nodes_searched: int = Field(ge=0)
    truncated: bool
    search_mode: Literal["raw", "parsed"]
    search_params: LogSearchParams


class LocalAiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audience: str = Field(default="support engineers", max_length=200)
    incident_context: str = Field(default="", max_length=4000)
    template_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")

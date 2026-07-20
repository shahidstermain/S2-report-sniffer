from __future__ import annotations

import json
from pathlib import Path
from string import Template


DEFAULT_TEMPLATE = """You are drafting a local analysis of a SingleStore Cluster Report.

Rules:
- Treat Sniffer heuristics as heuristics, not official SingleStore conclusions.
- Do not invent measurements, causes, or remediation.
- Cite a supplied finding_id and evidence_id for every material hypothesis.
- Separate observations from hypotheses and state missing evidence.
- Return JSON matching the supplied schema and no other text.

Audience: $audience
Incident context: $incident_context
Findings and bounded evidence:
$findings_json
"""


def load_template(template_path: Path | None = None) -> Template:
    if template_path is None:
        return Template(DEFAULT_TEMPLATE)
    text = template_path.read_text(encoding="utf-8")
    if template_path.stat().st_size > 100_000:
        raise ValueError("Prompt template exceeds 100 KB")
    return Template(text)


def render_prompt(
    findings: list[dict], *, audience: str, incident_context: str, template_path: Path | None
) -> str:
    return load_template(template_path).substitute(
        audience=audience[:200],
        incident_context=incident_context[:4000] or "Not supplied",
        findings_json=json.dumps(findings, ensure_ascii=False),
    )

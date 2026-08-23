"""Guided/Demo mode glossary: what a visible metric means and how it is derived.

KPI copy is owned here. Finding copy is derived from the grounding registry so a
new checker with GROUNDING is explained automatically. Unknown targets fail closed.
"""

from __future__ import annotations

from grounding import GENERIC_DOC_LINKS, GROUNDING, get_grounding, resolve_doc_link

DOCUMENTED = "documented"
TOOLBOX = "toolbox-default"
HEURISTIC = "heuristic"
OBSERVED = "observed"

BASIS_LABELS = {
    DOCUMENTED: "Documented",
    TOOLBOX: "Toolbox default",
    HEURISTIC: "Heuristic (Sniffer, not a SingleStore requirement)",
    OBSERVED: "Observed",
}

UNKNOWN_EXPLAINER = {
    "id": "unknown",
    "kind": "unknown",
    "meaning": "No derivation is registered for this control.",
    "derivation": "Guided/Demo mode only explains catalogued KPIs and findings that carry grounding metadata. It does not invent a formula.",
    "basis": OBSERVED,
    "basis_label": BASIS_LABELS[OBSERVED],
    "criterion": "",
    "source": "",
    "collectors": [],
}

KPI_GLOSSARY: dict[str, dict] = {
    "health_score": {
        "meaning": "Sniffer Finding Severity Index for this report — not cluster vitals or engine health.",
        "derivation": "health = max(0, 100 − risk). Risk = min(100, critical_findings × 15 + warning_findings × 5). Info findings do not reduce the index.",
        "basis": HEURISTIC,
        "criterion": "Sniffer-owned scoring of finding severities in the recommendations list.",
        "source": "",
        "collectors": ["recommendations", "superchecker"],
    },
    "cluster_risk_score": {
        "meaning": "Sniffer finding-risk counterpart of the Finding Severity Index.",
        "derivation": "risk = min(100, critical_findings × 15 + warning_findings × 5). Info findings do not add risk.",
        "basis": HEURISTIC,
        "criterion": "Same formula as the Finding Severity Index, inverted.",
        "source": "",
        "collectors": ["recommendations", "superchecker"],
    },
    "health_grade": {
        "meaning": "Letter grade of the Sniffer Finding Severity Index, not a SingleStore cluster grade.",
        "derivation": "A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, otherwise F, applied to health_score.",
        "basis": HEURISTIC,
        "criterion": "Letter buckets defined by Sniffer, not by SingleStore docs.",
        "source": "",
        "collectors": ["recommendations", "superchecker"],
    },
    "node_count": {
        "meaning": "Number of hosts/nodes discovered in this sdb-report bundle.",
        "derivation": "Counted from parsed node directories / MV_NODES rows in the bundle. Missing collectors can under-count.",
        "basis": OBSERVED,
        "criterion": "Presence of node folders or MV_NODES in the report archive.",
        "source": "",
        "collectors": ["MV_NODES", "node directories"],
    },
    "engine_version": {
        "meaning": "SingleStore engine version reported for the cluster in this bundle.",
        "derivation": "Taken from cluster overview / MV_NODES version fields in the report payload.",
        "basis": OBSERVED,
        "criterion": "Version strings present in the collected cluster metadata.",
        "source": "",
        "collectors": ["MV_NODES", "cluster_overview"],
    },
    "recommendation_count": {
        "meaning": "How many Sniffer findings (recommendations) fired for this report.",
        "derivation": "Length of the recommendations list produced by the superchecker.",
        "basis": OBSERVED,
        "criterion": "Each checker that fires appends one finding.",
        "source": "",
        "collectors": ["superchecker"],
    },
    "finding_severity": {
        "meaning": "Severity assigned to this finding by Sniffer (critical, warning, or info).",
        "derivation": "Checker-specific rules. Critical and warning affect the Finding Severity Index; info does not.",
        "basis": HEURISTIC,
        "criterion": "Severity is a Sniffer classification unless the checker cites a Toolbox/docs rule.",
        "source": "",
        "collectors": ["superchecker"],
    },
    "finding_title": {
        "meaning": "Human-readable summary of a superchecker finding.",
        "derivation": "Generated from the checker that fired; hover the finding body for formula, evidence class, and docs.",
        "basis": OBSERVED,
        "criterion": "Title text from the checker implementation.",
        "source": "",
        "collectors": ["superchecker"],
    },
    "guided_mode": {
        "meaning": "When on, hover or focus any dashed control to see meaning, derivation, and evidence class.",
        "derivation": "Client preference stored in this browser. Default is off so production review stays uncluttered.",
        "basis": OBSERVED,
        "criterion": "UI-only; does not change analysis results.",
        "source": "",
        "collectors": [],
    },
    "glean_packet": {
        "meaning": "A whole-report Markdown incident packet plus a suggested Glean Chat prompt, for manual handoff into Glean.",
        "derivation": "Built locally from this report's triage overview, capacity/replication snapshot, top grounded findings, incident clusters, suspected log lines, and doc links. Nothing is sent anywhere until you attach the file in Glean Chat yourself.",
        "basis": OBSERVED,
        "criterion": "Packet content is a direct serialization of the current report payload; no new analysis is computed.",
        "source": "",
        "collectors": ["investigation"],
    },
    "glean_setup": {
        "meaning": "First-run guided setup that saves your Glean host for chat deep-links and walks through the optional Cursor Glean connector.",
        "derivation": "The host you enter is validated and stored in this browser only (localStorage). The Cursor connector step is instructional; the app cannot verify IDE-side authentication.",
        "basis": OBSERVED,
        "criterion": "UI convenience only; no credentials are collected and no network calls are made by the app.",
        "source": "",
        "collectors": [],
    },
}


def _safe_source(url: str) -> str:
    value = (url or "").strip()
    if value in GENERIC_DOC_LINKS:
        return ""
    return value


def _pack(explainer_id: str, kind: str, meaning: str, derivation: str, basis: str,
          criterion: str, source: str, collectors: list[str] | None = None) -> dict:
    basis = basis if basis in BASIS_LABELS else OBSERVED
    return {
        "id": explainer_id,
        "kind": kind,
        "meaning": meaning,
        "derivation": derivation,
        "basis": basis,
        "basis_label": BASIS_LABELS[basis],
        "criterion": criterion or "",
        "source": _safe_source(source),
        "collectors": list(collectors or []),
    }


def explainer_for_kpi(kpi_id: str) -> dict:
    entry = KPI_GLOSSARY.get(kpi_id)
    if not entry:
        unknown = dict(UNKNOWN_EXPLAINER)
        unknown["id"] = kpi_id
        unknown["kind"] = "kpi"
        return unknown
    return _pack(
        kpi_id,
        "kpi",
        entry["meaning"],
        entry["derivation"],
        entry["basis"],
        entry["criterion"],
        entry.get("source", ""),
        entry.get("collectors"),
    )


def explainer_for_checker(checker_id: str) -> dict:
    checker_id = (checker_id or "").strip()
    if not checker_id:
        return dict(UNKNOWN_EXPLAINER)
    grounding = get_grounding(checker_id)
    registered = checker_id in GROUNDING or checker_id.startswith("pressureEvents_")
    meaning = (
        f"Sniffer finding '{checker_id}'. The evidence class below says whether "
        "the rule is documented, a Toolbox default, a heuristic, or observed."
    )
    if not registered and grounding.get("basis") == OBSERVED:
        # Dynamic pressure events still have an honest default; unknown names fail closed.
        if not checker_id.startswith("pressureEvents_"):
            unknown = dict(UNKNOWN_EXPLAINER)
            unknown["id"] = checker_id
            unknown["kind"] = "finding"
            return unknown
    derivation = grounding.get("criterion") or "Derived from report evidence; no extra formula is published."
    return _pack(
        checker_id,
        "finding",
        meaning,
        derivation,
        grounding.get("basis", OBSERVED),
        grounding.get("criterion", ""),
        resolve_doc_link(checker_id, grounding.get("source", "")),
        ["superchecker", "sdb-report collectors"],
    )


def card_from_finding(finding: dict) -> dict:
    """Prefer live finding grounding (evidence, basis) over static copy."""
    if not isinstance(finding, dict):
        return dict(UNKNOWN_EXPLAINER)
    checker_id = str(finding.get("checker_id") or "").strip()
    base = explainer_for_checker(checker_id) if checker_id else dict(UNKNOWN_EXPLAINER)
    live = finding.get("grounding") if isinstance(finding.get("grounding"), dict) else {}
    if live:
        basis = live.get("basis") or base["basis"]
        if basis not in BASIS_LABELS:
            basis = OBSERVED
        base["basis"] = basis
        base["basis_label"] = BASIS_LABELS[basis]
        if live.get("criterion"):
            base["criterion"] = live["criterion"]
            base["derivation"] = live["criterion"]
        base["source"] = _safe_source(resolve_doc_link(checker_id, live.get("source") or finding.get("doc_link") or ""))
    evidence = str(finding.get("evidence") or "").strip()
    if evidence:
        base["derivation"] = (
            f"{base['derivation']} Evidence from this report: {evidence}"
            if base.get("derivation") else f"Evidence from this report: {evidence}"
        )
    title = str(finding.get("title") or "").strip()
    if title:
        base["meaning"] = title
    return base


def build_explainers_catalog() -> dict:
    kpis = {kpi_id: explainer_for_kpi(kpi_id) for kpi_id in KPI_GLOSSARY}
    findings = {checker_id: explainer_for_checker(checker_id) for checker_id in GROUNDING}
    return {
        "kpis": kpis,
        "findings": findings,
        "unknown": dict(UNKNOWN_EXPLAINER),
        "basis_labels": dict(BASIS_LABELS),
    }


def resolve_explainer(explainer_id: str) -> dict:
    explainer_id = (explainer_id or "").strip()
    if explainer_id in KPI_GLOSSARY:
        return explainer_for_kpi(explainer_id)
    if explainer_id:
        return explainer_for_checker(explainer_id)
    return dict(UNKNOWN_EXPLAINER)

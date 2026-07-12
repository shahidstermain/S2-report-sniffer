"""Shared Export JSON fixture matching Recommendations → Export JSON shape."""

from __future__ import annotations

from typing import Any


def build_export_json_fixture() -> dict[str, Any]:
    """Build a representative superchecker Export JSON payload for RCA tests."""
    fix_first_checkers = [
        ("runawayQueries", "critical", "Query"),
        ("maxOpenFiles", "critical", "Configuration"),
        ("missingClusterDb", "critical", "Availability"),
        ("tracelogOOM", "critical", "Memory"),
        ("unmappedMasterPartitions", "critical", "Availability"),
        ("userDatabaseRedundancy", "critical", "Replication"),
    ]
    extra_checkers = [
        ("vmOvercommit", "warning", "Memory"),
        ("swapUsage", "warning", "Memory"),
    ]

    recommendations: list[dict[str, Any]] = []
    link_idx = 0
    for i, (checker_id, severity, category) in enumerate(
        fix_first_checkers + extra_checkers, start=1
    ):
        link_idx += 1
        doc_link = f"https://docs.singlestore.com/db/v9.1/topic/{checker_id}/"
        grounding_src = f"https://docs.singlestore.com/db/v9.1/grounding/{checker_id}/"
        recommendations.append(
            {
                "id": i,
                "checker_id": checker_id,
                "severity": severity,
                "category": category,
                "title": f"{checker_id} finding title",
                "description": f"Description for {checker_id}",
                "evidence": (
                    "Low nofile on: 10.251.0.35=524288"
                    if checker_id == "maxOpenFiles"
                    else f"evidence for {checker_id}"
                ),
                "remediation": f"Remediation steps for {checker_id}",
                "doc_link": doc_link,
                "grounding": {
                    "basis": "documented",
                    "source": grounding_src,
                    "criterion": f"Criterion for {checker_id}",
                },
                "nodes": ["10.251.0.102"],
                "risk_score": 100,
                "confidence": 0.98,
                "priority_tags": ["availability", "memory", "query"],
                "triage": {
                    "impact": "outage-risk",
                    "effort": "high",
                    "blast_radius": "cluster-wide",
                    "quick_win": checker_id == "maxOpenFiles",
                    "priority": 1,
                    "recommended_action": f"Fix {checker_id}",
                },
                "fix_first": checker_id in {c[0] for c in fix_first_checkers},
            }
        )

    # Pad to 22 unique doc URLs (11 checkers × doc_link + grounding.source)
    while link_idx < 11:
        link_idx += 1
        recommendations.append(
            {
                "id": 100 + link_idx,
                "checker_id": f"extraChecker{link_idx}",
                "severity": "info",
                "category": "Other",
                "title": "Extra doc link",
                "doc_link": f"https://docs.singlestore.com/db/v9.1/extra/{link_idx}/",
                "grounding": {
                    "source": f"https://docs.singlestore.com/db/v9.1/extra-grounding/{link_idx}/"
                },
                "fix_first": False,
            }
        )

    member_ids = [r["id"] for r in recommendations[:29]]

    return {
        "recommendations": recommendations,
        "triage": {
            "report_id": "3f1beca7-7533-4850-b107-46185cd86848",
            "report_name": "report-2026-06-20T164721.tar.gz",
            "health_score": "critical",
            "summary": {
                "total_findings": 29,
                "quick_wins": 13,
                "act_now": 10,
                "incident_clusters": 1,
            },
            "incident_clusters": [
                {
                    "cluster_id": "INC-001",
                    "root_cause_checker_id": "runawayQueries",
                    "root_cause_title": "Runaway queries detected (151)",
                    "summary": (
                        "29 findings related to availability, configuration, data-loss on "
                        "10.251.0.102, 10.251.0.104"
                    ),
                    "member_ids": member_ids,
                    "member_count": len(member_ids),
                    "max_risk_score": 100,
                    "dominant_severity": "critical",
                    "tags": [
                        "availability",
                        "configuration",
                        "memory",
                        "query",
                        "replication",
                    ],
                    "nodes": [
                        "10.251.0.102",
                        "10.251.0.104",
                        "10.251.0.35",
                    ],
                }
            ],
        },
        "cluster_overview": {"version": "8.7.4"},
    }

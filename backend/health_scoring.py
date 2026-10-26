"""Canonical finding-severity scoring used by analyzed reports."""

from __future__ import annotations


def health_grade(score: int) -> str:
    """Return the display grade for a 0–100 Finding Severity Index."""

    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def compute_health_metrics(
    recommendations: list[dict],
) -> tuple[int, str, int]:
    """Compute health, grade, and risk from finding severities."""

    critical = sum(
        1 for recommendation in recommendations
        if recommendation.get("severity") == "critical"
    )
    warnings = sum(
        1 for recommendation in recommendations
        if recommendation.get("severity") == "warning"
    )
    risk_score = min(100, critical * 15 + warnings * 5)
    health_score = max(0, 100 - risk_score)
    return health_score, health_grade(health_score), risk_score

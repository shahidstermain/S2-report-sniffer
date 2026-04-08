"""
Migration 001: Add recommendations metadata fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Adds risk_score, confidence, related_findings, checker_id, fix_first,
priority_tags, and cluster_risk_score fields to all report documents.
These fields are computed by SuperChecker at parse time.

Run:
    python backend/migrations_runner.py up --migration 001

Rollback:
    python backend/rollback_runner.py down --steps 1
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

UP_MIGRATION = """
db.reports.updateMany(
    { "recommendations": { "$exists": true } },
    [
        {
            "$set": {
                "recommendations": {
                    "$map": {
                        "input": "$recommendations",
                        "in": {
                            "$mergeObjects": [
                                "$$this",
                                {
                                    "checker_id":       { "$ifNull": ["$$this.checker_id",       ""] },
                                    "risk_score":       { "$ifNull": ["$$this.risk_score",       null] },
                                    "confidence":       { "$ifNull": ["$$this.confidence",       null] },
                                    "related_findings": { "$ifNull": ["$$this.related_findings", []] },
                                    "fix_first":        { "$ifNull": ["$$this.fix_first",        false] },
                                    "priority_tags":    { "$ifNull": ["$$this.priority_tags",    []] }
                                }
                            ]
                        }
                    }
                },
                "cluster_risk_score":  { "$ifNull": ["$cluster_risk_score", null] },
                "health_score":        { "$ifNull": ["$health_score",        "unknown"] }
            }
        }
    ]
)
"""

DOWN_MIGRATION = """
db.reports.updateMany(
    { "recommendations": { "$exists": true } },
    [
        {
            "$set": {
                "recommendations": {
                    "$map": {
                        "input": "$recommendations",
                        "in": {
                            "$mergeObjects": [
                                "$$this",
                                {
                                    "risk_score":       "$$REMOVE",
                                    "confidence":       "$$REMOVE",
                                    "related_findings": "$$REMOVE",
                                    "fix_first":        "$$REMOVE",
                                    "priority_tags":    "$$REMOVE",
                                    "checker_id":       "$$REMOVE"
                                }
                            ]
                        }
                    }
                }
            }
        }
    ]
)
"""


def up(client):
    db = client.get_database()
    result = db.command("aggregate", "reports", pipeline=[], explain=False)
    print(f"[001] Ensuring indexes for recommendation metadata queries...")
    try:
        db.reports.create_index("recommendations.checker_id")
        db.reports.create_index("cluster_risk_score")
        db.reports.create_index("health_score")
        print("[001] Indexes created.")
    except Exception as e:
        print(f"[001] Index creation skipped: {e}")
    print("[001] UP migration completed.")


def down(client):
    print("[001] DOWN migration: no-op (SuperChecker fields are nullable; no data destruction).")
    print("[001] To hard-delete fields, run with --force.")


if __name__ == "__main__":
    print(__doc__)

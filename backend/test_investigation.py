"""Tests for cluster-centric investigation helpers and Glean packet builder."""

import unittest

from investigation import (
    EXTRA_CHECKER_MAPPINGS,
    build_glean_packet,
    build_in_app_actions,
    build_investigation_bundle,
    dedupe_preserve_order,
    enrich_incident_clusters_with_logs,
    extract_known_doc_links,
    normalize_export_json_payload,
    resolve_cluster_theme,
    resolve_finding_type,
    resolve_incident_clusters,
    resolve_log_search_keywords,
)
from test_export_json_fixture import build_export_json_fixture


SAMPLE_PAYLOAD = {
    "cluster_overview": {"version": "9.0.24", "cluster_name": "prod-cluster"},
    "incident_clusters": [
        {
            "cluster_id": "INC-001",
            "root_cause_checker_id": "memoryUtilizationCritical",
            "root_cause_title": "Memory utilization critical on leaf-1",
            "summary": "3 findings related to memory on leaf-1",
            "member_ids": ["1", "2"],
            "member_count": 2,
            "tags": ["memory", "performance"],
            "nodes": ["leaf-1"],
            "dominant_severity": "critical",
            "max_risk_score": 88,
        }
    ],
    "recommendations": [
        {
            "id": "1",
            "checker_id": "memoryUtilizationCritical",
            "severity": "critical",
            "title": "Memory utilization critical on leaf-1",
            "description": "Node exceeded 90% memory utilization.",
            "evidence": "utilization_pct=92.1",
            "category": "Memory",
            "nodes": ["leaf-1"],
            "priority_tags": ["memory"],
        },
        {
            "id": "2",
            "checker_id": "swapUsage",
            "severity": "warning",
            "title": "Swap activity detected on leaf-1",
            "description": "Swap in use indicates memory pressure.",
            "evidence": "swap_used_pct=8.2%",
            "category": "Memory",
            "nodes": ["leaf-1"],
            "priority_tags": ["memory"],
        },
    ],
    "log_summary": {"severity_counts": {"ERROR": 2, "WARN": 50}, "total": 1000},
    "detected_log_patterns": [{
        "title": "OOM Kill Detected",
        "category": "oom",
        "count": 2,
        "severity": "critical",
        "sample": "Out of memory: Kill process 1234 (memsqld)",
        "nodes": ["leaf-1"],
        "first_seen": "2024-01-01 10:00:00",
        "last_seen": "2024-01-01 10:05:00",
    }],
    "logs": [
        {
            "timestamp": "2024-01-01 10:00:01",
            "hostname": "leaf-1.example.com",
            "severity": "ERROR",
            "message": "Out of memory: Kill process 1234 (memsqld)",
        },
        {
            "timestamp": "2024-01-01 10:00:02",
            "hostname": "leaf-2.example.com",
            "severity": "ERROR",
            "message": "Unrelated error on another node",
        },
    ],
    "memory_utilization": {
        "cluster_summary": {"status": "critical", "nodes_over_90_pct": 1},
    },
}


class TestInvestigationBundle(unittest.TestCase):
    def test_build_bundle_from_cluster(self):
        bundle = build_investigation_bundle(
            "00000000-0000-0000-0000-000000000001",
            SAMPLE_PAYLOAD,
            cluster_id="INC-001",
        )
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(bundle.cluster_id, "INC-001")
        self.assertEqual(bundle.theme, "memory")
        self.assertEqual(len(bundle.findings), 2)
        self.assertIn("leaf-1", bundle.affected_nodes)
        self.assertEqual(bundle.version, "9.0.24")
        self.assertGreater(bundle.log_context.get("summary", {}).get("excerpt_count", 0), 0)
        self.assertIn("cluster_log_excerpts", bundle.report_signals)

    def test_build_bundle_from_single_finding(self):
        bundle = build_investigation_bundle(
            "00000000-0000-0000-0000-000000000001",
            SAMPLE_PAYLOAD,
            finding_id="swapUsage",
        )
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(len(bundle.findings), 1)
        self.assertEqual(bundle.findings[0].id, "swapUsage")

    def test_resolve_cluster_theme_from_tags(self):
        self.assertEqual(resolve_cluster_theme(["memory", "performance"]), "memory")
        self.assertEqual(resolve_cluster_theme(["replication"]), "replication")

    def test_resolve_cluster_theme_prefers_root_cause_over_tags(self):
        self.assertEqual(
            resolve_cluster_theme(["availability"], "runawayQueries"),
            "query",
        )
        self.assertEqual(
            resolve_cluster_theme(["memory"], "replicationLagCritical"),
            "replication",
        )

    def test_extra_checker_mappings(self):
        self.assertIn("transparentHugepage", EXTRA_CHECKER_MAPPINGS)
        self.assertEqual(resolve_finding_type(checker_id="transparentHugepage"), "memory_pressure")
        self.assertEqual(resolve_finding_type(checker_id="pressureEvents_etimedout"), "partition_availability")


class TestIncidentClusterLogContext(unittest.TestCase):
    def test_enrich_incident_clusters_with_logs_scopes_to_cluster_nodes(self):
        enriched = enrich_incident_clusters_with_logs(
            SAMPLE_PAYLOAD["incident_clusters"],
            SAMPLE_PAYLOAD,
        )
        self.assertEqual(len(enriched), 1)
        log_ctx = enriched[0]["log_context"]
        self.assertGreater(log_ctx["summary"]["pattern_count"], 0)
        self.assertGreater(log_ctx["summary"]["excerpt_count"], 0)
        messages = " ".join(e["message"] for e in log_ctx["excerpts"])
        self.assertIn("Out of memory", messages)
        self.assertNotIn("Unrelated error", messages)

    def test_resolve_incident_clusters_enriches_when_missing(self):
        payload = dict(SAMPLE_PAYLOAD)
        payload["incident_clusters"] = [dict(SAMPLE_PAYLOAD["incident_clusters"][0])]
        resolved = resolve_incident_clusters(payload)
        self.assertIn("log_context", resolved[0])
        self.assertGreater(resolved[0]["log_context"]["summary"]["excerpt_count"], 0)

    def test_build_glean_packet_includes_suspected_logs_and_prompt(self):
        packet = build_glean_packet(
            SAMPLE_PAYLOAD,
            report_id="00000000-0000-0000-0000-000000000001",
        )
        self.assertEqual(packet["filename"], "s2rs-incident-packet-00000000.md")
        self.assertIn("Suggested Glean prompt", packet["markdown"])
        self.assertIn("Suspected log lines", packet["markdown"])
        self.assertIn("Out of memory", packet["markdown"])
        self.assertIn("OOM Kill Detected", packet["markdown"])
        self.assertIn("Memory utilization critical", packet["markdown"])
        self.assertIn("attach", packet["prompt"].lower())
        self.assertIn("INC-001", packet["markdown"])


class TestExportJsonPipeline(unittest.TestCase):
    def setUp(self):
        self.export_payload = build_export_json_fixture()
        self.report_id = "3f1beca7-7533-4850-b107-46185cd86848"

    def test_normalize_export_json_payload_lifts_incident_clusters(self):
        normalized = normalize_export_json_payload(self.export_payload)
        self.assertEqual(len(normalized["incident_clusters"]), 1)
        self.assertEqual(normalized["incident_clusters"][0]["cluster_id"], "INC-001")

    def test_resolve_cluster_theme_prefers_runaway_over_availability_tag(self):
        tags = self.export_payload["triage"]["incident_clusters"][0]["tags"]
        self.assertEqual(resolve_cluster_theme(tags, "runawayQueries"), "query")

    def test_extract_known_doc_links_returns_docs_singlestore_urls(self):
        links = extract_known_doc_links(self.export_payload)
        self.assertEqual(len(links), 22)
        self.assertTrue(all(url.startswith("https://docs.singlestore.com/") for url in links))

    def test_extract_known_doc_links_rejects_non_http_and_malformed_values(self):
        payload = {
            "recommendations": [
                {
                    "doc_link": "javascript:alert(1)",
                    "grounding": {"source": "ftp://example.com/doc"},
                },
                {
                    "doc_link": "https://docs.example.com/a",
                    "grounding": {"source": "http://docs.example.com/b"},
                },
                {"doc_link": 42, "grounding": None},
                "not-a-recommendation",
            ]
        }
        self.assertEqual(
            extract_known_doc_links(payload),
            {"https://docs.example.com/a", "http://docs.example.com/b"},
        )

    def test_build_glean_packet_from_export_json_includes_docs(self):
        packet = build_glean_packet(self.export_payload, report_id=self.report_id)
        self.assertTrue(packet["filename"].startswith("s2rs-incident-packet-"))
        self.assertIn("Known doc links", packet["markdown"])
        self.assertIn("https://docs.singlestore.com/", packet["markdown"])
        self.assertNotIn("javascript:", packet["markdown"])

    def test_build_in_app_actions_includes_log_search(self):
        bundle = build_investigation_bundle(
            "00000000-0000-0000-0000-000000000001",
            SAMPLE_PAYLOAD,
            cluster_id="INC-001",
        )
        assert bundle is not None
        actions = build_in_app_actions(bundle)
        types = {a["type"] for a in actions}
        self.assertIn("log_search", types)
        log_action = next(a for a in actions if a["type"] == "log_search")
        self.assertNotEqual(log_action["params"]["keyword"], "memoryUtilizationCritical")

    def test_resolve_log_search_keywords_never_uses_checker_id(self):
        payload = {
            **SAMPLE_PAYLOAD,
            "incident_clusters": [{
                **SAMPLE_PAYLOAD["incident_clusters"][0],
                "root_cause_checker_id": "runawayQueries",
                "root_cause_title": "Runaway queries detected (151)",
                "tags": ["query", "performance"],
            }],
            "recommendations": [{
                "id": "1",
                "checker_id": "runawayQueries",
                "severity": "critical",
                "title": "Runaway queries detected (151)",
                "description": "Queries running >5 minutes.",
                "evidence": "max_elapsed=412.0s user=admin db=analytics query=SELECT count(*) FROM orders_fact WHERE status='open'",
                "category": "Query",
                "nodes": ["leaf-1"],
                "priority_tags": ["query"],
            }],
            "detected_log_patterns": [],
            "logs": [],
        }
        bundle = build_investigation_bundle(
            "00000000-0000-0000-0000-000000000001",
            payload,
            cluster_id="INC-001",
        )
        assert bundle is not None
        keywords = resolve_log_search_keywords(bundle)
        self.assertTrue(keywords)
        self.assertNotIn("runawayQueries", keywords)
        self.assertIn("orders_fact", keywords)
        actions = build_in_app_actions(bundle)
        log_action = next(a for a in actions if a["type"] == "log_search")
        self.assertEqual(log_action["params"]["keyword"], "orders_fact")


class TestInvestigationHelpers(unittest.TestCase):
    def test_dedupe_preserve_order(self):
        self.assertEqual(
            dedupe_preserve_order(["a", "b", "a", "c", "b"]),
            ["a", "b", "c"],
        )

    def test_resolve_finding_type_from_checker(self):
        self.assertEqual(
            resolve_finding_type(checker_id="memoryUtilizationCritical"),
            "memory_pressure",
        )
        self.assertIn("transparentHugepage", EXTRA_CHECKER_MAPPINGS)


if __name__ == "__main__":
    unittest.main()

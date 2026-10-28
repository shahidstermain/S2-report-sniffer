"""Tests for cluster-centric investigation helpers and Glean packet builder."""

import unittest

from investigation import (
    EXTRA_CHECKER_MAPPINGS,
    build_ai_export_json,
    build_glean_packet,
    build_in_app_actions,
    build_investigation_bundle,
    dedupe_preserve_order,
    enrich_incident_clusters_with_logs,
    extract_known_doc_links,
    normalize_export_json_payload,
    resolve_cluster_theme,
    resolve_finding_log_search_terms,
    resolve_finding_type,
    resolve_incident_clusters,
    resolve_log_search_keywords,
)
from investigation_flows import estimate_blast_radius
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

    def test_estimate_blast_radius_scopes_partitions_to_evidence_nodes(self):
        radius = estimate_blast_radius(
            "replicationLagCritical",
            ["leaf-1"],
            {
                "nodes": [{"hostname": "leaf-1"}, {"hostname": "leaf-2"}],
                "cluster_layout": {
                    "total_partitions": 16,
                    "by_host": {
                        "leaf-1": {"master": 4, "slave": 0, "total": 4},
                        "leaf-2": {"master": 12, "slave": 0, "total": 12},
                    },
                },
            },
        )
        self.assertEqual(radius["nodesAffected"], 1)
        self.assertEqual(radius["partitionsAffected"], 4)
        self.assertEqual(radius["scope"], "node-local")

    def test_estimate_blast_radius_omits_partitions_without_host_map(self):
        radius = estimate_blast_radius(
            "replicationLagCritical",
            ["leaf-1"],
            {"nodes": [{"hostname": "leaf-1"}], "cluster_layout": {"total_partitions": 16}},
        )
        self.assertIsNone(radius["partitionsAffected"])

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
        self.assertIn("Triage overview", packet["markdown"])
        self.assertIn("Finding counts:", packet["markdown"])

    def test_build_glean_packet_includes_capacity_and_triage_context(self):
        payload = {
            **SAMPLE_PAYLOAD,
            "health_score": 72,
            "health_grade": "C",
            "memory_utilization": {
                "cluster_summary": {
                    "avg_engine_used_pct": 81.2,
                    "highest_utilization_pct": 94.5,
                    "highest_utilization_node": "leaf-1",
                    "nodes_over_90pct": 1,
                    "nodes_over_80pct": 2,
                },
                "per_node": {
                    "leaf-1": {"engine_used_pct": 94.5, "swap_used_pct": 12.0},
                    "leaf-2": {"engine_used_pct": 70.0, "swap_used_pct": 1.0},
                },
            },
            "replication_status": [
                {"LAG_SECONDS": 42.0, "Connected": "Yes"},
                {"LAG_SECONDS": 2.0, "Connected": "Yes"},
            ],
            "recommendations": [
                {
                    **SAMPLE_PAYLOAD["recommendations"][0],
                    "triage": {
                        "priority": 1,
                        "quick_win": False,
                        "recommended_action": "Raise max_memory on leaf-1",
                    },
                },
                {
                    **SAMPLE_PAYLOAD["recommendations"][1],
                    "triage": {"priority": 2, "quick_win": True},
                },
            ],
        }
        packet = build_glean_packet(payload, report_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        md = packet["markdown"]
        self.assertIn("Health grade (Sniffer):** C", md)
        self.assertIn("Cluster capacity & replication snapshot", md)
        self.assertIn("avg vs maximum_memory=81.2%", md)
        self.assertIn("Swap pressure", md)
        self.assertIn("Lag: max=42.0s", md)
        self.assertIn("Most-affected nodes", md)
        self.assertIn("Act Now=1", packet["prompt"])
        self.assertIn("Raise max_memory", md)

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


class TestResolveFindingLogSearchTerms(unittest.TestCase):
    """Per-finding 'View in Logs' deep-link hint attached by /recommendations."""

    def test_prefers_memsql_phrase_for_tracelog_oom_sample(self):
        finding = {
            "checker_id": "tracelogOOM",
            "evidence": (
                "count=3 first=2024-01-01 last=2024-01-02 sample="
                "6551550134584 2022-03-01 11:54:26.584 ERROR: Nonfatal buffer manager memory allocation failure."
            ),
            "nodes": ["host1"],
        }
        terms = resolve_finding_log_search_terms(finding)
        self.assertEqual(
            terms["keyword"],
            "Nonfatal buffer manager memory allocation failure",
        )
        self.assertEqual(terms["node"], "host1")

    def test_dmesg_oom_uses_restart_phrase_not_kernel_line(self):
        finding = {
            "checker_id": "tracelogOOM",
            "evidence": "Jul 10 02:15:00 host1 kernel: Out of memory: Kill process 1234",
            "related_views": ["dmesg"],
            "nodes": ["host1"],
        }
        terms = resolve_finding_log_search_terms(finding)
        self.assertEqual(terms["keyword"], "starting up, version")
        self.assertEqual(terms["node"], "host1")

    def test_memory_utilization_uses_nonfatal_phrase(self):
        finding = {
            "checker_id": "memoryUtilizationCritical",
            "evidence": "nodes_over_90pct=2 max_engine_pct=92.1",
            "nodes": ["leaf-1"],
        }
        terms = resolve_finding_log_search_terms(finding)
        self.assertEqual(
            terms["keyword"],
            "Nonfatal buffer manager memory allocation failure",
        )

    def test_extracts_keyword_from_evidence_when_no_checker_mapping(self):
        finding = {
            "checker_id": "runawayQueries",
            "evidence": "max_elapsed=412.0s user=admin db=analytics query=SELECT count(*) FROM orders_fact WHERE status='open'",
            "nodes": ["leaf-1", "leaf-2"],
        }
        terms = resolve_finding_log_search_terms(finding)
        self.assertNotEqual(terms["keyword"], "runawayQueries")
        # Multi-node finding: no single-node filter should be applied.
        self.assertEqual(terms["node"], "")

    def test_returns_empty_keyword_for_config_only_checkers(self):
        finding = {"checker_id": "transparentHugepage", "evidence": "", "nodes": []}
        terms = resolve_finding_log_search_terms(finding)
        self.assertEqual(terms["keyword"], "")
        self.assertEqual(terms["node"], "")

    def test_pressure_events_fsync_behind_keyword(self):
        finding = {
            "checker_id": "pressureEvents_fsync_behind",
            "evidence": "hot_hours=2 worst_hour=2024-01-10T09:00:00 worst_count=5",
            "nodes": [],
        }
        terms = resolve_finding_log_search_terms(finding)
        self.assertEqual(terms["keyword"], "fsync is behind")


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


class TestAiExportAndGleanEnhancements(unittest.TestCase):
    def test_build_glean_packet_includes_topology_and_workload(self):
        payload = {
            **SAMPLE_PAYLOAD,
            "cluster_overview": {
                "nodes_detail": [
                    {"id": "1", "ip_addr": "node-1", "type": "MA", "state": "online", "availability_group": ""},
                    {"id": "2", "ip_addr": "node-2", "type": "LEAF", "state": "offline", "availability_group": "1"},
                ],
                "processlist": [
                    {"ID": "100", "STATE": "executing", "TIME": 45, "USER": "app", "INFO": "SELECT * FROM large_table"},
                    {"ID": "101", "STATE": "Sleep", "TIME": 10, "USER": "root", "INFO": ""},
                ],
                "blocked_queries": [
                    {"ID": "100", "BLOCKING_ID": "99", "BLOCKING_TYPE": "lock wait", "QUERY_TEXT": "UPDATE t SET x=1"},
                ],
            },
        }
        packet = build_glean_packet(payload, report_id="test-report-12345678")
        md = packet["markdown"]
        self.assertIn("Cluster topology & node status", md)
        self.assertIn("Master Aggregator: 1", md)
        self.assertIn("Leaves: 1", md)
        self.assertIn("Offline / Degraded nodes", md)
        self.assertIn("Active workload & query contention", md)
        self.assertIn("Lock Contention (MV_BLOCKED_QUERIES)", md)
        self.assertIn("SELECT * FROM large_table", md)
        self.assertIn("suggested_prompt" if "suggested_prompt" in packet else "prompt", packet)

    def test_build_ai_export_json_structure(self):
        payload = {
            **SAMPLE_PAYLOAD,
            "cluster_overview": {
                "nodes_detail": [
                    {"id": "1", "ip_addr": "node-1", "type": "MA", "state": "online"},
                ],
                "processlist": [
                    {"ID": "101", "STATE": "executing", "TIME": 12, "USER": "app", "INFO": "SELECT 1"},
                ],
            },
        }
        ai_json = build_ai_export_json(payload, report_id="test-report-87654321")
        self.assertEqual(ai_json["$schema_version"], "1.0")
        self.assertEqual(ai_json["format"], "s2rs-ai-investigation-packet")
        self.assertEqual(ai_json["metadata"]["report_id"], "test-report-87654321")
        self.assertIn("suggested_prompt", ai_json)
        self.assertIn("cluster_topology", ai_json)
        self.assertEqual(ai_json["cluster_topology"]["master_aggregators"], 1)
        self.assertIn("active_workload_snapshot", ai_json)
        self.assertEqual(len(ai_json["active_workload_snapshot"]["executing_queries"]), 1)
        self.assertIn("top_findings", ai_json)
        self.assertIn("triage_action_items", ai_json)


if __name__ == "__main__":
    unittest.main()

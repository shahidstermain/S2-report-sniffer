import unittest

from explainers import (
    BASIS_LABELS,
    HEURISTIC,
    KPI_GLOSSARY,
    UNKNOWN_EXPLAINER,
    build_explainers_catalog,
    card_from_finding,
    explainer_for_checker,
    explainer_for_kpi,
    resolve_explainer,
)
from grounding import DOCUMENTED, GROUNDING, GENERIC_DOC_LINKS


class ExplainerCatalogTests(unittest.TestCase):
    def test_health_score_is_sniffer_index_not_cluster_vitals(self):
        card = explainer_for_kpi("health_score")
        self.assertEqual(HEURISTIC, card["basis"])
        self.assertIn("Finding Severity Index", card["meaning"])
        self.assertIn("not cluster vitals", card["meaning"])
        self.assertIn("critical_findings × 15", card["derivation"])
        self.assertIn("not a SingleStore requirement", card["basis_label"])

    def test_unknown_kpi_fails_closed(self):
        card = explainer_for_kpi("not_a_real_kpi")
        self.assertEqual(UNKNOWN_EXPLAINER["meaning"], card["meaning"])
        self.assertIn("does not invent", card["derivation"])

    def test_documented_checker_keeps_docs_formula(self):
        card = explainer_for_checker("maxMemorySettings")
        self.assertEqual(DOCUMENTED, card["basis"])
        self.assertIn("0.91 * RAM - 1 MB", card["criterion"])
        self.assertTrue(card["source"])
        self.assertNotIn(card["source"], GENERIC_DOC_LINKS)

    def test_heuristic_checker_is_not_sold_as_requirement(self):
        card = explainer_for_checker("memoryUtilizationCritical")
        self.assertEqual(HEURISTIC, card["basis"])
        self.assertIn("not a SingleStore requirement", card["basis_label"])

    def test_every_grounding_checker_has_an_explainer(self):
        catalog = build_explainers_catalog()
        for checker_id in GROUNDING:
            self.assertIn(checker_id, catalog["findings"])
            self.assertEqual(checker_id, catalog["findings"][checker_id]["id"])

    def test_live_finding_card_prefers_report_grounding_and_evidence(self):
        card = card_from_finding({
            "checker_id": "diskUsage",
            "title": "Disk usage high on leaf-1 /data",
            "evidence": "leaf-1 /data: 81.0% used",
            "grounding": {
                "basis": "documented",
                "criterion": "Toolbox recommends >30% free disk space.",
                "source": "https://docs.singlestore.com/db/v9.1/reference/configuration-reference/cluster-configuration/system-requirements-and-recommendations/",
            },
        })
        self.assertEqual("Disk usage high on leaf-1 /data", card["meaning"])
        self.assertIn("81.0% used", card["derivation"])
        self.assertEqual("documented", card["basis"])
        self.assertEqual(BASIS_LABELS["documented"], card["basis_label"])

    def test_generic_doc_link_is_stripped(self):
        card = card_from_finding({
            "checker_id": "usedClusterCapacity",
            "grounding": {"basis": "heuristic", "criterion": "75/90", "source": "https://docs.singlestore.com/"},
        })
        self.assertEqual("", card["source"])

    def test_resolve_explainer_routes_kpis_and_findings(self):
        self.assertEqual("kpi", resolve_explainer("node_count")["kind"])
        self.assertEqual("finding", resolve_explainer("replicationLag")["kind"])
        self.assertEqual(UNKNOWN_EXPLAINER["meaning"], resolve_explainer("nope")["meaning"])

    def test_all_kpis_are_in_catalog(self):
        catalog = build_explainers_catalog()
        for kpi_id in KPI_GLOSSARY:
            self.assertEqual("kpi", catalog["kpis"][kpi_id]["kind"])


if __name__ == "__main__":
    unittest.main()

import unittest

from parsers import (
    _strip_unreliable_skew_panels,
    build_extended_diagnostics,
    hydrate_extended_diagnostics,
)


class TableSkewRemovalTests(unittest.TestCase):
    def test_extended_diagnostics_do_not_include_table_skew(self):
        dx = build_extended_diagnostics([], [], {})
        self.assertNotIn("table_skew", dx)

    def test_hydrate_strips_persisted_table_skew(self):
        payload = {
            "extended_diagnostics": {
                "mv_events_timeline": {"total_count": 1},
                "table_skew": {"summary": {"high_row_skew_tables": 20}, "table_skew": [{"table": "db.t"}]},
            }
        }
        dx = hydrate_extended_diagnostics(payload)
        self.assertNotIn("table_skew", dx)

    def test_strip_helper_drops_only_skew_panel(self):
        cleaned = _strip_unreliable_skew_panels({
            "cpu_health": {"per_node": [1]},
            "table_skew": {"table_skew": [1]},
        })
        self.assertEqual({"per_node": [1]}, cleaned["cpu_health"])
        self.assertNotIn("table_skew", cleaned)


if __name__ == "__main__":
    unittest.main()

"""
Validators unit tests — QLT-001 coverage expansion.
"""
import unittest
from validators import (
    validate_report_id,
    validate_search_query,
    validate_severity_filter,
    validate_filename,
    validate_file_size,
    sanitize_log_message,
    sanitize_dict,
    ValidationError,
    SanitizationLevel,
    is_valid_report_id,
    validate_node_filter,
    validate_pagination,
)


class TestReportIdValidation(unittest.TestCase):
    def test_valid_uuid(self):
        uid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        result = validate_report_id(uid)
        self.assertEqual(result, uid.lower())

    def test_valid_uppercase_uuid(self):
        uid = "A1B2C3D4-E5F6-7890-ABCD-EF1234567890"
        result = validate_report_id(uid)
        self.assertEqual(result, uid.lower())

    def test_empty_raises(self):
        with self.assertRaises(ValidationError):
            validate_report_id("")

    def test_invalid_format_raises(self):
        with self.assertRaises(ValidationError):
            validate_report_id("not-a-uuid")

    def test_too_long_raises(self):
        with self.assertRaises(ValidationError):
            validate_report_id("a" * 100)

    def test_is_valid_true(self):
        ok, msg = is_valid_report_id("abc12345-1234-1234-1234-123456789012")
        self.assertTrue(ok)

    def test_is_valid_false_empty(self):
        ok, msg = is_valid_report_id("")
        self.assertFalse(ok)


class TestSearchQueryValidation(unittest.TestCase):
    def test_strips_whitespace(self):
        result = validate_search_query("  hello world  ")
        self.assertEqual(result, "hello world")

    def test_html_escaped(self):
        result = validate_search_query("<b>bold</b>")
        self.assertNotIn("<b>", result)
        self.assertNotIn("<", result)

    def test_script_tag_returns_none(self):
        self.assertIsNone(validate_search_query("<script>alert(1)</script>"))
        self.assertIsNone(validate_search_query("<SCRIPT>"))

    def test_js_protocol_returns_none(self):
        self.assertIsNone(validate_search_query("javascript:alert(1)"))

    def test_event_handler_returns_none(self):
        self.assertIsNone(validate_search_query("onclick=alert(1)"))

    def test_truncates_long_query(self):
        long_query = "a" * 600
        result = validate_search_query(long_query)
        self.assertEqual(len(result), 500)

    def test_none_returns_none(self):
        self.assertIsNone(validate_search_query(None))
        self.assertIsNone(validate_search_query(""))

    def test_valid_query(self):
        result = validate_search_query("SHOW DATABASES")
        self.assertEqual(result, "SHOW DATABASES")


class TestSeverityFilter(unittest.TestCase):
    def test_single_valid(self):
        result = validate_severity_filter("critical")
        self.assertEqual(result, ["critical"])

    def test_multiple_comma_separated(self):
        result = validate_severity_filter("critical,warning,info")
        self.assertEqual(set(result), {"critical", "warning", "info"})

    def test_warn_alias(self):
        result = validate_severity_filter("warn")
        self.assertEqual(result, ["warning"])

    def test_case_insensitive(self):
        result = validate_severity_filter("WARNING")
        self.assertEqual(result, ["warning"])

    def test_unknown_filtered(self):
        result = validate_severity_filter("unknown,critical,invalid")
        self.assertEqual(result, ["critical"])

    def test_none_returns_none(self):
        self.assertIsNone(validate_severity_filter(None))


class TestNodeFilter(unittest.TestCase):
    def test_strips_and_escapes(self):
        result = validate_node_filter("node-1")
        self.assertEqual(result, "node\\-1")

    def test_none_returns_none(self):
        self.assertIsNone(validate_node_filter(None))

    def test_truncates_long(self):
        long_val = "a" * 600
        result = validate_node_filter(long_val)
        self.assertEqual(len(result), 500)


class TestPagination(unittest.TestCase):
    def test_defaults(self):
        page, size = validate_pagination(None, None)
        self.assertEqual(page, 1)
        self.assertEqual(size, 100)

    def test_custom_values(self):
        page, size = validate_pagination("5", "50")
        self.assertEqual(page, 5)
        self.assertEqual(size, 50)

    def test_min_page_enforced(self):
        page, _ = validate_pagination(0, None)
        self.assertEqual(page, 1)

    def test_max_page_size_enforced(self):
        _, size = validate_pagination(None, 1000)
        self.assertEqual(size, 500)

    def test_invalid_coerced(self):
        page, size = validate_pagination("abc", "xyz")
        self.assertEqual(page, 1)
        self.assertEqual(size, 100)


class TestFilenameValidation(unittest.TestCase):
    def test_valid_zip(self):
        ok, name = validate_filename("report-2024-01-01.tar.gz")
        self.assertTrue(ok)
        self.assertEqual(name, "report-2024-01-01.tar.gz")

    def test_valid_tgz(self):
        ok, _ = validate_filename("data.tgz")
        self.assertTrue(ok)

    def test_valid_zip_ext(self):
        ok, _ = validate_filename("data.zip")
        self.assertTrue(ok)

    def test_rejects_exe(self):
        ok, _ = validate_filename("malware.exe")
        self.assertFalse(ok)

    def test_rejects_sh(self):
        ok, _ = validate_filename("script.sh")
        self.assertFalse(ok)

    def test_rejects_path_traversal(self):
        ok, _ = validate_filename("../../../etc/passwd")
        self.assertFalse(ok)

    def test_rejects_long_name(self):
        ok, _ = validate_filename("a" * 300 + ".tar.gz")
        self.assertFalse(ok)

    def test_rejects_no_extension(self):
        ok, _ = validate_filename("report")
        self.assertFalse(ok)


class TestFileSizeValidation(unittest.TestCase):
    def test_valid_size(self):
        ok, _ = validate_file_size(1024 * 1024 * 1024)
        self.assertTrue(ok)

    def test_within_limit(self):
        ok, _ = validate_file_size(5 * 1024**3)
        self.assertTrue(ok)

    def test_exceeds_limit(self):
        ok, msg = validate_file_size(20 * 1024**3)
        self.assertFalse(ok)
        self.assertIn("exceeds", msg)

    def test_zero_rejected(self):
        ok, _ = validate_file_size(0)
        self.assertFalse(ok)


class TestSanitization(unittest.TestCase):
    def test_html_escape_basic(self):
        result = sanitize_log_message("<b>bold</b> & \"quoted\"")
        self.assertNotIn("<b>", result)
        self.assertNotIn(">", result)

    def test_html_escape_strict(self):
        result = sanitize_log_message("<script>alert(1)</script>", SanitizationLevel.STRICT)
        self.assertNotIn("<script>", result)

    def test_strip_ctrl_chars(self):
        result = sanitize_log_message("line1\x00line2", SanitizationLevel.STRICT)
        self.assertNotIn("\x00", result)

    def test_strip_js_protocol(self):
        result = sanitize_log_message("javascript:alert(1)", SanitizationLevel.STRICT)
        self.assertNotIn("javascript", result)

    def test_empty_returns_empty(self):
        self.assertEqual(sanitize_log_message(""), "")

    def test_dict_sanitizes_strings(self):
        data = {"key": "<script>alert(1)</script>", "num": 42}
        result = sanitize_dict(data)
        self.assertNotIn("<script>", result["key"])
        self.assertEqual(result["num"], 42)

    def test_dict_nested(self):
        data = {"outer": {"inner": "<b>test</b>"}}
        result = sanitize_dict(data)
        self.assertNotIn("<b>", result["outer"]["inner"])

    def test_dict_list_values(self):
        data = {"items": ["<a>", "<b>"]}
        result = sanitize_dict(data)
        for item in result["items"]:
            self.assertNotIn("<", item)

    def test_non_dict_passthrough(self):
        result = sanitize_dict([1, 2, 3])
        self.assertEqual(result, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()

"""
Input validation, sanitization, and security utilities.
Provides comprehensive validation for all external inputs across the application.
"""
import re
import html
from typing import Any, Optional, List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum


class ValidationError(Exception):
    def __init__(self, field: str, message: str, code: str = "INVALID_INPUT"):
        self.field = field
        self.message = message
        self.code = code
        super().__init__(f"{field}: {message}")


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[ValidationError]
    sanitized: Optional[Dict[str, Any]] = None

    @classmethod
    def success(cls, sanitized: Optional[Dict[str, Any]] = None) -> "ValidationResult":
        return cls(is_valid=True, errors=[], sanitized=sanitized or {})

    @classmethod
    def failure(cls, errors: List[ValidationError]) -> "ValidationResult":
        return cls(is_valid=False, errors=errors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": [{"field": e.field, "message": e.message, "code": e.code} for e in self.errors],
        }


class SanitizationLevel(Enum):
    NONE = "none"
    BASIC = "basic"
    STRICT = "strict"


REPORT_ID_PATTERN = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', re.I)
FILENAME_SAFE_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')
MAX_FILENAME_LENGTH = 255
MAX_REPORT_ID_LENGTH = 64
MAX_SEARCH_LENGTH = 500
MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100


def is_valid_report_id(report_id: str) -> Tuple[bool, Optional[str]]:
    """
    Validate report ID format (UUID).
    Returns (is_valid, error_message).
    """
    if not report_id:
        return False, "Report ID is required"

    if len(report_id) > MAX_REPORT_ID_LENGTH:
        return False, f"Report ID exceeds maximum length of {MAX_REPORT_ID_LENGTH}"

    if not REPORT_ID_PATTERN.match(report_id):
        return False, "Report ID must be a valid UUID format"

    return True, None


def validate_report_id(report_id: str) -> str:
    """
    Validate and sanitize report ID.
    Raises ValidationError if invalid.
    """
    is_valid, error = is_valid_report_id(report_id)
    if not is_valid:
        raise ValidationError("report_id", error or "Invalid report ID", "INVALID_REPORT_ID")
    return report_id.lower()


def validate_search_query(search: Optional[str]) -> Optional[str]:
    """
    Validate and sanitize search query to prevent regex injection.
    Returns sanitized string or None if empty.
    """
    if not search:
        return None

    search = search.strip()

    if len(search) > MAX_SEARCH_LENGTH:
        search = search[:MAX_SEARCH_LENGTH]

    if len(search) < 1:
        return None

    dangerous_patterns = [
        r'<script',
        r'javascript:',
        r'on\w+\s*=',
    ]
    for pattern in dangerous_patterns:
        if re.search(pattern, search, re.I):
            return None

    sanitized = html.escape(search)

    return sanitized


def validate_severity_filter(severity: Optional[str]) -> Optional[List[str]]:
    """
    Validate and parse severity filter parameter.
    Returns list of valid severity levels or None.
    """
    if not severity:
        return None

    valid_severities = {"debug", "info", "notice", "warning", "error", "fatal", "critical"}
    parsed = set()

    for part in severity.split(","):
        part = part.strip().lower()
        if part in valid_severities:
            parsed.add(part)
        elif part == "warn":
            parsed.add("warning")

    return list(parsed) if parsed else None


def validate_node_filter(node: Optional[str]) -> Optional[str]:
    """
    Validate and sanitize node filter.
    Prevents regex injection by escaping special characters.
    """
    if not node:
        return None

    node = node.strip()
    if len(node) > MAX_SEARCH_LENGTH:
        node = node[:MAX_SEARCH_LENGTH]

    sanitized = re.escape(node)
    return sanitized


def validate_pagination(page: Any, page_size: Any, max_page_size: int = MAX_PAGE_SIZE) -> Tuple[int, int]:
    """
    Validate and normalize pagination parameters.
    Returns (page, page_size) with defaults applied.
    """
    try:
        page = int(page) if page is not None else 1
    except (ValueError, TypeError):
        page = 1

    if page < 1:
        page = 1

    try:
        page_size = int(page_size) if page_size is not None else DEFAULT_PAGE_SIZE
    except (ValueError, TypeError):
        page_size = DEFAULT_PAGE_SIZE

    if page_size < 10:
        page_size = 10
    elif page_size > max_page_size:
        page_size = max_page_size

    return page, page_size


def validate_filename(filename: str) -> Tuple[bool, str]:
    """
    Validate uploaded filename for security.
    Returns (is_valid, sanitized_filename).
    """
    if not filename:
        return False, ""

    if len(filename) > MAX_FILENAME_LENGTH:
        return False, "Filename too long"

    if not FILENAME_SAFE_PATTERN.match(filename):
        return False, "Filename contains invalid characters"

    dangerous_extensions = ['.exe', '.sh', '.bat', '.cmd', '.ps1', '.scr', '.pif', '.msi', '.dll', '.so']
    lower_name = filename.lower()
    for ext in dangerous_extensions:
        if lower_name.endswith(ext):
            return False, f"Extension {ext} not allowed"

    allowed_archive_extensions = ('.tar.gz', '.tgz', '.zip', '.tar', '.gz')
    if not lower_name.endswith(allowed_archive_extensions):
        return False, "Only .tar.gz, .tgz, .zip, .tar, and .gz files are accepted"

    return True, filename


def validate_file_size(size: int, max_size_bytes: int = 10 * 1024 * 1024 * 1024) -> Tuple[bool, str]:
    """
    Validate file size against maximum limit.
    Default max: 10GB.
    """
    if size <= 0:
        return False, "Invalid file size"

    if size > max_size_bytes:
        max_gb = max_size_bytes / (1024 * 1024 * 1024)
        return False, f"File size exceeds maximum of {max_gb:.0f}GB"

    return True, ""


def sanitize_log_message(message: str, level: SanitizationLevel = SanitizationLevel.BASIC) -> str:
    """
    Sanitize log message content to prevent XSS and injection attacks.
    """
    if not message:
        return ""

    sanitized = html.escape(message)

    if level == SanitizationLevel.STRICT:
        sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', sanitized)
        sanitized = re.sub(r'(java|vb)script:', '', sanitized, flags=re.I)
        sanitized = re.sub(r'on\w+\s*=', '', sanitized)

    return sanitized


def sanitize_dict(data: Dict[str, Any], level: SanitizationLevel = SanitizationLevel.BASIC) -> Dict[str, Any]:
    """
    Recursively sanitize dictionary values for safe storage/display.
    """
    if not isinstance(data, dict):
        return data

    sanitized = {}
    for key, value in data.items():
        safe_key = str(key).strip()
        if isinstance(value, str):
            sanitized[safe_key] = sanitize_log_message(value, level)
        elif isinstance(value, dict):
            sanitized[safe_key] = sanitize_dict(value, level)
        elif isinstance(value, list):
            sanitized[safe_key] = [
                sanitize_dict(v, level) if isinstance(v, dict) else sanitize_log_message(v, level) if isinstance(v, str) else v
                for v in value
            ]
        else:
            sanitized[safe_key] = value

    return sanitized


def validate_report_structure(report: Dict[str, Any]) -> ValidationResult:
    """
    Validate the structure of a parsed report to ensure required fields exist.
    """
    errors: List[ValidationError] = []

    if not isinstance(report, dict):
        return ValidationResult.failure([ValidationError("report", "Report must be a dictionary", "INVALID_REPORT_TYPE")])

    required_toplevel_fields = ["report_name", "parsed_at", "nodes"]
    for field in required_toplevel_fields:
        if field not in report:
            errors.append(ValidationError(field, f"Missing required field: {field}", "MISSING_FIELD"))

    nodes = report.get("nodes", [])
    if not isinstance(nodes, list):
        errors.append(ValidationError("nodes", "Nodes must be a list", "INVALID_NODES_TYPE"))
    elif len(nodes) == 0:
        errors.append(ValidationError("nodes", "Report contains no nodes", "EMPTY_NODES"))

    if errors:
        return ValidationResult.failure(errors)

    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(ValidationError(f"nodes[{i}]", "Node must be a dictionary", "INVALID_NODE_TYPE"))
            continue

        required_node_fields = ["hostname", "role"]
        for field in required_node_fields:
            if field not in node:
                errors.append(ValidationError(f"nodes[{i}].{field}", f"Missing required field: {field}", "MISSING_NODE_FIELD"))

        hostname = node.get("hostname", "")
        if hostname and (len(hostname) > 255 or '/' in hostname or '\\' in hostname):
            errors.append(ValidationError(f"nodes[{i}].hostname", "Invalid hostname format", "INVALID_HOSTNAME"))

    if errors:
        return ValidationResult.failure(errors)

    return ValidationResult.success()


def validate_parsed_report_safe(report: Dict[str, Any]) -> bool:
    """
    Additional safety check that parsed report data doesn't contain obviously dangerous content.
    This is a secondary validation after validate_report_structure.
    """
    if not isinstance(report, dict):
        return False

    dangerous_strings = [
        "<script",
        "javascript:",
        "onerror=",
        "onload=",
        "{{",
        "${",
    ]

    def check_value(val):
        if isinstance(val, str):
            for pattern in dangerous_strings:
                if pattern.lower() in val.lower():
                    return False
        elif isinstance(val, dict):
            return all(check_value(v) for v in val.values())
        elif isinstance(val, list):
            return all(check_value(v) for v in val)
        return True

    return check_value(report)


class RequestValidator:
    """
    Centralized request validation with composable rules.
    """

    @staticmethod
    def validate_report_upload_request(filename: str, file_size: int) -> ValidationResult:
        errors: List[ValidationError] = []

        is_valid, sanitized_name = validate_filename(filename)
        if not is_valid:
            errors.append(ValidationError("filename", sanitized_name, "INVALID_FILENAME"))

        is_valid, error_msg = validate_file_size(file_size)
        if not is_valid:
            errors.append(ValidationError("file_size", error_msg, "INVALID_FILE_SIZE"))

        if errors:
            return ValidationResult.failure(errors)

        return ValidationResult.success({"filename": sanitized_name, "file_size": file_size})

    @staticmethod
    def validate_log_search_request(
        report_id: str,
        search: Optional[str] = None,
        severity: Optional[str] = None,
        node: Optional[str] = None,
        page: Any = None,
        page_size: Any = None,
    ) -> ValidationResult:
        errors: List[ValidationError] = []

        try:
            validate_report_id(report_id)
        except ValidationError as e:
            errors.append(e)

        sanitized_search = validate_search_query(search)
        sanitized_severity = validate_severity_filter(severity)
        sanitized_node = validate_node_filter(node) if node else None
        validated_page, validated_page_size = validate_pagination(page, page_size)

        if errors:
            return ValidationResult.failure(errors)

        return ValidationResult.success({
            "report_id": report_id.lower(),
            "search": sanitized_search,
            "severity": sanitized_severity,
            "node": sanitized_node,
            "page": validated_page,
            "page_size": validated_page_size,
        })

    @staticmethod
    def validate_report_id_only(report_id: str) -> ValidationResult:
        try:
            validate_report_id(report_id)
            return ValidationResult.success({"report_id": report_id.lower()})
        except ValidationError as e:
            return ValidationResult.failure([e])
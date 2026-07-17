"""Product-layer capabilities, privacy, exports, comparison, and local telemetry.

All functions are deterministic and local-only.  No network client is imported here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import html
import ipaddress
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from superchecker import compute_diff


_IP_RE = re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.])")
_IPV6_CANDIDATE_RE = re.compile(
    r"(?<![0-9a-f:])(?:[0-9a-f]*:){2,7}[0-9a-f]*(?![0-9a-f:])",
    re.IGNORECASE,
)
_HOST_ASSIGN_RE = re.compile(
    r"(?i)(\b(?:host|hostname|node|node_name|master_host|leaf_host|"
    r"slave_host|peer|peer_host)\s*[:=]\s*)([\"']?)([a-z0-9][a-z0-9._-]*)\2"
)
_QUOTED_SECRET_ASSIGN_RE = re.compile(
    r"(?i)([\"']?)(password|passwd|pwd|token|secret|api[_-]?key|"
    r"access[_-]?key)\1(\s*[:=]\s*)([\"'])(.*?)\4"
)
_JSON_QUOTED_SECRET_RE = re.compile(
    r'(?i)"(password|passwd|pwd|token|secret|api[_-]?key|'
    r'access[_-]?key)"(\s*:\s*)"(?:\\.|[^"\\])*"'
)
_JSON_LITERAL_SECRET_RE = re.compile(
    r'(?i)"(password|passwd|pwd|token|secret|api[_-]?key|'
    r'access[_-]?key)"(\s*:\s*)'
    r"(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)"
)
_ESCAPED_JSON_QUOTED_SECRET_RE = re.compile(
    r'(?i)\\"(password|passwd|pwd|token|secret|api[_-]?key|'
    r'access[_-]?key)\\"(\s*:\s*)\\".*?\\"'
)
_ESCAPED_JSON_LITERAL_SECRET_RE = re.compile(
    r'(?i)\\"(password|passwd|pwd|token|secret|api[_-]?key|'
    r'access[_-]?key)\\"(\s*:\s*)'
    r"(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)"
)
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|"
    r"access[_-]?key)\s*[:=]\s*(?![\"'])([^\s,;]+)"
)
_URL_USERINFO_RE = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://)([^/@\s]+)@"
)
_URL_RE = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s,;\"'<>]+")
_SECRET_KEY_PARTS = {
    "password", "passwd", "pwd", "token", "secret", "api_key", "apikey",
    "access_key", "private_key", "credential", "credentials", "client_secret", "signing_key",
}
_HOST_KEYS = {
    "host",
    "hostname",
    "leaf_host",
    "master_host",
    "node",
    "node_name",
    "peer",
    "peer_host",
    "slave_host",
}
_HOST_MAP_KEYS = {"nodes_by_host", "per_host", "per_node"}
_DATABASE_KEYS = {"database", "database_name", "schema", "schema_name", "dbname"}
_DATABASE_MAP_KEYS = {"databases_by_name", "partitions", "per_database"}
_CONNECTION_KEYS = {
    "connection_string",
    "dsn",
    "master_uri",
    "replica_uri",
    "slave_uri",
    "uri",
}
_DOCUMENT_URL_KEYS = {"doc_link"}
_SOURCE_KEYS = {"source", "source_file"}
_LOCAL_SOURCE_PATH_KEYS = {
    "_node_path",
    "extracted_path",
    "import_source_path",
    "report_root",
}


def _normalize_key_name(key: str) -> str:
    snake_key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^a-z0-9]+", "_", snake_key.lower()).strip("_")


def _engine_version(payload: dict[str, Any]) -> str:
    overview = payload.get("cluster_overview") or {}
    version = overview.get("version") or payload.get("version")
    if version:
        return str(version)
    for node in payload.get("nodes") or []:
        if node.get("version"):
            return str(node["version"])
    return ""


def _version_support(version: str) -> str:
    match = re.search(r"(\d+)(?:\.(\d+))?", version or "")
    if not match:
        return "unknown"
    major = int(match.group(1))
    if major < 7:
        return "legacy"
    if major <= 9:
        return "supported"
    return "newer_than_validated"


def build_capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    """Describe what the supplied report can actually power in the UI."""
    nodes = payload.get("nodes") or []
    overview = payload.get("cluster_overview") or {}
    mode = payload.get("input_mode") or ("bundle" if nodes or overview else "sparse")
    version = _engine_version(payload)

    sources = {
        "overview": bool(overview or nodes),
        "charts": bool(nodes or payload.get("log_summary") or payload.get("storage")),
        "nodes": bool(nodes),
        "storage": bool(payload.get("storage") or payload.get("database_disk_usage") or payload.get("databases")),
        "queries": bool(payload.get("queries") or payload.get("query_patterns") or payload.get("query_analysis")),
        "logs": bool(payload.get("logs") or payload.get("log_count") or payload.get("log_summary")),
        "log-search": bool(payload.get("logs") or payload.get("log_count") or payload.get("extracted_path")),
        "config": bool(payload.get("config_health") or any((n.get("show_variables") or n.get("config")) for n in nodes)),
        "recommendations": bool(payload.get("recommendations")),
    }
    labels = {
        "overview": "cluster overview",
        "charts": "chart metrics",
        "nodes": "node inventory",
        "storage": "storage collectors",
        "queries": "query collectors",
        "logs": "log data",
        "log-search": "searchable logs",
        "config": "configuration collectors",
        "recommendations": "diagnostic findings",
    }
    features = {
        key: {
            "available": available,
            "reason": "Available" if available else f"Missing {labels[key]} in this input",
        }
        for key, available in sources.items()
    }
    return {
        "mode": mode,
        "partial": mode == "sparse" or not all(sources.values()),
        "engine_version": version or None,
        "version_support": _version_support(version),
        "features": features,
    }


def _register_host_alias(
    value: str,
    aliases: dict[str, str],
    host_aliases: dict[str, str],
    counters: dict[str, int],
) -> None:
    existing = next(
        (
            alias
            for original, alias in host_aliases.items()
            if original.casefold() == value.casefold()
        ),
        None,
    )
    if existing is None:
        counters["node"] += 1
        existing = f"NODE_{counters['node']}"
    host_aliases[value] = existing
    aliases[value] = existing
    if "." in value:
        short_name = value.split(".", 1)[0]
        host_aliases.setdefault(short_name, existing)
        aliases.setdefault(short_name, existing)


def _register_database_alias(
    value: str,
    aliases: dict[str, str],
    counters: dict[str, int],
) -> None:
    existing = next(
        (
            alias
            for original, alias in aliases.items()
            if alias.startswith("DATABASE_")
            and original.casefold() == value.casefold()
        ),
        None,
    )
    if existing is None:
        counters["database"] += 1
        existing = f"DATABASE_{counters['database']}"
    aliases[value] = existing


def _collect_aliases(
    value: Any,
    aliases: dict[str, str],
    host_aliases: dict[str, str],
    counters: dict[str, int],
    key: str = "",
) -> None:
    if isinstance(value, dict):
        if _normalize_key_name(key) in _HOST_MAP_KEYS:
            for child_key in value:
                if isinstance(child_key, str) and child_key:
                    _register_host_alias(
                        child_key,
                        aliases,
                        host_aliases,
                        counters,
                    )
        if _normalize_key_name(key) in _DATABASE_MAP_KEYS:
            for child_key in value:
                if isinstance(child_key, str) and child_key:
                    _register_database_alias(
                        child_key,
                        aliases,
                        counters,
                    )
        for child_key, child in value.items():
            _collect_aliases(
                child,
                aliases,
                host_aliases,
                counters,
                str(child_key),
            )
    elif isinstance(value, list):
        for child in value:
            _collect_aliases(child, aliases, host_aliases, counters, key)
    elif isinstance(value, str):
        normalized = _normalize_key_name(key)
        if normalized in _HOST_KEYS and value:
            _register_host_alias(value, aliases, host_aliases, counters)
        elif normalized in _DATABASE_KEYS and value:
            _register_database_alias(value, aliases, counters)


def anonymize_report(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a deep-copy with stable node/database aliases and secret redaction."""
    cleaned = deepcopy(payload)
    aliases: dict[str, str] = {}
    host_aliases: dict[str, str] = {}
    counters = {
        "connection": 0,
        "database": 0,
        "ip": 0,
        "node": 0,
        "source": 0,
    }
    _collect_aliases(cleaned, aliases, host_aliases, counters)
    connection_aliases: dict[str, str] = {}
    ip_aliases: dict[str, str] = {}
    source_aliases: dict[str, str] = {}
    replacements = 0

    def is_secret_key(key: str) -> bool:
        normalized = _normalize_key_name(key)
        return any(
            normalized == part
            or normalized.startswith(f"{part}_")
            or normalized.endswith(f"_{part}")
            or f"_{part}_" in normalized
            for part in _SECRET_KEY_PARTS
        )

    def host_alias_for(original: str) -> str:
        original_folded = original.casefold()
        short_folded = original_folded.split(".", 1)[0]
        replacement = next(
            (
                alias
                for known, alias in host_aliases.items()
                if known.casefold() in {original_folded, short_folded}
            ),
            None,
        )
        if replacement is None:
            counters["node"] += 1
            replacement = f"NODE_{counters['node']}"
        host_aliases[original] = replacement
        aliases[original] = replacement
        return replacement

    def ip_alias_for(original: str) -> str:
        nonlocal replacements
        if original not in ip_aliases:
            counters["ip"] += 1
            ip_aliases[original] = f"IP_{counters['ip']}"
        replacements += 1
        return ip_aliases[original]

    def replace_string(
        text: str,
        *,
        preserve_url_hosts: bool = False,
    ) -> str:
        nonlocal replacements
        stripped = text.strip()
        if (
            len(stripped) >= 2
            and stripped[0] in "[{"
            and stripped[-1] in "]}"
        ):
            try:
                structured = json.loads(stripped)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(structured, (dict, list)):
                    return json.dumps(
                        walk(structured),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
        result = text

        def replace_url_userinfo(match: re.Match[str]) -> str:
            nonlocal replacements
            replacements += 1
            return f"{match.group(1)}[REDACTED]@"

        def replace_host_assignment(match: re.Match[str]) -> str:
            nonlocal replacements
            original = match.group(3)
            replacement = host_alias_for(original)
            replacements += 1
            quote = match.group(2)
            return f"{match.group(1)}{quote}{replacement}{quote}"

        result = _HOST_ASSIGN_RE.sub(replace_host_assignment, result)

        def replace_url_host(match: re.Match[str]) -> str:
            url = match.group(0)
            parsed = urlsplit(url)
            hostname = parsed.hostname
            if not hostname:
                return url
            try:
                is_ip = bool(ipaddress.ip_address(hostname))
            except ValueError:
                is_ip = False
            if preserve_url_hosts and not is_ip:
                return url
            replacement = (
                ip_alias_for(hostname)
                if is_ip
                else host_alias_for(hostname)
            )
            userinfo = (
                "[REDACTED]@"
                if parsed.username is not None or parsed.password is not None
                else ""
            )
            try:
                port = f":{parsed.port}" if parsed.port is not None else ""
            except ValueError:
                port = ""
            return urlunsplit(
                (
                    parsed.scheme,
                    f"{userinfo}{replacement}{port}",
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )

        result = _URL_RE.sub(replace_url_host, result)
        result = _URL_USERINFO_RE.sub(replace_url_userinfo, result)
        seen_hosts: set[str] = set()
        for original in sorted(host_aliases, key=len, reverse=True):
            folded = original.casefold()
            if folded in seen_hosts:
                continue
            seen_hosts.add(folded)
            replacement = host_aliases[original]
            fqdn_suffix = (
                ""
                if "." in original
                else r"(?:\.[a-zA-Z0-9-]+)*"
            )
            alias_pattern = re.compile(
                rf"(?<![a-zA-Z0-9_.-]){re.escape(original)}{fqdn_suffix}"
                r"(?![a-zA-Z0-9_.-])",
                re.IGNORECASE,
            )
            result, count = alias_pattern.subn(replacement, result)
            if count:
                replacements += count

        host_alias_keys = {key.casefold() for key in host_aliases}
        for original in sorted(aliases, key=len, reverse=True):
            if original.casefold() in host_alias_keys:
                continue
            replacement = aliases[original]
            alias_pattern = re.compile(
                rf"(?<![a-zA-Z0-9_.-]){re.escape(original)}"
                r"(?![a-zA-Z0-9_.-])"
            )
            result, count = alias_pattern.subn(replacement, result)
            if count:
                replacements += count

        result = _IP_RE.sub(lambda match: ip_alias_for(match.group(0)), result)

        def replace_ipv6(match: re.Match[str]) -> str:
            candidate = match.group(0)
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                return candidate
            if address.version != 6:
                return candidate
            return ip_alias_for(candidate)

        result = _IPV6_CANDIDATE_RE.sub(replace_ipv6, result)

        def replace_secret(match: re.Match[str]) -> str:
            nonlocal replacements
            replacements += 1
            return f"{match.group(1)}=[REDACTED]"

        def replace_quoted_secret(match: re.Match[str]) -> str:
            nonlocal replacements
            replacements += 1
            key_quote = match.group(1)
            value_quote = match.group(4)
            return (
                f"{key_quote}{match.group(2)}{key_quote}"
                f"{match.group(3)}{value_quote}[REDACTED]{value_quote}"
            )

        def replace_json_quoted_secret(match: re.Match[str]) -> str:
            nonlocal replacements
            replacements += 1
            return f'"{match.group(1)}"{match.group(2)}"[REDACTED]"'

        def replace_json_literal_secret(match: re.Match[str]) -> str:
            nonlocal replacements
            replacements += 1
            return f'"{match.group(1)}"{match.group(2)}"[REDACTED]"'

        def replace_escaped_json_quoted_secret(
            match: re.Match[str],
        ) -> str:
            nonlocal replacements
            replacements += 1
            return (
                f'\\"{match.group(1)}\\"'
                f'{match.group(2)}\\"[REDACTED]\\"'
            )

        def replace_escaped_json_literal_secret(
            match: re.Match[str],
        ) -> str:
            nonlocal replacements
            replacements += 1
            return (
                f'\\"{match.group(1)}\\"'
                f'{match.group(2)}\\"[REDACTED]\\"'
            )

        result = _ESCAPED_JSON_QUOTED_SECRET_RE.sub(
            replace_escaped_json_quoted_secret,
            result,
        )
        result = _ESCAPED_JSON_LITERAL_SECRET_RE.sub(
            replace_escaped_json_literal_secret,
            result,
        )
        result = _JSON_QUOTED_SECRET_RE.sub(
            replace_json_quoted_secret,
            result,
        )
        result = _JSON_LITERAL_SECRET_RE.sub(
            replace_json_literal_secret,
            result,
        )
        result = _QUOTED_SECRET_ASSIGN_RE.sub(replace_quoted_secret, result)
        return _SECRET_ASSIGN_RE.sub(replace_secret, result)

    def walk(value: Any, key: str = "") -> Any:
        nonlocal replacements
        if key and is_secret_key(key) and value not in ("", None):
            replacements += 1
            return "[REDACTED]"
        if isinstance(value, dict):
            cleaned_dict = {}
            for child_key, child_value in value.items():
                if str(child_key) in _LOCAL_SOURCE_PATH_KEYS:
                    continue
                cleaned_key = (
                    replace_string(child_key)
                    if isinstance(child_key, str)
                    else child_key
                )
                cleaned_dict[cleaned_key] = walk(child_value, str(child_key))
            return cleaned_dict
        if isinstance(value, list):
            return [walk(item, key) for item in value]
        if isinstance(value, str):
            normalized_key = _normalize_key_name(key)
            if normalized_key in _CONNECTION_KEYS and value:
                if value not in connection_aliases:
                    counters["connection"] += 1
                    connection_aliases[value] = (
                        f"CONNECTION_{counters['connection']}"
                    )
                replacements += 1
                return connection_aliases[value]
            if normalized_key in _SOURCE_KEYS and value:
                if re.match(r"^[a-z][a-z0-9+.-]*://", value, re.IGNORECASE):
                    return replace_string(value, preserve_url_hosts=True)
                if value not in source_aliases:
                    counters["source"] += 1
                    suffix = Path(value).suffix.lower()
                    if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                        suffix = ""
                    source_aliases[value] = f"SOURCE_{counters['source']}{suffix}"
                replacements += 1
                return source_aliases[value]
            if normalized_key in _DOCUMENT_URL_KEYS:
                return replace_string(value, preserve_url_hosts=True)
            return replace_string(value)
        return value

    cleaned = walk(cleaned)
    cleaned["privacy"] = {
        "anonymized": True,
        "scheme": "stable-local-aliases-v1",
    }
    return cleaned, {
        "enabled": True,
        "replacements": replacements,
        "nodes_aliased": counters["node"],
        "databases_aliased": counters["database"],
        "connections_aliased": counters["connection"],
        "ips_aliased": counters["ip"],
        "sources_aliased": counters["source"],
    }


def _config_map(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for node in payload.get("nodes") or []:
        host = str(node.get("hostname") or "unknown")
        values = node.get("show_variables") or {}
        for key, value in values.items():
            result[f"{host}:{key}"] = value
    return result


def compare_reports(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare findings, topology metrics, and engine variables."""
    findings = compute_diff(before.get("recommendations") or [], after.get("recommendations") or [])
    before_overview = before.get("cluster_overview") or {}
    after_overview = after.get("cluster_overview") or {}
    metrics: dict[str, dict[str, Any]] = {}
    for key in ("total_nodes", "leaves", "aggregators", "total_partitions", "version"):
        left = before_overview.get(key)
        right = after_overview.get(key)
        if left != right:
            metrics[key] = {"before": left, "after": right}

    old_config = _config_map(before)
    new_config = _config_map(after)
    changes = []
    for compound in sorted(set(old_config) | set(new_config)):
        left = old_config.get(compound)
        right = new_config.get(compound)
        if left == right:
            continue
        host, _, key = compound.partition(":")
        changes.append({"node": host, "key": key, "before": left, "after": right})

    return {
        "from": {"id": before.get("id"), "name": before.get("report_name"), "version": _engine_version(before)},
        "to": {"id": after.get("id"), "name": after.get("report_name"), "version": _engine_version(after)},
        "summary": {
            "new_findings": len(findings.get("new", [])),
            "resolved_findings": len(findings.get("resolved", [])),
            "worsened_findings": len(findings.get("worsened", [])),
            "configuration_changes": len(changes),
            "metric_changes": len(metrics),
        },
        "findings": findings,
        "metrics": metrics,
        "configuration_changes": changes,
    }


def _sorted_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(
        payload.get("recommendations") or [],
        key=lambda row: (order.get(str(row.get("severity", "info")).lower(), 3), -int(row.get("risk_score") or 0)),
    )


def build_markdown_export(payload: dict[str, Any]) -> str:
    overview = payload.get("cluster_overview") or {}
    findings = _sorted_findings(payload)
    lines = [
        f"# SingleStore diagnostic summary: {payload.get('report_name') or 'Report'}",
        "",
        f"- **Health:** {payload.get('health_score') or 'unknown'}",
        f"- **Risk score:** {payload.get('cluster_risk_score') or 0}",
        f"- **Engine version:** {_engine_version(payload) or 'unknown'}",
        f"- **Nodes:** {overview.get('total_nodes') or payload.get('node_count') or 0}",
        "",
        "## Findings",
    ]
    if not findings:
        lines.append("No diagnostic findings were detected in the supplied data.")
    for index, finding in enumerate(findings[:50], 1):
        lines.extend([
            f"### {index}. [{str(finding.get('severity') or 'info').upper()}] {finding.get('title') or 'Finding'}",
            str(finding.get("description") or ""),
            "",
            f"**Evidence:** {finding.get('evidence') or 'Not supplied'}",
            "",
        ])
    lines.extend(["## Recommended actions"])
    actions = [str(row.get("remediation") or "").strip() for row in findings if row.get("remediation")]
    if actions:
        lines.extend(f"{index}. {action}" for index, action in enumerate(actions[:50], 1))
    else:
        lines.append("No remediation actions were generated for the supplied data.")
    lines.extend(["", "_Generated locally by S2 Report Sniffer. No report data was transmitted._", ""])
    return "\n".join(lines)


def build_portable_html(payload: dict[str, Any]) -> str:
    """Build a standalone, dependency-free, escaped customer report."""
    esc = lambda value: html.escape(str(value if value is not None else ""), quote=True)
    overview = payload.get("cluster_overview") or {}
    rows = []
    for finding in _sorted_findings(payload)[:100]:
        rows.append(
            "<article class='finding'>"
            f"<div class='finding-head'><span class='severity {esc(str(finding.get('severity') or 'info').lower())}'>{esc(str(finding.get('severity') or 'info').upper())}</span>"
            f"<strong>{esc(finding.get('title') or 'Finding')}</strong></div>"
            f"<p>{esc(finding.get('description') or '')}</p>"
            f"<div class='evidence'><b>Evidence:</b> {esc(finding.get('evidence') or 'Not supplied')}</div>"
            f"<div class='action'><b>Action:</b> {esc(finding.get('remediation') or 'Review with SingleStore Support.')}</div>"
            "</article>"
        )
    if not rows:
        rows.append("<div class='empty'>No diagnostic findings were detected in the supplied data.</div>")
    return f"""<!doctype html>
<html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{esc(payload.get('report_name') or 'SingleStore diagnostic report')}</title>
<style>
:root{{--bg:#08090b;--panel:#111318;--text:#eef2f3;--muted:#9aa3a8;--accent:#00d992;--line:#2a2f35;--critical:#ff5d73;--warning:#ffb84d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,sans-serif}}main{{max-width:960px;margin:auto;padding:40px 24px}}h1{{font-size:28px;margin:0 0 6px}}.sub{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:28px 0}}.metric,.finding,.empty{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}}.metric b{{display:block;font-size:22px;color:var(--accent)}}h2{{margin-top:34px}}.finding{{margin:12px 0}}.finding-head{{display:flex;gap:10px;align-items:center}}.severity{{font-size:11px;font-weight:800;border-radius:999px;padding:3px 8px;background:#263039}}.severity.critical{{color:var(--critical)}}.severity.warning{{color:var(--warning)}}.evidence,.action{{margin-top:10px;color:var(--muted)}}footer{{margin-top:30px;color:var(--muted);font-size:12px}}
</style></head><body><main>
<h1>{esc(payload.get('report_name') or 'SingleStore diagnostic report')}</h1><div class='sub'>Portable customer-facing diagnostic summary</div>
<section class='metrics'><div class='metric'><b>{esc(payload.get('health_score') or 'unknown')}</b>Health</div><div class='metric'><b>{esc(payload.get('cluster_risk_score') or 0)}</b>Risk score</div><div class='metric'><b>{esc(_engine_version(payload) or 'unknown')}</b>Engine</div><div class='metric'><b>{esc(overview.get('total_nodes') or payload.get('node_count') or 0)}</b>Nodes</div></section>
<h2>Findings and recommended actions</h2>{''.join(rows)}
<footer>Generated locally by S2 Report Sniffer. This standalone file makes no network requests.</footer>
</main></body></html>"""


class TelemetryStore:
    """Local, opt-in product analytics. External delivery is intentionally absent."""

    _ALLOWED_FIELDS = {"duration_ms", "checker_ids", "input_mode", "engine_major", "node_count", "status"}

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.base_dir / "telemetry-settings.json"
        self.events_path = self.base_dir / "telemetry-events.jsonl"

    def get_settings(self) -> dict[str, Any]:
        settings = {"enabled": False, "external_delivery": False, "privacy": "allowlist-only"}
        if self.settings_path.exists():
            try:
                loaded = json.loads(self.settings_path.read_text(encoding="utf-8"))
                settings["enabled"] = bool(loaded.get("enabled", False))
            except (OSError, json.JSONDecodeError):
                pass
        return settings

    def update_settings(self, *, enabled: bool) -> dict[str, Any]:
        settings = {"enabled": bool(enabled), "external_delivery": False, "privacy": "allowlist-only"}
        self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return settings

    def record(self, event: str, data: dict[str, Any]) -> bool:
        if not self.get_settings()["enabled"]:
            return False
        row: dict[str, Any] = {
            "event": re.sub(r"[^a-z0-9_.-]", "", str(event).lower())[:64],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        for key in self._ALLOWED_FIELDS:
            if key not in data:
                continue
            value = data[key]
            if key == "checker_ids":
                value = [re.sub(r"[^A-Za-z0-9_.-]", "", str(item))[:80] for item in list(value)[:20]]
            row[key] = value
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True

    def read_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        rows = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 1000)):]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows


class AutoUpdateSettingsStore:
    """Persist the explicit opt-in for the desktop app's network update check."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.base_dir / "auto-update-settings.json"

    def get_settings(self) -> dict[str, Any]:
        enabled = False
        if self.settings_path.exists():
            try:
                loaded = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    enabled = bool(loaded.get("enabled", False))
            except (OSError, json.JSONDecodeError):
                pass
        return {"enabled": enabled, "network_access": "github-releases"}

    def update_settings(self, *, enabled: bool) -> dict[str, Any]:
        settings = {"enabled": bool(enabled), "network_access": "github-releases"}
        self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return settings

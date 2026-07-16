"""Product-layer capabilities, privacy, exports, comparison, and local telemetry.

All functions are deterministic and local-only.  No network client is imported here.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
from typing import Any

from superchecker import compute_diff


_IP_RE = re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.])")
_HOST_ASSIGN_RE = re.compile(
    r"(?i)(\b(?:host|hostname|node|node_name)\s*[:=]\s*)([a-z0-9][a-z0-9._-]*)"
)
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key)\s*[:=]\s*([^\s,;]+)"
)
_SECRET_KEY_PARTS = {
    "password", "passwd", "pwd", "token", "secret", "api_key", "apikey",
    "access_key", "private_key", "credential", "credentials", "client_secret", "signing_key",
}
_HOST_KEYS = {"hostname", "host", "node", "node_name", "master_host", "leaf_host"}
_DATABASE_KEYS = {"database", "database_name", "schema", "schema_name", "dbname"}
_LOCAL_SOURCE_PATH_KEYS = {
    "_node_path",
    "extracted_path",
    "import_source_path",
    "report_root",
}


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


def _collect_aliases(value: Any, aliases: dict[str, str], counters: dict[str, int], key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            _collect_aliases(child, aliases, counters, str(child_key).lower())
    elif isinstance(value, list):
        for child in value:
            _collect_aliases(child, aliases, counters, key)
    elif isinstance(value, str):
        normalized = key.lower()
        if normalized in _HOST_KEYS and value and value not in aliases:
            counters["node"] += 1
            aliases[value] = f"NODE_{counters['node']}"
        elif normalized in _DATABASE_KEYS and value and value not in aliases:
            counters["database"] += 1
            aliases[value] = f"DATABASE_{counters['database']}"


def anonymize_report(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a deep-copy with stable node/database aliases and secret redaction."""
    cleaned = deepcopy(payload)
    aliases: dict[str, str] = {}
    counters = {"node": 0, "database": 0, "ip": 0}
    _collect_aliases(cleaned, aliases, counters)
    ip_aliases: dict[str, str] = {}
    replacements = 0

    def is_secret_key(key: str) -> bool:
        snake_key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
        normalized = re.sub(r"[^a-z0-9]+", "_", snake_key.lower()).strip("_")
        return any(
            normalized == part
            or normalized.startswith(f"{part}_")
            or normalized.endswith(f"_{part}")
            or f"_{part}_" in normalized
            for part in _SECRET_KEY_PARTS
        )

    def replace_string(text: str) -> str:
        nonlocal replacements
        result = text

        def replace_host_assignment(match: re.Match[str]) -> str:
            nonlocal replacements
            original = match.group(2)
            if original not in aliases:
                counters["node"] += 1
                aliases[original] = f"NODE_{counters['node']}"
            replacements += 1
            return f"{match.group(1)}{aliases[original]}"

        result = _HOST_ASSIGN_RE.sub(replace_host_assignment, result)
        for original in sorted(aliases, key=len, reverse=True):
            replacement = aliases[original]
            count = result.count(original)
            if count:
                result = result.replace(original, replacement)
                replacements += count

        def replace_ip(match: re.Match[str]) -> str:
            nonlocal replacements
            original = match.group(0)
            if original not in ip_aliases:
                counters["ip"] += 1
                ip_aliases[original] = f"IP_{counters['ip']}"
            replacements += 1
            return ip_aliases[original]

        result = _IP_RE.sub(replace_ip, result)

        def replace_secret(match: re.Match[str]) -> str:
            nonlocal replacements
            replacements += 1
            return f"{match.group(1)}=[REDACTED]"

        return _SECRET_ASSIGN_RE.sub(replace_secret, result)

    def walk(value: Any, key: str = "") -> Any:
        nonlocal replacements
        if isinstance(value, dict):
            return {
                k: walk(v, str(k))
                for k, v in value.items()
                if str(k) not in _LOCAL_SOURCE_PATH_KEYS
            }
        if isinstance(value, list):
            return [walk(item, key) for item in value]
        if isinstance(value, str):
            if is_secret_key(key) and value:
                replacements += 1
                return "[REDACTED]"
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
        "ips_aliased": counters["ip"],
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

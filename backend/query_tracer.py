"""
Offline-first query trace correlation for S2 Report Sniffer.

Joins processlist, MV_BLOCKED_QUERIES, MV_QUERIES, query_patterns, and optional
tracelog hits into a stage graph with confidence scoring and observed vs inferred layers.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from parsers import _normalize_sql, _safe_float_val, search_all_trace_logs

RUNAWAY_THRESHOLD_SEC = 300.0
SLOW_THRESHOLD_SEC = 30.0
_MAX_LOG_CORRELATIONS = 20

LOG_CORRELATION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("lock_wait", "lock wait"),
    ("etimedout", "ETIMEDOUT"),
    ("compile_failure", "Failed to finalize asynchronous compilation"),
    ("retry_stall", "Retry loop is stalling"),
)

STAGE_ORDER = [
    "client",
    "aggregator_ingress",
    "compile",
    "route",
    "distribute",
    "leaf_execute",
    "leaf_lock",
    "aggregator_gather",
    "client_return",
]

CONFIDENCE_TIERS = (
    (80, "high"),
    (50, "medium"),
    (0, "low"),
)


def _field(row: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return str(row[key])
    return default


def _connection_id(row: dict) -> str:
    return _field(
        row,
        "ID",
        "id",
        "CONNECTION_ID",
        "connection_id",
        "PROCESSLIST_ID",
        "BLOCKED_QUERY_ID",
        "blocked_query_id",
    )


def _query_text(row: dict) -> str:
    return _field(
        row,
        "QUERY_TEXT",
        "query_text",
        "Info",
        "info",
        "QUERY",
        "BLOCKED_QUERY_TEXT",
        "blocked_query_text",
        "BLOCKING_QUERY_TEXT",
        "blocking_query_text",
    )[:500]


def _activity_name(row: dict) -> str:
    return _field(row, "ACTIVITY_NAME", "activity_name", "ActivityName")


def _node_id(row: dict) -> str:
    return _field(row, "NODE_ID", "node_id", "BLOCKED_NODE_ID", "blocked_node_id", "HOST", "host")


def _elapsed_sec(row: dict) -> float:
    return _safe_float_val(
        row.get("ELAPSED_TIME")
        or row.get("elapsed_time")
        or row.get("Time")
        or row.get("ELAPSED_TIME_S")
        or row.get("time_sec")
        or 0
    )


def _blocking_type(row: dict) -> str:
    return _field(row, "BLOCKING_TYPE", "blocking_type", "blocking_reason", "BlockingType")


def compute_trace_id(
    normalized_sql: str,
    *,
    connection_id: str | None = None,
    activity_name: str | None = None,
    node_id: str | None = None,
    trace_type: str = "generic",
) -> str:
    payload = "|".join(
        [
            normalized_sql or "",
            str(connection_id or ""),
            activity_name or "",
            node_id or "",
            trace_type,
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def _confidence_tier(score: int) -> str:
    for threshold, tier in CONFIDENCE_TIERS:
        if score >= threshold:
            return tier
    return "low"


def _score_confidence(factors: list[dict[str, Any]], *, fan_out_inferred: bool = False) -> dict[str, Any]:
    score = sum(int(f.get("weight", 0)) for f in factors)
    if fan_out_inferred:
        score -= 15
        factors = list(factors) + [
            {
                "id": "fan_out_inference_only",
                "label": "Partition routing inferred only",
                "weight": -15,
                "present": True,
            }
        ]
    score = max(0, min(100, score))
    return {"score": score, "tier": _confidence_tier(score), "factors": factors}


def _node_role_map(report: dict) -> dict[str, str]:
    roles: dict[str, str] = {}
    overview = report.get("cluster_overview", {}) or {}
    for nd in overview.get("nodes_detail", []) or []:
        ip = _field(nd, "ip_addr", "IP_ADDR")
        nid = _field(nd, "id", "ID")
        node_type = _field(nd, "type", "TYPE").upper()
        role = "LEAF"
        if node_type == "MA":
            role = "MA"
        elif node_type in ("CA", "AGGREGATOR"):
            role = "CA"
        if ip:
            roles[ip] = role
        if nid:
            roles[nid] = role
    return roles


def _resolve_node_role(node_id: str, role_map: dict[str, str]) -> str:
    if not node_id:
        return "CA"
    return role_map.get(node_id, "LEAF" if "leaf" in node_id.lower() else "CA")


def _partition_routing_hint(report: dict, query_text: str = "") -> dict[str, Any]:
    return _infer_partition_routing(report, query_text)


def _extract_from_tables(query_text: str) -> list[str]:
    if not query_text:
        return []
    match = re.search(r"\bfrom\s+([^\s;]+)", query_text, re.IGNORECASE)
    if not match:
        return []
    raw = match.group(1).strip("`\"'")
    return [part.strip("`\"'") for part in raw.split(",") if part.strip()]


def _extract_where_predicates(query_text: str) -> list[dict[str, str]]:
    if not query_text:
        return []
    predicates: list[dict[str, str]] = []
    for match in re.finditer(
        r"\b([a-zA-Z_][\w.]*)\s*=\s*(?:'[^']*'|\?|\d+)",
        query_text,
        re.IGNORECASE,
    ):
        predicates.append({"type": "equality", "column": match.group(1).split(".")[-1]})
    for match in re.finditer(
        r"\b([a-zA-Z_][\w.]*)\s+in\s*\(",
        query_text,
        re.IGNORECASE,
    ):
        predicates.append({"type": "in", "column": match.group(1).split(".")[-1]})
    return predicates


def _infer_partition_routing(report: dict, query_text: str) -> dict[str, Any]:
    partitions = report.get("partitions", {}) or {}
    cluster_layout = report.get("cluster_layout", {}) or {}
    total_partitions = (
        partitions.get("total_partitions")
        or partitions.get("total")
        or cluster_layout.get("total_partitions")
        or 0
    )
    if total_partitions and int(total_partitions) == 1:
        return {
            "label": "partitions:single",
            "confidence": "high",
            "inferred": True,
            "reason": "Cluster layout shows a single partition",
            "matched_columns": [],
        }

    tables = _extract_from_tables(query_text)
    predicates = _extract_where_predicates(query_text)
    in_list_preds = [p for p in predicates if p["type"] == "in"]
    eq_preds = [p for p in predicates if p["type"] == "equality"]

    if in_list_preds:
        return {
            "label": "partitions:inlist",
            "confidence": "medium",
            "inferred": True,
            "reason": f"IN-list predicate on {in_list_preds[0]['column']}",
            "matched_columns": [p["column"] for p in in_list_preds],
        }

    if eq_preds:
        return {
            "label": "partitions:single",
            "confidence": "medium",
            "inferred": True,
            "reason": f"Equality on {eq_preds[0]['column']} (shard-key not verified in bundle)",
            "matched_columns": [p["column"] for p in eq_preds],
        }

    if len(tables) > 1:
        return {
            "label": "partitions:all",
            "confidence": "medium",
            "inferred": True,
            "reason": "Multi-table query — likely fan-out without aligned shard keys",
            "matched_columns": [],
        }

    return {
        "label": "partitions:all",
        "confidence": "low",
        "inferred": True,
        "reason": "No shard-key equality detected — default fan-out",
        "matched_columns": [],
    }


def _correlate_logs(
    extracted_root: str | None,
    *,
    query_text: str,
    node_id: str | None,
) -> list[dict[str, Any]]:
    if not extracted_root:
        return []

    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    node_filter = None
    if node_id:
        node_filter = node_id.rsplit(".", 1)[-1]

    search_terms = list(LOG_CORRELATION_PATTERNS)
    snippet = (query_text or "").strip()
    if len(snippet) > 12:
        search_terms.append(("query_text", snippet[:60]))

    for pattern_id, keyword in search_terms:
        if len(hits) >= _MAX_LOG_CORRELATIONS:
            break
        try:
            res = search_all_trace_logs(
                extracted_root,
                keyword,
                max_results=_MAX_LOG_CORRELATIONS - len(hits),
                context_lines=1,
                node_filter=node_filter,
            )
        except Exception:
            continue
        for match in res.get("matches", []) or []:
            dedupe_key = (
                str(match.get("hostname", "")),
                int(match.get("line_number") or 0),
                str(match.get("line", ""))[:80],
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            hits.append(
                {
                    "pattern": pattern_id,
                    "node": match.get("hostname", ""),
                    "role": match.get("role", ""),
                    "timestamp": match.get("timestamp", ""),
                    "severity": match.get("severity", ""),
                    "line_number": match.get("line_number"),
                    "line": (match.get("line", "") or "")[:300],
                    "source": match.get("source", ""),
                }
            )
            if len(hits) >= _MAX_LOG_CORRELATIONS:
                break
    return hits


def _build_timeline(
    report: dict,
    *,
    process_row: dict | None,
    blocked_row: dict | None,
    log_correlations: list[dict[str, Any]],
    routing_info: dict[str, Any],
    elapsed: float,
    agg_role: str,
    agg_node: str,
    leaf_role: str,
    leaf_node: str,
) -> dict[str, Any]:
    log_timeframe = report.get("log_timeframe", {}) or {}
    snapshot_ts = log_timeframe.get("cluster_last") or None

    def event(
        event_id: str,
        label: str,
        *,
        observed: bool,
        stage_id: str,
        timestamp: str | None = None,
        note: str | None = None,
        elapsed_sec: float | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": event_id,
            "label": label,
            "observed": observed,
            "inferred": not observed,
            "timestamp": timestamp,
            "stage_id": stage_id,
        }
        if note:
            payload["note"] = note
        if elapsed_sec:
            payload["elapsed_sec"] = round(elapsed_sec, 1)
        if source:
            payload["source"] = source
        return payload

    lanes: list[dict[str, Any]] = []

    lanes.append(
        {
            "role": "CLIENT",
            "label": "Client",
            "events": [event("connect", "Client request", observed=False, stage_id="client")],
        }
    )

    agg_events = [
        event(
            "processlist_snapshot" if process_row else "ingress_inferred",
            "Processlist snapshot" if process_row else "Aggregator receive (inferred)",
            observed=bool(process_row),
            stage_id="aggregator_ingress",
            timestamp=snapshot_ts if process_row else None,
            elapsed_sec=elapsed if process_row else None,
        ),
        event("compile_inferred", "Plan compile (inferred)", observed=False, stage_id="compile"),
        event(
            "route_inferred",
            f"Routing: {routing_info.get('label', 'partitions:all')}",
            observed=False,
            stage_id="route",
            note=routing_info.get("reason"),
        ),
    ]
    lanes.append({"role": agg_role, "label": f"Aggregator ({agg_node})", "events": agg_events})

    leaf_events: list[dict[str, Any]] = []
    if routing_info.get("label") in {"partitions:all", "partitions:inlist"}:
        leaf_events.append(
            event(
                "distribute_inferred",
                f"Distribute ({routing_info.get('label')})",
                observed=False,
                stage_id="distribute",
            )
        )
    if process_row or blocked_row:
        leaf_events.append(
            event(
                "leaf_execute",
                "Leaf execution",
                observed=True,
                stage_id="leaf_execute",
                timestamp=snapshot_ts,
                elapsed_sec=elapsed,
            )
        )
    if blocked_row:
        leaf_events.append(
            event(
                "leaf_lock",
                f"Lock wait ({_blocking_type(blocked_row) or 'blocked'})",
                observed=True,
                stage_id="leaf_lock",
                timestamp=snapshot_ts,
            )
        )
    for idx, log_hit in enumerate(log_correlations[:5]):
        leaf_events.append(
            event(
                f"log_{log_hit.get('pattern', idx)}",
                f"Tracelog: {log_hit.get('pattern', 'match')}",
                observed=True,
                stage_id="leaf_execute",
                timestamp=log_hit.get("timestamp") or None,
                source="tracelog",
            )
        )
    lanes.append({"role": leaf_role, "label": f"Leaf ({leaf_node})", "events": leaf_events})

    lanes.append(
        {
            "role": agg_role,
            "label": f"Gather ({agg_node})",
            "events": [
                event("gather_inferred", "Gather results (inferred)", observed=False, stage_id="aggregator_gather"),
                event(
                    "client_return",
                    "Result / error",
                    observed=bool(blocked_row),
                    stage_id="client_return",
                    timestamp=snapshot_ts if blocked_row else None,
                ),
            ],
        }
    )

    return {
        "snapshot_timestamp": snapshot_ts,
        "collection_note": "Timestamps reflect bundle snapshot and tracelog hits — not live operator timing.",
        "lanes": lanes,
    }


def _log_pattern_flags(log_correlations: list[dict[str, Any]] | None) -> dict[str, bool]:
    patterns = {str(h.get("pattern", "")) for h in (log_correlations or [])}
    return {
        "compile_failure": "compile_failure" in patterns,
        "etimedout": "etimedout" in patterns,
        "lock_wait": "lock_wait" in patterns,
        "retry_stall": "retry_stall" in patterns,
    }


def _detect_wlm_queued(report: dict, process_row: dict | None) -> dict[str, Any]:
    overview = report.get("cluster_overview", {}) or {}
    mv_processlist = overview.get("mv_processlist", []) or []
    workload_management = overview.get("workload_management", []) or []

    if process_row:
        state = _field(process_row, "State", "state", "STATUS", "COMMAND").lower()
        if "queue" in state:
            return {"queued": True, "source": "processlist", "reason": state}

    conn = _connection_id(process_row or {})
    if conn:
        for row in mv_processlist:
            if _connection_id(row) == conn:
                state = _field(row, "STATE", "state", "STATUS").lower()
                if "queue" in state:
                    return {"queued": True, "source": "mv_processlist", "reason": state}

    for row in workload_management:
        stat = str(row.get("Stat", row.get("stat", ""))).lower()
        val = str(row.get("Value", row.get("value", ""))).strip()
        if "queue" not in stat or val in ("", "0", "NULL", "null"):
            continue
        try:
            if float(val.replace(",", "")) > 0:
                return {"queued": True, "source": "workload_management", "reason": f"{stat}={val}"}
        except ValueError:
            continue

    return {"queued": False}


def _build_evidence_summary(
    *,
    blocked_row: dict | None,
    process_row: dict | None,
    query_row: dict | None,
    log_correlations: list[dict[str, Any]] | None,
    wlm_info: dict[str, Any] | None,
) -> list[str]:
    items: list[str] = []
    if blocked_row:
        items.append("MV_BLOCKED_QUERIES")
    if process_row:
        conn = _connection_id(process_row)
        items.append(f"processlist id {conn}" if conn else "processlist")
    if query_row:
        items.append("MV_QUERIES")
    if wlm_info and wlm_info.get("queued"):
        items.append(f"WLM queue ({wlm_info.get('source', 'unknown')})")
    log_count = len(log_correlations or [])
    if log_count:
        suffix = "s" if log_count != 1 else ""
        items.append(f"{log_count} tracelog hit{suffix}")
    return items


def _match_rows_by_selector(
    rows: list[dict],
    *,
    normalized_sql: str,
    connection_id: str | None,
    activity_name: str | None,
) -> list[tuple[dict, int]]:
    matches: list[tuple[dict, int]] = []
    for idx, row in enumerate(rows):
        score = 0
        row_sql = _normalize_sql(_query_text(row))
        row_conn = _connection_id(row)
        row_activity = _activity_name(row)

        if normalized_sql and row_sql and row_sql == normalized_sql:
            score += 30
        elif normalized_sql and row_sql and normalized_sql in row_sql:
            score += 15

        if connection_id and row_conn and row_conn == str(connection_id):
            score += 40

        if activity_name and row_activity and row_activity == activity_name:
            score += 25

        if score > 0:
            matches.append((row, score))
    matches.sort(key=lambda item: item[1], reverse=True)
    return matches


def _candidate_summary(
    *,
    trace_id: str,
    trace_type: str,
    query_text: str,
    connection_id: str,
    activity_name: str,
    node_id: str,
    elapsed_sec: float,
    failure_stage: str | None,
    confidence: dict[str, Any],
) -> dict[str, Any]:
    label = query_text[:120] if query_text else activity_name or trace_id
    elapsed_val = _safe_float_val(elapsed_sec)
    return {
        "trace_id": trace_id,
        "trace_type": trace_type,
        "summary": label,
        "connection_id": connection_id or None,
        "activity_name": activity_name or None,
        "node_id": node_id or None,
        "elapsed_sec": round(elapsed_val, 1) if elapsed_val else None,
        "failure_stage": failure_stage,
        "confidence": {
            "score": confidence["score"],
            "tier": confidence["tier"],
        },
    }


def list_query_trace_candidates(report: dict) -> list[dict[str, Any]]:
    """Build index of traceable queries from bundle snapshots."""
    overview = report.get("cluster_overview", {}) or {}
    processlist = overview.get("processlist", []) or []
    blocked_queries = overview.get("blocked_queries", []) or []
    queries = report.get("queries", []) or []
    query_patterns = report.get("query_patterns", {}) or {}

    candidates: dict[str, dict[str, Any]] = {}

    def add_candidate(**kwargs: Any) -> None:
        trace_id = kwargs["trace_id"]
        if trace_id not in candidates or kwargs["confidence"]["score"] > candidates[trace_id]["confidence"]["score"]:
            candidates[trace_id] = _candidate_summary(**kwargs)

    # Lock-wait traces from blocked queries
    for idx, blocked in enumerate(blocked_queries):
        query_text = _query_text(blocked)
        normalized = _normalize_sql(query_text)
        if not normalized and not _connection_id(blocked):
            continue
        conn = _connection_id(blocked)
        activity = _activity_name(blocked)
        node = _node_id(blocked)
        factors = [
            {"id": "blocked_query_row", "label": "MV_BLOCKED_QUERIES row present", "weight": 20, "present": True},
        ]
        proc_matches = _match_rows_by_selector(
            processlist, normalized_sql=normalized, connection_id=conn or None, activity_name=activity or None
        )
        if proc_matches:
            factors.append(
                {"id": "connection_id_match", "label": "Processlist connection id aligned", "weight": 25, "present": True}
            )
        mv_matches = _match_rows_by_selector(
            queries, normalized_sql=normalized, connection_id=None, activity_name=activity or None
        )
        if mv_matches:
            factors.append(
                {"id": "activity_name_match", "label": "MV_QUERIES activity_name match", "weight": 20, "present": True}
            )
        confidence = _score_confidence(
            factors,
            fan_out_inferred=_infer_partition_routing(report, query_text).get("confidence") == "low",
        )
        trace_id = compute_trace_id(
            normalized or f"blocked:{idx}",
            connection_id=conn,
            activity_name=activity,
            node_id=node,
            trace_type="lock_wait",
        )
        elapsed = _elapsed_sec(blocked)
        if not elapsed and proc_matches:
            elapsed = _elapsed_sec(proc_matches[0][0])
        add_candidate(
            trace_id=trace_id,
            trace_type="lock_wait",
            query_text=query_text,
            connection_id=conn,
            activity_name=activity,
            node_id=node,
            elapsed_sec=elapsed,
            failure_stage="leaf_lock",
            confidence=confidence,
        )

    # Runaway traces from query_patterns + processlist
    runaway_rows = list(query_patterns.get("runaway_queries", []) or [])
    seen_norm: set[str] = set()
    for entry in runaway_rows:
        normalized = entry.get("normalized") or _normalize_sql(entry.get("query_text", ""))
        if not normalized or normalized in seen_norm:
            continue
        seen_norm.add(normalized)
        proc_matches = _match_rows_by_selector(processlist, normalized_sql=normalized, connection_id=None, activity_name=None)
        proc_row = proc_matches[0][0] if proc_matches else {}
        conn = _connection_id(proc_row)
        activity = _activity_name(proc_row)
        node = entry.get("node_id") or _node_id(proc_row)
        factors = [
            {"id": "runaway_elapsed", "label": "Runaway elapsed time (>5 min)", "weight": 20, "present": True},
        ]
        if proc_matches:
            factors.append(
                {"id": "processlist_sql_match", "label": "Processlist SQL match", "weight": 25, "present": True}
            )
        if conn:
            factors.append(
                {"id": "connection_id_match", "label": "Processlist connection id present", "weight": 15, "present": True}
            )
        confidence = _score_confidence(
            factors,
            fan_out_inferred=_infer_partition_routing(report, entry.get("query_text", "")).get("confidence") == "low",
        )
        trace_id = compute_trace_id(normalized, connection_id=conn, activity_name=activity, node_id=node, trace_type="runaway")
        add_candidate(
            trace_id=trace_id,
            trace_type="runaway",
            query_text=entry.get("query_text", ""),
            connection_id=conn,
            activity_name=activity,
            node_id=node,
            elapsed_sec=float(entry.get("elapsed_sec") or 0),
            failure_stage="leaf_execute",
            confidence=confidence,
        )

    # High-elapsed processlist without blocked row (medium-confidence runaway/slow)
    for row in processlist:
        elapsed = _elapsed_sec(row)
        if elapsed < SLOW_THRESHOLD_SEC:
            continue
        query_text = _query_text(row)
        normalized = _normalize_sql(query_text)
        if not normalized:
            continue
        conn = _connection_id(row)
        activity = _activity_name(row)
        node = _node_id(row)
        trace_type = "runaway" if elapsed >= RUNAWAY_THRESHOLD_SEC else "slow"
        trace_id = compute_trace_id(normalized, connection_id=conn, activity_name=activity, node_id=node, trace_type=trace_type)
        if trace_id in candidates:
            continue
        factors = [
            {
                "id": "processlist_elapsed",
                "label": f"Processlist elapsed {round(elapsed, 1)}s",
                "weight": 20 if trace_type == "runaway" else 10,
                "present": True,
            }
        ]
        if conn:
            factors.append(
                {"id": "connection_id_present", "label": "Connection id in processlist", "weight": 15, "present": True}
            )
        confidence = _score_confidence(
            factors,
            fan_out_inferred=_infer_partition_routing(report, query_text).get("confidence") == "low",
        )
        add_candidate(
            trace_id=trace_id,
            trace_type=trace_type,
            query_text=query_text,
            connection_id=conn,
            activity_name=activity,
            node_id=node,
            elapsed_sec=elapsed,
            failure_stage="leaf_execute" if trace_type == "runaway" else None,
            confidence=confidence,
        )

    result = list(candidates.values())
    result.sort(key=lambda c: (c["confidence"]["score"], c.get("elapsed_sec") or 0), reverse=True)
    return result


def _build_stages(
    *,
    report: dict,
    trace_type: str,
    process_row: dict | None,
    blocked_row: dict | None,
    query_row: dict | None,
    routing_info: dict[str, Any],
    log_correlations: list[dict[str, Any]] | None = None,
    wlm_info: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    role_map = _node_role_map(report)
    stages: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    routing_label = routing_info.get("label", "partitions:all")
    log_flags = _log_pattern_flags(log_correlations)
    wlm = wlm_info or {}

    agg_node = _node_id(process_row or {}) or _node_id(query_row or {}) or "aggregator"
    agg_role = _resolve_node_role(agg_node, role_map)
    leaf_node = _node_id(blocked_row or process_row or {}) or "leaf"
    leaf_role = _resolve_node_role(leaf_node, role_map)

    elapsed = _elapsed_sec(process_row or blocked_row or query_row or {})
    state = "healthy"
    if trace_type == "lock_wait":
        state = "critical"
    elif trace_type == "runaway":
        state = "warning"
    if log_flags["etimedout"]:
        state = "critical"

    rebalance = report.get("rebalance_events", {}) or {}
    rebalance_active = str(rebalance.get("status", "")).upper() not in {"", "IDLE", "NONE"}
    ingress_status = "warning" if wlm.get("queued") else (state if trace_type != "lock_wait" else "warning")
    compile_status = "warning" if log_flags["compile_failure"] else "healthy"
    gather_status = "warning" if trace_type == "runaway" or log_flags["retry_stall"] else "healthy"

    def add_stage(
        stage_id: str,
        label: str,
        *,
        node_role: str,
        node_host: str,
        status: str,
        observed: bool,
        metrics: dict | None = None,
        evidence: list | None = None,
    ) -> None:
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "node_role": node_role,
                "node_host": node_host,
                "status": status,
                "observed": observed,
                "metrics": metrics or {},
                "evidence": evidence or [],
            }
        )

    add_stage("client", "Client", node_role="CLIENT", node_host="client", status="healthy", observed=False)
    add_stage(
        "aggregator_ingress",
        "Aggregator receive",
        node_role=agg_role,
        node_host=agg_node,
        status=ingress_status,
        observed=bool(process_row),
        metrics={
            "elapsed_sec": elapsed,
            "state": _field(process_row or {}, "State", "state", "COMMAND", "Command"),
            "wlm_queued": bool(wlm.get("queued")),
        },
        evidence=[{"source": "processlist", "connection_id": _connection_id(process_row or {})}] if process_row else [],
    )
    if wlm.get("queued"):
        add_stage(
            "wlm_queue",
            "WLM queue",
            node_role=agg_role,
            node_host=agg_node,
            status="warning",
            observed=True,
            metrics={"reason": wlm.get("reason"), "source": wlm.get("source")},
            evidence=[{"source": wlm.get("source", "workload_management")}],
        )
    add_stage(
        "compile",
        "Plan compile",
        node_role="MA",
        node_host=agg_node,
        status=compile_status,
        observed=log_flags["compile_failure"],
        metrics={
            "note": "Compile failure in tracelog" if log_flags["compile_failure"] else "No compile evidence in bundle — inferred stage",
        },
        evidence=[{"source": "tracelog", "pattern": "compile_failure"}] if log_flags["compile_failure"] else [],
    )
    add_stage(
        "route",
        "Partition routing",
        node_role=agg_role,
        node_host=agg_node,
        status="info",
        observed=False,
        metrics={
            "routing": routing_label,
            "confidence": routing_info.get("confidence"),
            "reason": routing_info.get("reason"),
            "matched_columns": routing_info.get("matched_columns", []),
            "inferred": True,
        },
    )

    if routing_label in {"partitions:all", "partitions:inlist"}:
        add_stage(
            "distribute",
            "Repartition / fan-out",
            node_role=leaf_role,
            node_host=leaf_node,
            status="warning" if rebalance_active else "info",
            observed=False,
            metrics={
                "routing": routing_label,
                "rebalance_active": rebalance_active,
                "inferred": True,
            },
        )

    add_stage(
        "leaf_execute",
        "Leaf execution",
        node_role=leaf_role,
        node_host=leaf_node,
        status=state,
        observed=bool(process_row or blocked_row),
        metrics={"elapsed_sec": elapsed},
        evidence=(
            [{"source": "processlist", "connection_id": _connection_id(process_row or {})}]
            if process_row
            else []
        )
        + ([{"source": "tracelog", "pattern": "etimedout"}] if log_flags["etimedout"] else []),
    )

    failure: dict[str, Any] | None = None
    if blocked_row or trace_type == "lock_wait":
        blocking_type = _blocking_type(blocked_row or {})
        add_stage(
            "leaf_lock",
            "Lock acquire",
            node_role=leaf_role,
            node_host=leaf_node,
            status="critical",
            observed=bool(blocked_row),
            metrics={"blocking_type": blocking_type or "lock wait"},
            evidence=[{"source": "mv_blocked_queries", "blocking_type": blocking_type}] if blocked_row else [],
        )
        failure = {
            "stage_id": "leaf_lock",
            "category": "lock_wait",
            "summary": blocking_type or "Query blocked waiting for lock",
            "blocking_type": blocking_type or None,
        }
    elif trace_type == "runaway":
        failure = {
            "stage_id": "leaf_execute",
            "category": "runaway_query",
            "summary": f"Query running >{int(RUNAWAY_THRESHOLD_SEC)}s in processlist snapshot",
            "blocking_type": None,
        }

    add_stage(
        "aggregator_gather",
        "Gather results",
        node_role=agg_role,
        node_host=agg_node,
        status=gather_status,
        observed=False,
        metrics={"note": "Gather stage inferred — no MV_ACTIVITIES in bundle"},
    )
    add_stage(
        "client_return",
        "Result / error",
        node_role="CLIENT",
        node_host="client",
        status=state if failure else "healthy",
        observed=bool(failure and blocked_row),
        metrics={},
    )

    ordered_ids = [s["id"] for s in stages]
    inferred_targets = {"compile", "route", "distribute", "aggregator_gather", "wlm_queue"}
    for i in range(len(ordered_ids) - 1):
        src, dst = ordered_ids[i], ordered_ids[i + 1]
        inferred = dst in inferred_targets or (src == "route" and dst in {"distribute", "leaf_execute"})
        label = routing_label if src in {"route", "distribute"} and dst in {"distribute", "leaf_execute"} else "flow"
        edges.append({"from": src, "to": dst, "label": label, "inferred": inferred})

    return stages, edges, failure


def resolve_query_trace(
    report: dict,
    trace_request: dict,
    *,
    extracted_root: str | None = None,
) -> dict[str, Any]:
    """
    Resolve a query trace from selector fields.

    trace_request keys: trace_id?, query_text?, connection_id?, activity_name?, normalized_sql?
    """
    overview = report.get("cluster_overview", {}) or {}
    processlist = overview.get("processlist", []) or []
    blocked_queries = overview.get("blocked_queries", []) or []
    queries = report.get("queries", []) or []

    selector = dict(trace_request or {})
    trace_id = str(selector.get("trace_id") or "").strip()
    connection_id = str(selector.get("connection_id") or "").strip() or None
    activity_name = str(selector.get("activity_name") or "").strip() or None
    query_text = str(selector.get("query_text") or "").strip()
    normalized_sql = str(selector.get("normalized_sql") or "").strip() or _normalize_sql(query_text)

    candidates = list_query_trace_candidates(report)
    candidate = next((c for c in candidates if c["trace_id"] == trace_id), None) if trace_id else None

    trace_type = candidate["trace_type"] if candidate else "generic"
    if not normalized_sql and candidate:
        normalized_sql = _normalize_sql(candidate.get("summary", ""))

    proc_matches = _match_rows_by_selector(
        processlist,
        normalized_sql=normalized_sql,
        connection_id=connection_id,
        activity_name=activity_name,
    )
    process_row = proc_matches[0][0] if proc_matches else None

    blocked_matches = _match_rows_by_selector(
        blocked_queries,
        normalized_sql=normalized_sql,
        connection_id=connection_id,
        activity_name=activity_name,
    )
    blocked_row = blocked_matches[0][0] if blocked_matches else None

    query_matches = _match_rows_by_selector(
        queries,
        normalized_sql=normalized_sql,
        connection_id=None,
        activity_name=activity_name,
    )
    query_row = query_matches[0][0] if query_matches else None

    if blocked_row and trace_type == "generic":
        trace_type = "lock_wait"
    elif process_row and _elapsed_sec(process_row) >= RUNAWAY_THRESHOLD_SEC:
        trace_type = "runaway"
    elif candidate:
        trace_type = candidate["trace_type"]

    if not query_text:
        query_text = _query_text(process_row or blocked_row or query_row or {}) or (candidate or {}).get("summary", "")

    if not connection_id and process_row:
        connection_id = _connection_id(process_row) or None
    if not activity_name:
        activity_name = _activity_name(query_row or process_row or {}) or None

    if not trace_id:
        trace_id = compute_trace_id(
            normalized_sql or _normalize_sql(query_text),
            connection_id=connection_id,
            activity_name=activity_name,
            node_id=_node_id(process_row or blocked_row or {}),
            trace_type=trace_type,
        )

    routing_info = _infer_partition_routing(report, query_text)
    node_for_logs = _node_id(process_row or blocked_row or {})
    log_correlations = _correlate_logs(
        extracted_root,
        query_text=query_text,
        node_id=node_for_logs,
    )

    wlm_info = _detect_wlm_queued(report, process_row)
    stages, edges, failure = _build_stages(
        report=report,
        trace_type=trace_type,
        process_row=process_row,
        blocked_row=blocked_row,
        query_row=query_row,
        routing_info=routing_info,
        log_correlations=log_correlations,
        wlm_info=wlm_info,
    )

    elapsed = _elapsed_sec(process_row or blocked_row or query_row or {})
    role_map = _node_role_map(report)
    agg_node = _node_id(process_row or {}) or _node_id(query_row or {}) or "aggregator"
    leaf_node = node_for_logs or "leaf"
    timeline = _build_timeline(
        report,
        process_row=process_row,
        blocked_row=blocked_row,
        log_correlations=log_correlations,
        routing_info=routing_info,
        elapsed=elapsed,
        agg_role=_resolve_node_role(agg_node, role_map),
        agg_node=agg_node,
        leaf_role=_resolve_node_role(leaf_node, role_map),
        leaf_node=leaf_node,
    )

    factors: list[dict[str, Any]] = []
    if connection_id and process_row and _connection_id(process_row) == str(connection_id):
        factors.append(
            {"id": "connection_id_match", "label": "Exact connection id match", "weight": 25, "present": True}
        )
    elif connection_id:
        factors.append(
            {"id": "connection_id_requested", "label": "Connection id provided in request", "weight": 10, "present": True}
        )
    if activity_name and query_row and _activity_name(query_row) == activity_name:
        factors.append(
            {"id": "activity_name_match", "label": "activity_name in MV_QUERIES", "weight": 20, "present": True}
        )
    if blocked_row:
        factors.append(
            {"id": "blocked_query_row", "label": "Blocked-query row present", "weight": 20, "present": True}
        )
    if process_row:
        factors.append(
            {"id": "processlist_row", "label": "Processlist row aligned", "weight": 15, "present": True}
        )
    if trace_type == "runaway":
        factors.append(
            {"id": "runaway_elapsed", "label": "Runaway elapsed threshold met", "weight": 15, "present": True}
        )
    if log_correlations:
        factors.append(
            {"id": "tracelog_correlation", "label": "Tracelog correlation hits", "weight": 15, "present": True}
        )
    if not factors:
        factors.append(
            {"id": "sql_only", "label": "SQL text match only", "weight": 10, "present": bool(normalized_sql)}
        )

    confidence = _score_confidence(
        factors,
        fan_out_inferred=routing_info.get("confidence") == "low",
    )

    related_findings: list[str] = []
    if trace_type == "lock_wait":
        related_findings.extend(["lockContention", "longRunningTransactions"])
    if trace_type == "runaway":
        related_findings.extend(["runawayQueries", "slowQueries"])
    if wlm_info.get("queued"):
        related_findings.append("workloadManagementQueue")

    evidence_summary = _build_evidence_summary(
        blocked_row=blocked_row,
        process_row=process_row,
        query_row=query_row,
        log_correlations=log_correlations,
        wlm_info=wlm_info,
    )

    return {
        "trace_id": trace_id,
        "trace_type": trace_type,
        "selector": {
            "connection_id": connection_id,
            "activity_name": activity_name,
            "query_text": query_text[:500] if query_text else None,
            "normalized_sql": normalized_sql or None,
        },
        "query_text": query_text[:500] if query_text else "",
        "confidence": confidence,
        "routing": routing_info,
        "stages": stages,
        "edges": edges,
        "timeline": timeline,
        "failure": failure,
        "related_findings": related_findings,
        "evidence_summary": evidence_summary,
        "log_correlations": log_correlations,
        "limitations": [
            "Point-in-time bundle snapshot — stages may reflect different collection moments.",
            "No EXPLAIN/PROFILE or MV_ACTIVITIES in bundle; compile/gather/partition routing stages are inferred.",
        ],
    }


def get_query_trace_by_id(
    report: dict,
    trace_id: str,
    *,
    extracted_root: str | None = None,
) -> dict[str, Any] | None:
    candidates = list_query_trace_candidates(report)
    candidate = next((c for c in candidates if c["trace_id"] == trace_id), None)
    if not candidate:
        return None
    return resolve_query_trace(
        report,
        {
            "trace_id": trace_id,
            "connection_id": candidate.get("connection_id"),
            "activity_name": candidate.get("activity_name"),
            "query_text": candidate.get("summary"),
        },
        extracted_root=extracted_root,
    )

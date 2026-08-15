import { useMemo } from "react";
import InfoHint from "./InfoHint";

const STATUS_CONFIG = {
  ACTIVE:  { label: "REBALANCING",      color: "#fff",     bg: "#FF9800" },
  FAILED:  { label: "REBALANCE FAILED", color: "#fff",     bg: "#F44336" },
  IDLE:    { label: "IDLE",             color: "#04140d",  bg: "#00C853" },
};

function eventColor(evtType) {
  const lower = (evtType || "").toLowerCase();
  if (lower.includes("fail") || lower.includes("error") || lower.includes("offline")) return "#F44336";
  if (lower.includes("complete") || lower.includes("online") || lower.includes("success")) return "#00C853";
  if (lower.includes("start") || lower.includes("begin") || lower.includes("initiat")) return "#FF9800";
  if (lower.includes("sync")) return "#2196F3";
  return "var(--text-muted)";
}

function fmtTs(ts) {
  return ts ? ts.slice(0, 19).replace("T", " ") : "—";
}

export default function ClusterStatePanel({ rebalanceEvents }) {
  const { status = "IDLE", reason = "", events = [], raw_status = [] } = rebalanceEvents || {};
  const hasContent = events.length > 0 || raw_status.length > 0 || status !== "IDLE";

  if (!hasContent) return null;

  const statusConf = STATUS_CONFIG[status] || STATUS_CONFIG.IDLE;

  // Determine which raw_status columns to show (skip nulls / skip too many)
  const rawCols = useMemo(() => {
    if (!raw_status.length) return [];
    const allKeys = Object.keys(raw_status[0] || {});
    return allKeys.slice(0, 6);
  }, [raw_status]);

  return (
    <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
      <div className="border-b px-4 py-3 flex items-center gap-3 flex-wrap" style={{ borderColor: "var(--ss-divider)" }}>
        <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Inter, sans-serif" }}>
          ⚖️ Rebalance &amp; Partition State
        </h3>
        <InfoHint
          label="rebalance and partition state"
          content="Rebalance status and partition-movement events parsed from MV_EVENTS and the rebalance-status collector."
        />
        <span
          className="text-[10px] font-bold px-2 py-0.5 rounded tracking-wide"
          style={{ background: statusConf.bg, color: statusConf.color }}
        >
          {statusConf.label}
        </span>
        <p className="text-xs" style={{ color: "var(--ss-mid-gray)" }}>
          Partition rebalancing moves data between leaf nodes to restore balance after topology changes
        </p>
      </div>

      {status === "ACTIVE" && (
        <div className="px-4 py-2 text-xs" style={{ background: "rgba(255,152,0,0.07)", color: "var(--text-secondary)" }}>
          ⚠️ Partition rebalancing is in progress — query performance may be temporarily reduced on affected leaf nodes.
        </div>
      )}
      {status === "FAILED" && reason && (
        <div className="px-4 py-2 text-xs" style={{ background: "rgba(244,67,54,0.07)", color: "var(--text-secondary)" }}>
          ❌ Rebalance failure: {reason}
        </div>
      )}

      {events.length > 0 && (
        <div>
          <p className="px-4 pt-3 pb-1 text-[9px] uppercase tracking-widest font-bold" style={{ color: "var(--ss-mid-gray)" }}>
            Recent Partition &amp; Rebalance Events ({events.length})
          </p>
          <div className="divide-y max-h-52 overflow-y-auto" style={{ borderColor: "var(--divider-light)" }}>
            {events.slice(0, 25).map((evt, i) => (
              <div key={i} className="flex items-start gap-3 px-4 py-1.5 text-[10px]">
                <span className="font-mono flex-shrink-0 pt-px" style={{ color: "var(--ss-mid-gray)", minWidth: "9.5rem" }}>
                  {fmtTs(evt.event_time)}
                </span>
                <span
                  className="font-bold uppercase tracking-wide flex-shrink-0"
                  style={{ color: eventColor(evt.event_type), minWidth: "9rem" }}
                >
                  {evt.event_type}
                </span>
                {evt.node_id && (
                  <span className="font-mono flex-shrink-0" style={{ color: "var(--ss-mid-gray)", minWidth: "5rem" }}>
                    node {evt.node_id}
                  </span>
                )}
                {evt.description && (
                  <span className="truncate" style={{ color: "var(--text-body)" }} title={evt.description}>
                    {evt.description}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {raw_status.length > 0 && rawCols.length > 0 && (
        <div className="border-t" style={{ borderColor: "var(--divider-light)" }}>
          <p className="px-4 pt-3 pb-1 text-[9px] uppercase tracking-widest font-bold" style={{ color: "var(--ss-mid-gray)" }}>
            Rebalance Status
          </p>
          <div className="px-4 pb-3 overflow-x-auto">
            <table className="w-full dense-table text-[11px]">
              <thead>
                <tr>
                  {rawCols.map(col => <th key={col} className="text-left whitespace-nowrap">{col}</th>)}
                </tr>
              </thead>
              <tbody>
                {raw_status.slice(0, 10).map((row, i) => (
                  <tr key={i}>
                    {rawCols.map((col, j) => (
                      <td key={j} className="font-mono">{String(row[col] ?? "—")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

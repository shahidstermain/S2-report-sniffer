import { useMemo } from "react";
import InfoHint from "./InfoHint";

const CATEGORY_COLOR = {
  node_down:    "#F44336",
  node_up:      "#00C853",
  failover:     "#FF9800",
  state_change: "#2196F3",
};

const CATEGORY_ICON = {
  node_down:    "🔴",
  node_up:      "🟢",
  failover:     "🔄",
  state_change: "⚡",
};

function fmtTs(ts) {
  return ts ? ts.slice(0, 19).replace("T", " ") : "—";
}

function nodeMatchesEvent(node, evtNodeId, evtDesc) {
  const ip = (node.ip_addr || "").toLowerCase();
  const id = String(node.id || "").toLowerCase();
  const blob = `${evtNodeId} ${evtDesc}`.toLowerCase();
  return !!(ip && blob.includes(ip)) || !!(id && id.length > 0 && blob.includes(id));
}

function nodeMatchesHost(node, hostname) {
  const ip = (node.ip_addr || "").toLowerCase();
  const h = (hostname || "").toLowerCase();
  return !!(ip && (h.includes(ip) || ip.includes(h)));
}

export default function NodeDownDetails({
  nodeEvents,
  nodesDetail,
  dmesgEvents,
  detectedLogPatterns,
  logTimeframe,
}) {
  const offlineNodes = useMemo(
    () => (nodesDetail || []).filter(n => (n.state || "").toLowerCase() !== "online"),
    [nodesDetail]
  );

  const eventsPerNode = useMemo(() => {
    const map = {};
    for (const node of offlineNodes) {
      map[node.id] = (nodeEvents || []).filter(e =>
        nodeMatchesEvent(node, e.node_id, e.description)
      );
    }
    return map;
  }, [offlineNodes, nodeEvents]);

  const dmesgPerNode = useMemo(() => {
    const map = {};
    for (const node of offlineNodes) {
      map[node.id] = (dmesgEvents || []).filter(e => nodeMatchesHost(node, e.hostname));
    }
    return map;
  }, [offlineNodes, dmesgEvents]);

  const patternsPerNode = useMemo(() => {
    const map = {};
    for (const node of offlineNodes) {
      map[node.id] = (detectedLogPatterns || []).filter(p =>
        (p.nodes || []).some(n => nodeMatchesHost(node, n))
      );
    }
    return map;
  }, [offlineNodes, detectedLogPatterns]);

  if (!offlineNodes.length) return null;

  const logPerNode = logTimeframe?.per_node || {};

  return (
    <div className="border" style={{ borderColor: "var(--ss-divider)", background: "var(--ss-white)" }}>
      <div className="border-b px-4 py-3" style={{ borderColor: "var(--ss-divider)" }}>
        <div className="flex items-center gap-1">
          <h3 className="text-sm font-bold tracking-tight" style={{ fontFamily: "Inter, sans-serif" }}>
            🔴 Offline Node Details
          </h3>
          <InfoHint
            label="offline node details"
            content="Correlates MV_EVENTS, tracelog coverage, kernel evidence, and known log patterns for nodes that were not ONLINE in the report snapshot."
          />
        </div>
        <p className="text-xs mt-0.5" style={{ color: "var(--ss-mid-gray)" }}>
          MV_EVENTS timeline, tracelog window, and crash evidence for each node not currently ONLINE
        </p>
      </div>

      <div className="divide-y" style={{ borderColor: "var(--divider-light)" }}>
        {offlineNodes.map(node => {
          const events = eventsPerNode[node.id] || [];
          const dmesg = dmesgPerNode[node.id] || [];
          const patterns = patternsPerNode[node.id] || [];

          // Find log timeframe by IP
          const tfKey = Object.keys(logPerNode).find(k =>
            node.ip_addr && (k.includes(node.ip_addr) || node.ip_addr.includes(k))
          );
          const tf = tfKey ? logPerNode[tfKey] : null;

          // Infer crash reason
          const hasCrash = patterns.some(p => p.category === "crash");
          const hasOom = patterns.some(p => p.category === "oom") || dmesg.some(d => d.category === "oom");
          const hasDisk = patterns.some(p => p.category === "disk");
          const hasRestart = patterns.some(p => p.category === "restart");

          let crashReason = null;
          if (hasCrash)        crashReason = "Crash / backtrace detected in SingleStore tracelogs";
          else if (hasOom)     crashReason = "OOM kill detected — Linux OOM-killer terminated the process";
          else if (hasDisk)    crashReason = "Disk full condition detected — write operations likely failed";
          else if (hasRestart) crashReason = "Process restart detected in tracelogs — check preceding entries for cause";
          else if (events.length > 0) {
            const e = events[0];
            crashReason = e.event_type + (e.description ? ` — ${e.description.slice(0, 120)}` : "");
          }

          const downEvent = events.find(e => e.category === "node_down");
          const upEvent   = events.find(e => e.category === "node_up");

          return (
            <div key={node.id} className="p-4">
              {/* Node header */}
              <div className="flex items-center gap-3 mb-3 flex-wrap">
                <span className={`text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 ${
                  node.type === "MA" ? "bg-[var(--ss-purple)] text-white"
                  : node.type === "CA" ? "bg-zinc-700 text-white"
                  : "bg-zinc-100 text-zinc-600"
                }`}>{node.type || "NODE"}</span>
                <span className="font-mono text-sm font-semibold">{node.ip_addr || `Node ${node.id}`}</span>
                <span className="text-[10px] uppercase tracking-widest font-bold px-1.5 py-0.5 badge-critical">
                  {(node.state || "offline").toUpperCase()}
                </span>
                {node.availability_group && node.availability_group !== "NULL" && (
                  <span className="text-[10px] font-mono px-1.5 py-0.5 border"
                    style={{ borderColor: "var(--ss-divider)", color: "var(--ss-mid-gray)" }}>
                    AG {node.availability_group}
                  </span>
                )}
                {tf && tf.first_log_entry && (
                  <span className="text-[10px] font-mono ml-auto" style={{ color: "var(--ss-mid-gray)" }}>
                    Tracelog: {fmtTs(tf.first_log_entry)} → {fmtTs(tf.last_log_entry)} ({tf.coverage_hours}h)
                  </span>
                )}
              </div>

              {/* Inferred crash reason */}
              {crashReason && (
                <div className="mb-3 text-xs rounded px-3 py-2" style={{
                  background: "rgba(244,67,54,0.07)",
                  border: "1px solid rgba(244,67,54,0.25)",
                  color: "var(--text-secondary)",
                }}>
                  ⚠️ <b>Likely cause:</b> {crashReason}
                </div>
              )}

              {/* Down / up timestamps */}
              {(downEvent || upEvent) && (
                <div className="flex flex-wrap items-center gap-6 mb-3 text-[11px]">
                  {downEvent && (
                    <span>
                      <span style={{ color: "var(--ss-mid-gray)" }}>Went offline: </span>
                      <span className="font-mono font-semibold" style={{ color: "#F44336" }}>{fmtTs(downEvent.event_time)}</span>
                    </span>
                  )}
                  {upEvent && (
                    <span>
                      <span style={{ color: "var(--ss-mid-gray)" }}>Last recovery: </span>
                      <span className="font-mono font-semibold" style={{ color: "#00C853" }}>{fmtTs(upEvent.event_time)}</span>
                    </span>
                  )}
                </div>
              )}

              {/* MV_EVENTS timeline */}
              {events.length > 0 && (
                <div className="mb-3">
                  <p className="text-[9px] uppercase tracking-widest font-bold mb-1.5" style={{ color: "var(--ss-mid-gray)" }}>
                    MV_EVENTS Timeline
                  </p>
                  <div className="space-y-1">
                    {events.slice(0, 8).map((evt, i) => (
                      <div key={i} className="flex items-start gap-2 text-[10px]">
                        <span>{CATEGORY_ICON[evt.category] || "•"}</span>
                        <span className="font-mono flex-shrink-0" style={{ color: "var(--ss-mid-gray)", minWidth: "9.5rem" }}>
                          {fmtTs(evt.event_time)}
                        </span>
                        <span className="font-semibold flex-shrink-0 uppercase tracking-wide"
                          style={{ color: CATEGORY_COLOR[evt.category] || "var(--text-primary)", minWidth: "8rem" }}>
                          {evt.event_type}
                        </span>
                        {evt.description && (
                          <span className="truncate" style={{ color: "var(--text-body)" }} title={evt.description}>
                            {evt.description.slice(0, 120)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* dmesg kernel evidence */}
              {dmesg.length > 0 && (
                <div className="mb-3">
                  <p className="text-[9px] uppercase tracking-widest font-bold mb-1.5" style={{ color: "var(--ss-mid-gray)" }}>
                    OS Kernel Evidence (dmesg)
                  </p>
                  {dmesg.slice(0, 3).map((d, i) => (
                    <div key={i} className="text-[10px] font-mono mb-1" style={{ color: "#F44336" }}>
                      [{d.severity}] {d.title} — {(d.line || "").slice(0, 120)}
                    </div>
                  ))}
                </div>
              )}

              {/* Critical tracelog patterns */}
              {patterns.length > 0 && (
                <div>
                  <p className="text-[9px] uppercase tracking-widest font-bold mb-1.5" style={{ color: "var(--ss-mid-gray)" }}>
                    Critical Tracelog Patterns
                  </p>
                  {patterns.slice(0, 4).map((p, i) => (
                    <div key={i} className="text-[10px] mb-1 flex items-center gap-2">
                      <span className={`text-[9px] uppercase tracking-widest font-bold px-1 py-0.5 ${p.severity === "critical" ? "badge-critical" : "badge-warning"}`}>
                        {p.severity}
                      </span>
                      <span className="font-medium">{p.title}</span>
                      {p.count > 1 && (
                        <span className="font-mono" style={{ color: "var(--ss-mid-gray)" }}>×{p.count}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {!events.length && !dmesg.length && !patterns.length && !crashReason && (
                <p className="text-xs italic" style={{ color: "var(--ss-mid-gray)" }}>
                  No MV_EVENTS or tracelog evidence for this node in the report. Check the Recommendations tab for guidance.
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

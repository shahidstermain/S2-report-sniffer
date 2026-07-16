import { useState, useMemo } from "react";
import { Server, HardDrive, MemoryStick, Clock, Layers, Network } from "lucide-react";
import { formatMegabytes, formatUptime } from "@/lib/utils-sdb";

/**
 * Interactive SVG-based cluster topology map for the SingleStore Report Sniffer.
 *
 * Props:
 *  - nodesDetail:    array of node objects
 *  - clusterLayout:  { by_host, total_partitions }
 *  - logTimeframe:   { per_node }
 *  - onSelectNode:   optional callback(node)
 *  - selectedNode:   optional node id to highlight
 */
export default function TopologyMap({ nodesDetail = [], clusterLayout = {}, logTimeframe = {}, onSelectNode, selectedNode }) {
  const [hovered, setHovered] = useState(null);
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 });

  const layoutByHost = clusterLayout.by_host || {};
  const logPerNode = logTimeframe.per_node || {};

  // Match a node's IP/id to layout and log timeframes
  const matchHost = (keys, ip, id) =>
    keys.find((h) => h === ip) ||
    keys.find((h) => h.endsWith(`:${ip}`) || (ip && ip.endsWith(`:${h}`))) ||
    (id != null && keys.find((h) => h === String(id))) ||
    null;

  const enrichedNodes = useMemo(() => {
    return nodesDetail.map((node) => {
      const memKnown = node.max_memory_mb > 0 && node.memory_used_mb != null;
      const memPct = memKnown ? Math.round((Number(node.memory_used_mb) / node.max_memory_mb) * 100) : null;
      const diskKnown = node.total_disk_mb > 0 && node.available_disk_mb != null;
      const diskUsedMb = diskKnown ? (node.total_disk_mb - Number(node.available_disk_mb)) : null;
      const diskPct = diskKnown ? Math.round((diskUsedMb / node.total_disk_mb) * 100) : null;
      const isOnline = node.state === "online";
      const stateKnown = !!(node.state && String(node.state).trim());
      const layoutKey = matchHost(Object.keys(layoutByHost), node.ip_addr, node.id);
      const nodeLayout = layoutKey ? layoutByHost[layoutKey] : null;
      const tfKey = matchHost(Object.keys(logPerNode), node.ip_addr, node.id);
      const nodeTf = tfKey ? logPerNode[tfKey] : null;
      return {
        ...node,
        memPct,
        diskUsedMb,
        diskPct,
        isOnline,
        stateKnown,
        nodeLayout,
        partitions: nodeLayout?.total ?? null,
        nodeTf,
      };
    });
  }, [nodesDetail, layoutByHost, logPerNode]);

  const maNodes = enrichedNodes.filter((n) => n.type === "MA");
  const caNodes = enrichedNodes.filter((n) => n.type === "CA");
  const leafNodes = enrichedNodes.filter((n) => n.type !== "MA" && n.type !== "CA" && (n.type === "LEAF" || /leaf/i.test(n.type || "")));

  // Fallback: if no LEAF-typed nodes, treat non-aggregators as leaves
  const leafList = leafNodes.length > 0 ? leafNodes : enrichedNodes.filter((n) => n.type !== "MA" && n.type !== "CA");

  const totalNodes = enrichedNodes.length || 1;
  const svgWidth = Math.max(800, totalNodes * 180);
  const svgHeight = 340;
  const centerX = svgWidth / 2;

  // Position nodes
  const ma = maNodes[0] || null;
  const ca = caNodes[0] || null;

  const leaves = leafList.map((n, i) => {
    const count = leafList.length || 1;
    const span = Math.min(svgWidth - 160, count * 180);
    const startX = centerX - span / 2;
    const step = count > 1 ? span / (count - 1) : 0;
    return { node: n, x: count > 1 ? startX + i * step : centerX, y: 260 };
  });

  // Helper colors
  const barColor = (pct) => (pct > 90 ? "var(--ss-critical)" : pct > 75 ? "var(--ss-warning)" : "var(--ss-success)");
  const roleColor = (type) => (type === "MA" ? "#AA00FF" : type === "CA" ? "var(--bg-zinc-800)" : "var(--ss-mid-gray)");

  // Node box layout (local SVG coords per node)
  const NODE_W = 168;
  const NODE_H = 96;

  const renderNode = (node, x, y, role) => {
    const isSelected = selectedNode != null && String(selectedNode) === String(node.id);
    const isHovered = hovered && hovered.id === node.id;
    const tx = x - NODE_W / 2;
    const ty = y - NODE_H / 2;

    return (
      <g
        key={node.id}
        transform={`translate(${tx}, ${ty})`}
        style={{ cursor: "pointer" }}
        onMouseEnter={(e) => {
          setHovered(node);
          setHoverPos({ x: e.clientX, y: e.clientY });
        }}
        onMouseMove={(e) => setHoverPos({ x: e.clientX, y: e.clientY })}
        onMouseLeave={() => setHovered(null)}
        onClick={() => onSelectNode?.(node)}
      >
        {/* Selection glow */}
        {isSelected && (
          <rect
            x={-4}
            y={-4}
            width={NODE_W + 8}
            height={NODE_H + 8}
            rx={12}
            ry={12}
            fill="none"
            stroke="var(--ss-purple)"
            strokeWidth={3}
            opacity={0.9}
            style={{ filter: "drop-shadow(0 0 6px var(--ss-purple))" }}
          />
        )}
        {/* Node body */}
        <rect
          width={NODE_W}
          height={NODE_H}
          rx={10}
          ry={10}
          fill="var(--bg-node-card)"
          stroke={isHovered ? "var(--ss-purple)" : "var(--ss-divider)"}
          strokeWidth={isHovered ? 2 : 1}
        />
        {/* Role badge */}
        <rect x={8} y={6} width={28} height={14} rx={3} ry={3} fill={roleColor(role)} />
        <text x={22} y={16} textAnchor="middle" fontSize={9} fontWeight={700} fill={role === "LEAF" ? "var(--ss-white)" : "#FFFFFF"} style={{ letterSpacing: "0.1em" }}>
          {role}
        </text>

        {/* Status dot */}
        <circle
          cx={NODE_W - 14}
          cy={13}
          r={5}
          fill={
            !node.stateKnown
              ? "var(--ss-mid-gray)"
              : node.isOnline
              ? "var(--green-bright)"
              : "var(--red-bright)"
          }
          className={node.stateKnown && !node.isOnline ? "pulse-dot" : ""}
        />

        {/* Hostname */}
        <text x={8} y={32} fontSize={10} fontFamily="JetBrains Mono, monospace" fill="var(--text-body)" fontWeight={600}>
          {(node.ip_addr || "—").slice(0, 22)}
        </text>

        {/* Memory bar */}
        <text x={8} y={48} fontSize={8} fill="var(--ss-mid-gray)" fontWeight={700} style={{ letterSpacing: "0.1em" }}>MEM</text>
        <rect x={34} y={42} width={NODE_W - 44} height={8} rx={2} fill="var(--divider-light)" />
        {node.memPct != null && (
          <rect x={34} y={42} width={(NODE_W - 44) * Math.min(node.memPct, 100) / 100} height={8} rx={2} fill={barColor(node.memPct)} />
        )}
        <text x={NODE_W - 8} y={49} textAnchor="end" fontSize={8} fontFamily="JetBrains Mono, monospace" fill="var(--text-body)">
          {node.memPct == null ? "—" : `${node.memPct}%`}
        </text>

        {/* Disk bar */}
        <text x={8} y={66} fontSize={8} fill="var(--ss-mid-gray)" fontWeight={700} style={{ letterSpacing: "0.1em" }}>DISK</text>
        <rect x={34} y={60} width={NODE_W - 44} height={8} rx={2} fill="var(--divider-light)" />
        {node.diskPct != null && (
          <rect x={34} y={60} width={(NODE_W - 44) * Math.min(node.diskPct, 100) / 100} height={8} rx={2} fill={barColor(node.diskPct)} />
        )}
        <text x={NODE_W - 8} y={67} textAnchor="end" fontSize={8} fontFamily="JetBrains Mono, monospace" fill="var(--text-body)">
          {node.diskPct == null ? "—" : `${node.diskPct}%`}
        </text>

        {/* Partitions badge + AG */}
        <g>
          {node.availability_group && node.availability_group !== "NULL" && (
            <>
              <rect x={8} y={78} width={26} height={12} rx={2} fill="none" stroke="var(--ss-divider)" />
              <text x={21} y={87} textAnchor="middle" fontSize={8} fontFamily="JetBrains Mono, monospace" fill="var(--ss-mid-gray)">AG{node.availability_group}</text>
            </>
          )}
          {node.partitions != null && node.partitions > 0 && (
            <>
              <rect x={NODE_W - 42} y={78} width={34} height={12} rx={2} fill="var(--ss-purple-badge)" stroke="var(--ss-purple)" />
              <text x={NODE_W - 25} y={87} textAnchor="middle" fontSize={8} fontFamily="JetBrains Mono, monospace" fill="var(--ss-purple)" fontWeight={700}>{node.partitions}P</text>
            </>
          )}
        </g>
      </g>
    );
  };

  const renderConnection = (from, to, key) => {
    if (!from || !to) return null;
    const x1 = from.x;
    const y1 = from.y + NODE_H / 2;
    const x2 = to.x;
    const y2 = to.y - NODE_H / 2;
    const midY = (y1 + y2) / 2;
    const path = `M ${x1},${y1} Q ${x1},${midY} ${(x1 + x2) / 2},${midY} T ${x2},${y2}`;
    return (
      <path
        key={key}
        d={path}
        fill="none"
        stroke="var(--ss-mid-gray)"
        strokeWidth={1.5}
        strokeDasharray="4 3"
        markerEnd="url(#arrow)"
        opacity={0.7}
      />
    );
  };

  const maPos = ma ? { x: centerX, y: 40 } : null;
  const caPos = ca ? { x: centerX, y: 140 } : null;

  const maxPartitions = useMemo(
    () => Math.max(1, ...enrichedNodes.map((n) => n.partitions || 0)),
    [enrichedNodes]
  );

  const tooltip = hovered ? (
    <div
      style={{
        position: "fixed",
        left: hoverPos.x + 14,
        top: hoverPos.y + 14,
        zIndex: 50,
        pointerEvents: "none",
        background: "var(--ss-charcoal)",
        color: "var(--ss-white)",
        border: "1px solid var(--ss-divider)",
        borderRadius: 8,
        padding: "10px 12px",
        fontSize: 11,
        fontFamily: "JetBrains Mono, monospace",
        boxShadow: "0 4px 16px rgba(0,0,0,0.25)",
        maxWidth: 280,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        <span
          style={{
            background: roleColor(hovered.type),
            color: "#fff",
            padding: "1px 6px",
            borderRadius: 3,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.1em",
          }}
        >
          {hovered.type}
        </span>
        <span
          style={{
            color: !hovered.stateKnown
              ? "var(--ss-mid-gray)"
              : hovered.isOnline
              ? "var(--ss-success)"
              : "var(--ss-critical)",
            fontWeight: 700,
          }}
        >
          {!hovered.stateKnown ? "UNKNOWN" : hovered.isOnline ? "ONLINE" : "OFFLINE"}
        </span>
      </div>
      <div style={{ color: "var(--ss-white)", fontWeight: 700, marginBottom: 4 }}>{hovered.ip_addr}</div>
      <Row label="ID" value={hovered.id} />
      <Row label="Version" value={hovered.version} />
      <Row label="Uptime" value={formatUptime(hovered.uptime_seconds)} />
      <Row label="AG" value={hovered.availability_group && hovered.availability_group !== "NULL" ? hovered.availability_group : "—"} />
      <Row
        label="Memory"
        value={
          hovered.memPct == null
            ? "—"
            : `${formatMegabytes(hovered.memory_used_mb)} / ${formatMegabytes(hovered.max_memory_mb)} (${hovered.memPct}%)`
        }
      />
      <Row
        label="Disk"
        value={
          hovered.diskPct == null
            ? "—"
            : `${formatMegabytes(hovered.diskUsedMb)} / ${formatMegabytes(hovered.total_disk_mb)} (${hovered.diskPct}%)`
        }
      />
      <Row label="Partitions" value={hovered.partitions != null && hovered.partitions > 0 ? hovered.partitions : "—"} />
      {hovered.nodeTf && hovered.nodeTf.coverage_hours > 0 && (
        <Row label="Logs" value={`${hovered.nodeTf.coverage_hours}h coverage`} />
      )}
    </div>
  ) : null;

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <div style={{ width: "100%", overflowX: "auto" }}>
        <svg
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          width="100%"
          preserveAspectRatio="xMidYMid meet"
          style={{ display: "block", minWidth: 600 }}
        >
          <defs>
            <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="var(--ss-mid-gray)" />
            </marker>
          </defs>

          {/* Connections */}
          {maPos && caPos && renderConnection(maPos, caPos, "ma-ca")}
          {maPos && leaves.map((l, i) => renderConnection(maPos, l, `ma-leaf-${i}`))}
          {!maPos && caPos && leaves.map((l, i) => renderConnection(caPos, l, `ca-leaf-${i}`))}

          {/* Nodes */}
          {maPos && ma && renderNode(ma, maPos.x, maPos.y, "MA")}
          {caPos && ca && renderNode(ca, caPos.x, caPos.y, "CA")}
          {leaves.map((l) => renderNode(l.node, l.x, l.y, "LEAF"))}
        </svg>
      </div>

      {/* Partition heatmap strip */}
      <div style={{ marginTop: 8, padding: "8px 12px", borderTop: "1px solid var(--ss-divider)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
          <Layers size={11} style={{ color: "var(--ss-mid-gray)" }} />
          <span style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.15em", fontWeight: 700, color: "var(--ss-mid-gray)" }}>
            Partition Heatmap
          </span>
          {clusterLayout.total_partitions > 0 && (
            <span style={{ fontSize: 10, fontFamily: "JetBrains Mono, monospace", color: "var(--ss-purple)" }}>
              {clusterLayout.total_partitions} total
            </span>
          )}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {enrichedNodes.map((n) => {
            const intensity = (n.partitions || 0) / maxPartitions;
            const bg =
              n.partitions > 0
                ? `rgba(170, 0, 255, ${Math.max(0.15, intensity)})`
                : "var(--divider-light)";
            return (
              <div
                key={n.id}
                title={`${n.ip_addr || n.id}: ${n.partitions == null ? "unknown partitions" : `${n.partitions} partitions`}`}
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: 3,
                  background: bg,
                  border: "1px solid var(--ss-divider)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 8,
                  fontFamily: "JetBrains Mono, monospace",
                  color: intensity > 0.5 ? "#fff" : "var(--ss-mid-gray)",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
                onClick={() => onSelectNode?.(n)}
              >
                {n.partitions == null ? "?" : n.partitions > 0 ? n.partitions : "·"}
              </div>
            );
          })}
        </div>
      </div>

      {tooltip}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, lineHeight: 1.4 }}>
      <span style={{ color: "var(--ss-mid-gray)", fontSize: 9, textTransform: "uppercase", letterSpacing: "0.1em" }}>{label}</span>
      <span style={{ color: "var(--ss-white)", textAlign: "right" }}>{value ?? "—"}</span>
    </div>
  );
}
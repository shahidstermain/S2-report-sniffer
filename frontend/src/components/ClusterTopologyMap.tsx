import { useEffect, useRef, useMemo, useState } from "react";
import * as d3 from "d3";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { asRowList, cn } from "@/lib/utils";
import { formatMegabytes, formatUptime } from "@/lib/utils-sdb";
import InfoHint from "./InfoHint";

/**
 * Tiered cluster topology map — MA / CA / Leaf bands with replication edges,
 * lag severity coloring, and per-node resource rings.
 */

interface NodeDetail {
  id?: string | number;
  ip_addr?: string;
  port?: string | number;
  type?: string;
  state?: string;
  availability_group?: string;
  num_cpus?: number;
  max_memory_mb?: number;
  memory_used_mb?: number;
  total_disk_mb?: number;
  available_disk_mb?: number;
  uptime_seconds?: number;
  version?: string;
}

interface ClusterNode {
  id: string;
  role: "master" | "leaf" | "aggregator" | "unknown";
  partitions: number;
  masterPartitions: number;
  slavePartitions: number;
  status: "online" | "offline" | "unknown";
  health: "healthy" | "warning" | "critical" | "unknown";
  availabilityGroup?: string;
  memPct: number | null;
  engineMemPct: number | null;
  diskPct: number | null;
  detail?: NodeDetail;
}

interface ClusterEdge {
  source: string;
  target: string;
  type: "replication";
  lagSec?: number;
  severity?: "healthy" | "warning" | "critical";
  connected?: string;
}

interface LayoutNode extends ClusterNode {
  x: number;
  y: number;
  band: "master" | "aggregator" | "leaf";
}

interface ClusterTopologyMapProps {
  clusterLayout?: {
    by_host?: Record<string, { master: number; slave: number; total: number }>;
    total_partitions?: number;
    by_role?: Record<string, number>;
  };
  clusterOverview?: {
    total_nodes?: number;
    online_nodes?: number;
    offline_nodes?: number;
    memory_used_pct?: number;
    disk_used_pct?: number;
    /** List or legacy `{ rows: [...] }` wrapper from persisted payloads. */
    nodes_detail?: NodeDetail[] | { rows?: NodeDetail[] };
  };
  nodeEvents?: Array<{
    node_id: string;
    event_type: string;
    severity?: string;
    description?: string;
  }>;
  replicationStatus?: Array<{
    MasterHost?: string;
    SlaveHost?: string;
  }>;
  replicationLagPatterns?: {
    lagging_pairs?: Array<{
      master: string;
      slave: string;
      lag_sec?: number;
      severity?: string;
      connected?: string;
    }>;
    replication_state?: string;
    lagging_count?: number;
    max_lag_sec?: number;
  };
  memoryUtilization?: {
    per_node?: Record<string, {
      hostname?: string;
      status?: string;
      memory_pct?: number;
      engine_used_pct?: number;
    }>;
    nodes?: Array<{
      hostname?: string;
      status?: string;
      memory_pct?: number;
      engine_used_pct?: number;
    }>;
  };
}

const ROLE_COLORS: Record<string, string> = {
  master: "#E85D5D",
  leaf: "#00d992",
  aggregator: "#6B8CFF",
  unknown: "#8B8FA3",
};

const STATUS_COLORS: Record<string, string> = {
  healthy: "#00d992",
  warning: "#FF9800",
  critical: "#F44336",
  offline: "#6B7280",
  unknown: "#8B8FA3",
};

const LAG_COLORS: Record<string, string> = {
  healthy: "rgba(0, 217, 146, 0.55)",
  warning: "rgba(255, 152, 0, 0.75)",
  critical: "rgba(244, 67, 54, 0.85)",
};

const ROLE_LABELS: Record<string, string> = {
  master: "Master Aggregator (MA)",
  leaf: "Leaf",
  aggregator: "Aggregator (CA)",
  unknown: "Unknown",
};

const BAND_LABELS: Record<string, string> = {
  master: "Master tier",
  aggregator: "Aggregator tier",
  leaf: "Leaf tier",
};

function matchHost(keys: string[], ip: string | undefined): string | null {
  if (!ip) return null;
  return (
    keys.find((h) => h === ip) ||
    keys.find((h) => h.endsWith(`:${ip}`) || (ip && ip.endsWith(`:${h}`))) ||
    null
  );
}

function roleFromDetailType(type: string | undefined): ClusterNode["role"] {
  const t = (type || "").toUpperCase();
  if (t === "MA" || t === "MASTER") return "master";
  if (t === "CA" || t === "AGGREGATOR") return "aggregator";
  if (t === "LEAF") return "leaf";
  return "unknown";
}

function memDiskPct(nd: NodeDetail): { memPct: number | null; diskPct: number | null } {
  let memPct: number | null = null;
  let diskPct: number | null = null;
  if (nd.max_memory_mb && nd.max_memory_mb > 0 && nd.memory_used_mb != null) {
    memPct = (Number(nd.memory_used_mb) / nd.max_memory_mb) * 100;
  }
  if (nd.total_disk_mb && nd.total_disk_mb > 0 && nd.available_disk_mb != null) {
    diskPct = ((nd.total_disk_mb - Number(nd.available_disk_mb)) / nd.total_disk_mb) * 100;
  }
  return { memPct, diskPct };
}

function normalizeMemoryRows(
  memoryUtilization?: ClusterTopologyMapProps["memoryUtilization"]
): Array<{ hostname: string; status?: string; memory_pct?: number; engine_used_pct?: number }> {
  if (!memoryUtilization) return [];
  if (Array.isArray(memoryUtilization.nodes)) {
    return memoryUtilization.nodes
      .filter((node) => !!node?.hostname)
      .map((node) => ({ ...node, hostname: String(node.hostname) }));
  }
  const perNode = memoryUtilization.per_node;
  if (perNode && typeof perNode === "object") {
    return Object.entries(perNode).map(([hostname, metrics]) => ({
      ...(metrics || {}),
      hostname,
    }));
  }
  return [];
}

export function buildTopologyGraph(
  clusterLayout?: ClusterTopologyMapProps["clusterLayout"],
  clusterOverview?: ClusterTopologyMapProps["clusterOverview"],
  nodeEvents?: ClusterTopologyMapProps["nodeEvents"],
  replicationStatus?: ClusterTopologyMapProps["replicationStatus"],
  replicationLagPatterns?: ClusterTopologyMapProps["replicationLagPatterns"],
  memoryUtilization?: ClusterTopologyMapProps["memoryUtilization"]
): { nodes: ClusterNode[]; edges: ClusterEdge[] } {
  const nodes: ClusterNode[] = [];
  const edges: ClusterEdge[] = [];
  const nodeMap = new Map<string, ClusterNode>();
  const detailByHost = new Map<string, NodeDetail>();
  const nodesDetail = asRowList<NodeDetail>(clusterOverview?.nodes_detail);

  if (nodesDetail.length) {
    for (const nd of nodesDetail) {
      const ip = nd.ip_addr || String(nd.id || "");
      if (ip) detailByHost.set(ip, nd);
    }
  }

  if (clusterLayout?.by_host) {
    for (const [hostname, counts] of Object.entries(clusterLayout.by_host)) {
      const detail =
        detailByHost.get(hostname) ||
        [...detailByHost.entries()].find(([k]) => matchHost([hostname], k))?.[1];
      // Role comes only from nodes_detail.type — never promote from partition master counts.
      let role: ClusterNode["role"] = "leaf";
      if (detail?.type) {
        role = roleFromDetailType(detail.type);
      }

      const { memPct, diskPct } = detail ? memDiskPct(detail) : { memPct: null, diskPct: null };
      const node: ClusterNode = {
        id: hostname,
        role,
        partitions: counts.total || 0,
        masterPartitions: counts.master || 0,
        slavePartitions: counts.slave || 0,
        status: detail?.state ? ((detail.state || "").toLowerCase() === "online" ? "online" : "offline") : "unknown",
        health: "unknown",
        availabilityGroup: detail?.availability_group,
        memPct,
        engineMemPct: null,
        diskPct,
        detail,
      };
      nodeMap.set(hostname, node);
      nodes.push(node);
    }
  }

  if (nodesDetail.length) {
    for (const nd of nodesDetail) {
      const ip = nd.ip_addr || String(nd.id || "");
      const matchKey = matchHost(Array.from(nodeMap.keys()), ip) || ip;
      let node = nodeMap.get(matchKey);
      if (!node && ip) {
        const { memPct, diskPct } = memDiskPct(nd);
        node = {
          id: ip,
          role: roleFromDetailType(nd.type),
          partitions: 0,
          masterPartitions: 0,
          slavePartitions: 0,
          status: (nd.state || "").toLowerCase() === "online" ? "online" : ((nd.state || "").trim() ? "offline" : "unknown"),
          health: "unknown",
          availabilityGroup: nd.availability_group,
          memPct,
          engineMemPct: null,
          diskPct,
          detail: nd,
        };
        nodeMap.set(ip, node);
        nodes.push(node);
      }
      if (node && nd) {
        node.detail = nd;
        node.role = roleFromDetailType(nd.type) !== "unknown" ? roleFromDetailType(nd.type) : node.role;
        node.availabilityGroup = nd.availability_group || node.availabilityGroup;
        const { memPct, diskPct } = memDiskPct(nd);
        node.memPct = memPct;
        node.diskPct = diskPct;
        if (nd.state) {
          node.status = nd.state.toLowerCase() === "online" ? "online" : "offline";
        }
      }
    }
  }

  for (const mu of normalizeMemoryRows(memoryUtilization)) {
      const host = mu.hostname;
      if (!host) continue;
      const matchKey = matchHost(Array.from(nodeMap.keys()), host) || host;
      const node = nodeMap.get(matchKey);
      if (!node) continue;
      const pctRaw = mu.engine_used_pct ?? mu.memory_pct;
      const pct = pctRaw == null ? null : Number(pctRaw);
      if (pct != null && Number.isFinite(pct)) {
        node.engineMemPct = pct;
      }
      if (mu.status === "critical") {
        node.health = "critical";
      } else if (mu.status === "warning" && node.health !== "critical") {
        node.health = "warning";
      }
  }

  if (nodeEvents) {
    for (const event of nodeEvents) {
      const nodeId = event.node_id;
      if (!nodeId) continue;
      const matchKey = matchHost(Array.from(nodeMap.keys()), nodeId) || nodeId;
      const node = nodeMap.get(matchKey);
      if (!node) continue;
      if (event.event_type?.toLowerCase().includes("offline")) {
        node.status = "offline";
      }
      if (event.severity === "CRITICAL" || event.severity === "critical") {
        node.health = "critical";
      } else if (
        (event.severity === "WARNING" || event.severity === "warning") &&
        node.health !== "critical"
      ) {
        node.health = "warning";
      }
    }
  }

  type LaggingPair = NonNullable<
    NonNullable<ClusterTopologyMapProps["replicationLagPatterns"]>["lagging_pairs"]
  >[number];
  const lagByPair = new Map<string, LaggingPair>();
  for (const pair of replicationLagPatterns?.lagging_pairs || []) {
    lagByPair.set(`${pair.master}::${pair.slave}`, pair);
  }

  const edgeKeys = new Set<string>();
  const addEdge = (master?: string, slave?: string) => {
    if (!master || !slave) return;
    const key = `${master}::${slave}`;
    if (edgeKeys.has(key)) return;
    edgeKeys.add(key);
    const lag = lagByPair.get(key);
    edges.push({
      source: master,
      target: slave,
      type: "replication",
      lagSec: lag?.lag_sec,
      severity: (lag?.severity as ClusterEdge["severity"]) || "healthy",
      connected: lag?.connected,
    });
  };

  for (const rep of replicationStatus || []) {
    addEdge(rep.MasterHost, rep.SlaveHost);
  }
  for (const pair of replicationLagPatterns?.lagging_pairs || []) {
    addEdge(pair.master, pair.slave);
  }

  return { nodes, edges };
}

function computeTieredLayout(nodes: ClusterNode[], width: number): LayoutNode[] {
  const bandY: Record<string, number> = { master: 72, aggregator: 210, leaf: 348 };
  const grouped: Record<string, ClusterNode[]> = {
    master: [],
    aggregator: [],
    leaf: [],
    unknown: [],
  };
  for (const node of nodes) {
    const band = node.role === "unknown" ? "leaf" : node.role;
    grouped[band].push(node);
  }

  const layout: LayoutNode[] = [];
  for (const band of ["master", "aggregator", "leaf"] as const) {
    const list = grouped[band];
    if (!list.length) continue;
    const agGroups = new Map<string, ClusterNode[]>();
    for (const n of list) {
      const ag = n.availabilityGroup || "default";
      if (!agGroups.has(ag)) agGroups.set(ag, []);
      agGroups.get(ag)!.push(n);
    }
    const agKeys = [...agGroups.keys()].sort();
    const totalSlots = list.length;
    let slot = 0;
    for (const ag of agKeys) {
      const group = agGroups.get(ag)!;
      group.sort((a, b) => b.partitions - a.partitions);
      for (const node of group) {
        slot += 1;
        const x = (width / (totalSlots + 1)) * slot;
        layout.push({ ...node, x, y: bandY[band], band });
      }
    }
  }
  return layout;
}

function nodeRadius(partitions: number): number {
  return 22 + Math.min(partitions, 24) * 1.2;
}

function shortHost(id: string): string {
  const shortId = id.split(".")[0] || id;
  return shortId.length > 14 ? `${shortId.slice(0, 12)}…` : shortId;
}

function edgePath(x1: number, y1: number, x2: number, y2: number): string {
  const midY = (y1 + y2) / 2;
  return `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
}

function resourceRing(r: number, pct: number | null | undefined, color: string, offset: number): string {
  const c = 2 * Math.PI * (r + offset);
  if (pct == null || !Number.isFinite(Number(pct))) {
    return `0 ${c}`;
  }
  const filled = Math.max(0, Math.min(100, Number(pct))) / 100;
  const dash = filled * c;
  return `${dash} ${c}`;
}

export default function ClusterTopologyMap({
  clusterLayout,
  clusterOverview,
  nodeEvents,
  replicationStatus,
  replicationLagPatterns,
  memoryUtilization,
}: ClusterTopologyMapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredNode, setHoveredNode] = useState<ClusterNode | null>(null);
  const [selectedNode, setSelectedNode] = useState<ClusterNode | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  const { nodes, edges } = useMemo(
    () =>
      buildTopologyGraph(
        clusterLayout,
        clusterOverview,
        nodeEvents,
        replicationStatus,
        replicationLagPatterns,
        memoryUtilization
      ),
    [
      clusterLayout,
      clusterOverview,
      nodeEvents,
      replicationStatus,
      replicationLagPatterns,
      memoryUtilization,
    ]
  );

  const layoutNodes = useMemo(() => {
    const width = 900;
    return computeTieredLayout(nodes, width);
  }, [nodes]);

  const nodeById = useMemo(() => new Map(layoutNodes.map((n) => [n.id, n])), [layoutNodes]);

  const partitionSkew = useMemo(() => {
    const counts = nodes.map((n) => n.partitions).filter((c) => c > 0);
    if (counts.length < 2) return null;
    const max = Math.max(...counts);
    const min = Math.min(...counts);
    const avg = counts.reduce((a, b) => a + b, 0) / counts.length;
    return { max, min, avg: Math.round(avg), ratio: min > 0 ? (max / min).toFixed(1) : "∞" };
  }, [nodes]);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>(".topology-zoom");
    if (g.empty()) return;

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.45, 3])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });

    svg.call(zoom as any);
    return () => {
      svg.on(".zoom", null);
    };
  }, [layoutNodes.length]);

  if (nodes.length === 0) {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <div className="flex items-center gap-1">
            <CardTitle>Cluster Topology</CardTitle>
            <InfoHint
              label="cluster topology"
              content="Tiered map of MA / CA / Leaf nodes with partition distribution, replication links, and resource pressure rings."
            />
          </div>
          <CardDescription>No cluster data available</CardDescription>
        </CardHeader>
        <CardContent className="text-center text-muted-foreground py-8">
          <p>Cluster topology will appear here once node data is available.</p>
        </CardContent>
      </Card>
    );
  }

  const onlineCount = nodes.filter((n) => n.status === "online").length;
  const offlineCount = nodes.filter((n) => n.status === "offline").length;
  const criticalCount = nodes.filter((n) => n.health === "critical").length;
  const warningCount = nodes.filter((n) => n.health === "warning").length;
  const replState = replicationLagPatterns?.replication_state || "unknown";
  const laggingCount = replicationLagPatterns?.lagging_count || 0;
  const maxLag = replicationLagPatterns?.max_lag_sec;
  const svgWidth = 900;
  const svgHeight = 440;

  return (
    <Card className="shadow-sm overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-1">
              <CardTitle>Cluster Topology</CardTitle>
              <InfoHint
                label="cluster topology"
                content="Tiered MA / CA / Leaf layout with replication edges colored by lag severity. Ring arcs show memory (inner) and disk (outer) utilization."
              />
            </div>
            <CardDescription>
              {nodes.length} nodes · {onlineCount} online
              {offlineCount > 0 ? ` · ${offlineCount} offline` : ""} ·{" "}
              {clusterLayout?.total_partitions || 0} partitions
              {edges.length > 0 ? ` · ${edges.length} replication links` : ""}
            </CardDescription>
          </div>
          <div className="flex gap-2 flex-wrap">
            <Badge
              variant={
                replState === "critical"
                  ? "critical"
                  : replState === "degraded"
                  ? "warning"
                  : replState === "healthy"
                  ? "healthy"
                  : "info"
              }
            >
              Replication {replState}
              {laggingCount > 0 ? ` · ${laggingCount} lagging` : ""}
              {maxLag != null && maxLag > 0 ? ` · max ${maxLag}s` : ""}
            </Badge>
            {criticalCount > 0 && <Badge variant="critical">{criticalCount} critical</Badge>}
            {warningCount > 0 && <Badge variant="warning">{warningCount} warning</Badge>}
            {offlineCount > 0 && <Badge variant="destructive">{offlineCount} offline</Badge>}
          </div>
        </div>

        {partitionSkew && (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
            <span className="font-medium text-foreground">Partition distribution</span>
            <span>
              min <strong>{partitionSkew.min}</strong> · avg <strong>{partitionSkew.avg}</strong> · max{" "}
              <strong>{partitionSkew.max}</strong>
            </span>
            <span
              className={cn(
                "px-2 py-0.5 rounded-full border",
                partitionSkew.ratio === "∞" || Number(partitionSkew.ratio) >= 2
                  ? "border-amber-500/40 text-amber-600 dark:text-amber-400"
                  : "border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
              )}
            >
              skew {partitionSkew.ratio}x
            </span>
          </div>
        )}
      </CardHeader>

      <CardContent className="p-0">
        <div
          className="relative overflow-hidden rounded-b-lg"
          style={{ background: "linear-gradient(180deg, hsl(var(--card)) 0%, hsl(240 18% 8%) 100%)" }}
        >
          <svg
            ref={svgRef}
            className="w-full"
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            style={{ height: "440px" }}
            role="img"
            aria-label="Cluster topology map"
          >
            <defs>
              <filter id="topo-glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <g className="topology-zoom">
              {/* Tier bands */}
              {(["master", "aggregator", "leaf"] as const).map((band) => {
                const y = band === "master" ? 40 : band === "aggregator" ? 178 : 316;
                const h = 120;
                const count = layoutNodes.filter((n) => n.band === band).length;
                if (!count) return null;
                return (
                  <g key={band}>
                    <rect
                      x={24}
                      y={y}
                      width={svgWidth - 48}
                      height={h}
                      rx={12}
                      fill="rgba(255,255,255,0.03)"
                      stroke="rgba(255,255,255,0.06)"
                    />
                    <text
                      x={36}
                      y={y + 18}
                      fill="rgba(255,255,255,0.45)"
                      fontSize={10}
                      fontWeight={600}
                      letterSpacing="0.08em"
                    >
                      {BAND_LABELS[band].toUpperCase()} ({count})
                    </text>
                  </g>
                );
              })}

              {/* Replication edges */}
              {edges.map((edge, i) => {
                const src = nodeById.get(edge.source);
                const tgt = nodeById.get(edge.target);
                if (!src || !tgt) return null;
                const severity = edge.severity || "healthy";
                const stroke = LAG_COLORS[severity] || LAG_COLORS.healthy;
                const sw = severity === "critical" ? 2.8 : severity === "warning" ? 2.2 : 1.6;
                return (
                  <g key={`${edge.source}-${edge.target}-${i}`}>
                    <path
                      d={edgePath(src.x, src.y, tgt.x, tgt.y)}
                      fill="none"
                      stroke={stroke}
                      strokeWidth={sw}
                      strokeDasharray={severity === "healthy" ? "6 5" : undefined}
                      opacity={0.85}
                    />
                    {edge.lagSec != null && edge.lagSec > 0 && (
                      <text
                        x={(src.x + tgt.x) / 2}
                        y={(src.y + tgt.y) / 2 - 6}
                        textAnchor="middle"
                        fill={severity === "critical" ? "#F44336" : "#FF9800"}
                        fontSize={9}
                        fontFamily="JetBrains Mono, monospace"
                      >
                        {edge.lagSec}s
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Nodes */}
              {layoutNodes.map((node) => {
                const r = nodeRadius(node.partitions);
                const selected = selectedNode?.id === node.id;
                const hovered = hoveredNode?.id === node.id;
                const memoryRingPct = node.engineMemPct;
                const fill =
                  node.status === "offline"
                    ? STATUS_COLORS.offline
                    : ROLE_COLORS[node.role] || ROLE_COLORS.unknown;
                const healthStroke =
                  node.health === "critical"
                    ? STATUS_COLORS.critical
                    : node.health === "warning"
                    ? STATUS_COLORS.warning
                    : selected
                    ? "#ffffff"
                    : "rgba(255,255,255,0.15)";

                return (
                  <g
                    key={node.id}
                    transform={`translate(${node.x}, ${node.y})`}
                    style={{ cursor: "pointer" }}
                    onMouseEnter={(e) => {
                      setHoveredNode(node);
                      setTooltipPos({ x: e.pageX, y: e.pageY });
                    }}
                    onMouseMove={(e) => setTooltipPos({ x: e.pageX, y: e.pageY })}
                    onMouseLeave={() => setHoveredNode(null)}
                    onClick={() => setSelectedNode((prev) => (prev?.id === node.id ? null : node))}
                  >
                    {(hovered || selected) && (
                      <circle r={r + 10} fill="none" stroke={fill} strokeWidth={1} opacity={0.35} filter="url(#topo-glow)" />
                    )}

                    {/* Disk ring */}
                    <circle
                      r={r + 6}
                      fill="none"
                      stroke="rgba(255,255,255,0.08)"
                      strokeWidth={3}
                    />
                    <circle
                      r={r + 6}
                      fill="none"
                      stroke={
                        node.diskPct == null
                          ? "rgba(255,255,255,0.08)"
                          : node.diskPct > 90
                          ? STATUS_COLORS.critical
                          : node.diskPct > 80
                          ? STATUS_COLORS.warning
                          : "rgba(107,140,255,0.7)"
                      }
                      strokeWidth={3}
                      strokeDasharray={resourceRing(r, node.diskPct, "", 6)}
                      transform="rotate(-90)"
                      strokeLinecap="round"
                      opacity={node.diskPct == null ? 0.2 : 1}
                    />

                    {/* Memory ring */}
                    <circle
                      r={r + 2}
                      fill="none"
                      stroke="rgba(255,255,255,0.08)"
                      strokeWidth={3}
                    />
                    <circle
                      r={r + 2}
                      fill="none"
                      stroke={
                        memoryRingPct == null
                          ? "rgba(255,255,255,0.08)"
                          : memoryRingPct > 90
                          ? STATUS_COLORS.critical
                          : memoryRingPct > 80
                          ? STATUS_COLORS.warning
                          : STATUS_COLORS.healthy
                      }
                      strokeWidth={3}
                      strokeDasharray={resourceRing(r, memoryRingPct, "", 2)}
                      transform="rotate(-90)"
                      strokeLinecap="round"
                      opacity={memoryRingPct == null ? 0.2 : 1}
                    />

                    <circle
                      r={r}
                      fill={fill}
                      stroke={healthStroke}
                      strokeWidth={selected ? 3 : node.health !== "healthy" ? 2.5 : 1.5}
                      opacity={node.status === "offline" ? 0.45 : 1}
                    />

                    <text
                      textAnchor="middle"
                      dy="0.35em"
                      fill="#0a0a0f"
                      fontSize={10}
                      fontWeight={700}
                      pointerEvents="none"
                    >
                      {node.role === "master" ? "MA" : node.role === "aggregator" ? "CA" : "L"}
                    </text>

                    {node.partitions > 0 && (
                      <g transform={`translate(${r - 4}, ${-r + 2})`}>
                        <circle r={9} fill="rgba(0,0,0,0.55)" />
                        <text textAnchor="middle" dy="0.35em" fill="#fff" fontSize={8} fontWeight={700}>
                          {node.partitions}
                        </text>
                      </g>
                    )}

                    <text
                      textAnchor="middle"
                      y={r + 16}
                      fill="rgba(255,255,255,0.75)"
                      fontSize={10}
                      fontFamily="Inter, sans-serif"
                      pointerEvents="none"
                    >
                      {shortHost(node.id)}
                    </text>
                    {node.availabilityGroup && (
                      <text
                        textAnchor="middle"
                        y={r + 28}
                        fill="rgba(255,255,255,0.35)"
                        fontSize={8}
                        fontFamily="JetBrains Mono, monospace"
                        pointerEvents="none"
                      >
                        AG {node.availabilityGroup}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>

          {hoveredNode && (
            <div
              className="fixed z-50 pointer-events-none bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg shadow-xl p-3 text-xs max-w-xs"
              style={{ left: tooltipPos.x + 14, top: tooltipPos.y + 14 }}
            >
              <div className="font-bold text-sm mb-1">{hoveredNode.id}</div>
              <div className="space-y-0.5 text-muted-foreground">
                <div>
                  <span className="font-medium">Role:</span> {ROLE_LABELS[hoveredNode.role]}
                </div>
                <div>
                  <span className="font-medium">Status:</span>{" "}
                  <span
                    className={
                      hoveredNode.status === "online"
                        ? "text-green-600"
                        : hoveredNode.status === "unknown"
                        ? "text-zinc-500"
                        : "text-red-600"
                    }
                  >
                    {hoveredNode.status}
                  </span>
                </div>
                <div>
                  <span className="font-medium">Partitions:</span>{" "}
                  {hoveredNode.partitions > 0 ? hoveredNode.partitions : "—"}
                  {hoveredNode.masterPartitions > 0 && (
                    <span> (M:{hoveredNode.masterPartitions} S:{hoveredNode.slavePartitions})</span>
                  )}
                </div>
                <div>
                  <span className="font-medium">Memory vs maximum_memory:</span>{" "}
                  {hoveredNode.engineMemPct == null ? "—" : `${hoveredNode.engineMemPct.toFixed(0)}%`}
                </div>
                {hoveredNode.memPct != null && (
                  <div>
                    <span className="font-medium">Host / overview memory:</span>{" "}
                    {`${hoveredNode.memPct.toFixed(0)}%`}
                  </div>
                )}
                <div>
                  <span className="font-medium">Disk:</span>{" "}
                  {hoveredNode.diskPct == null ? "—" : `${hoveredNode.diskPct.toFixed(0)}%`}
                </div>
                {hoveredNode.detail?.ip_addr && (
                  <div className="font-mono text-[10px] pt-1 border-t mt-1">
                    {hoveredNode.detail.ip_addr}:{hoveredNode.detail.port || ""}
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="absolute bottom-4 left-4 bg-black/70 backdrop-blur rounded-lg border border-white/10 p-3 text-xs text-white/90 shadow-lg max-w-[220px]">
            <div className="font-bold mb-2 text-white">Legend</div>
            <div className="space-y-1.5">
              {Object.entries(ROLE_COLORS)
                .filter(([k]) => k !== "unknown")
                .map(([role, color]) => (
                  <div key={role} className="flex items-center gap-2">
                    <div className="w-3.5 h-3.5 rounded-full" style={{ backgroundColor: color }} />
                    <span>{ROLE_LABELS[role]}</span>
                  </div>
                ))}
              <div className="pt-1 border-t border-white/10 space-y-1">
                <div className="flex items-center gap-2">
                  <svg width="18" height="8">
                    <line x1="0" y1="4" x2="18" y2="4" stroke={LAG_COLORS.healthy} strokeWidth="2" strokeDasharray="4 3" />
                  </svg>
                  <span>Healthy replication</span>
                </div>
                <div className="flex items-center gap-2">
                  <svg width="18" height="8">
                    <line x1="0" y1="4" x2="18" y2="4" stroke={LAG_COLORS.warning} strokeWidth="2.5" />
                  </svg>
                  <span>Lag warning</span>
                </div>
                <div className="flex items-center gap-2">
                  <svg width="18" height="8">
                    <line x1="0" y1="4" x2="18" y2="4" stroke={LAG_COLORS.critical} strokeWidth="3" />
                  </svg>
                  <span>Lag critical</span>
                </div>
                <div className="flex items-center gap-2">
                  <svg width="14" height="14">
                    <circle cx="7" cy="7" r="5" fill="none" stroke="#00d992" strokeWidth="2" strokeDasharray="12 20" />
                  </svg>
                  <span>Memory vs maximum_memory ring</span>
                </div>
                <div className="flex items-center gap-2">
                  <svg width="14" height="14">
                    <circle cx="7" cy="7" r="6" fill="none" stroke="#6B8CFF" strokeWidth="2" strokeDasharray="10 28" />
                  </svg>
                  <span>Disk ring</span>
                </div>
              </div>
            </div>
          </div>

          <div className="absolute top-4 right-4 text-[10px] text-white/50 bg-black/50 rounded px-2 py-1">
            Scroll to zoom · Click node for details
          </div>
        </div>

        {selectedNode && (
          <div className="border-t border-slate-200 dark:border-slate-800 p-4 bg-card">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h4 className="text-sm font-bold">{selectedNode.id}</h4>
                <p className="text-xs text-muted-foreground">
                  {ROLE_LABELS[selectedNode.role]} · {selectedNode.partitions > 0 ? `${selectedNode.partitions} partitions` : "partitions unknown"}
                  {selectedNode.availabilityGroup ? ` · AG ${selectedNode.availabilityGroup}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge
                  variant={
                    selectedNode.health === "critical"
                      ? "critical"
                      : selectedNode.health === "warning"
                      ? "warning"
                      : "info"
                  }
                >
                  {selectedNode.health}
                </Badge>
                <button
                  type="button"
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-xs"
                  onClick={() => setSelectedNode(null)}
                >
                  ✕ Close
                </button>
              </div>
            </div>
            {selectedNode.detail ? (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                <DetailItem
                  label="IP Address"
                  value={`${selectedNode.detail.ip_addr || "—"}:${selectedNode.detail.port || ""}`}
                  mono
                />
                <DetailItem label="Availability Group" value={selectedNode.detail.availability_group || "—"} mono />
                <DetailItem label="CPUs" value={String(selectedNode.detail.num_cpus || "—")} />
                <DetailItem
                  label="Version"
                  value={selectedNode.detail.version ? `v${selectedNode.detail.version}` : "—"}
                  mono
                />
                <DetailItem
                  label="Memory"
                  value={
                    selectedNode.detail.max_memory_mb
                      ? `${formatMegabytes(selectedNode.detail.memory_used_mb)} / ${formatMegabytes(selectedNode.detail.max_memory_mb)}`
                      : "—"
                  }
                  mono
                />
                <DetailItem
                  label="Disk"
                  value={
                    selectedNode.detail.total_disk_mb
                      ? `${formatMegabytes(selectedNode.detail.total_disk_mb - (selectedNode.detail.available_disk_mb || 0))} / ${formatMegabytes(selectedNode.detail.total_disk_mb)}`
                      : "—"
                  }
                  mono
                />
                <DetailItem label="Uptime" value={formatUptime(selectedNode.detail.uptime_seconds)} mono />
                <DetailItem label="State" value={selectedNode.detail.state || selectedNode.status} />
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No detailed metrics available for this node.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DetailItem({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className={cn("font-medium", mono && "font-mono text-[11px]")}>{value}</div>
    </div>
  );
}

import { useEffect, useRef, useMemo, useState } from "react";
import * as d3 from "d3";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { formatBytes, formatUptime } from "@/lib/utils-sdb";

/**
 * Interactive topology visualization for a SingleStore cluster.
 * D3 force-directed graph with zoom/pan, hover tooltips, and click-to-select.
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
  status: "online" | "offline" | "unknown";
  health: "healthy" | "warning" | "critical";
  detail?: NodeDetail;
}

interface ClusterEdge {
  source: string;
  target: string;
  type: "replication" | "partition";
}

interface SimNode extends ClusterNode, d3.SimulationNodeDatum {}
interface SimLink {
  source: SimNode | string;
  target: SimNode | string;
  type: "replication" | "partition";
}

interface ClusterTopologyMapProps {
  clusterLayout?: {
    by_host?: Record<string, { master: number; slave: number; total: number }>;
    total_partitions?: number;
  };
  clusterOverview?: {
    total_nodes?: number;
    online_nodes?: number;
    offline_nodes?: number;
    memory_used_pct?: number;
    disk_used_pct?: number;
    nodes_detail?: NodeDetail[];
  };
  nodeEvents?: Array<{
    node_id: string;
    event_type: string;
    severity?: string;
    description?: string;
    MasterHost?: string;
    SlaveHost?: string;
  }>;
  replicationStatus?: Array<{
    MasterHost?: string;
    SlaveHost?: string;
  }>;
}

const ROLE_COLORS: Record<string, string> = {
  master: "#FF6B6B",
  leaf: "#4ECDC4",
  aggregator: "#45B7D1",
  unknown: "#95A5A6",
};

const STATUS_COLORS: Record<string, string> = {
  healthy: "#00C853",
  warning: "#FF9800",
  critical: "#F44336",
  offline: "#9E9E9E",
};

const ROLE_LABELS: Record<string, string> = {
  master: "Master (MA)",
  leaf: "Leaf",
  aggregator: "Aggregator (CA)",
  unknown: "Unknown",
};

/** Match a node IP to cluster_layout / log_timeframe keys with suffix tolerance. */
function matchHost(keys: string[], ip: string | undefined): string | null {
  if (!ip) return null;
  return (
    keys.find((h) => h === ip) ||
    keys.find((h) => h.endsWith(`:${ip}`) || (ip && ip.endsWith(`:${h}`))) ||
    null
  );
}

function buildTopologyGraph(
  clusterLayout?: ClusterTopologyMapProps["clusterLayout"],
  clusterOverview?: ClusterTopologyMapProps["clusterOverview"],
  nodeEvents?: ClusterTopologyMapProps["nodeEvents"],
  replicationStatus?: ClusterTopologyMapProps["replicationStatus"]
): { nodes: ClusterNode[]; edges: ClusterEdge[] } {
  const nodes: ClusterNode[] = [];
  const edges: ClusterEdge[] = [];
  const nodeMap = new Map<string, ClusterNode>();

  // Build nodes from cluster layout
  if (clusterLayout?.by_host) {
    for (const [hostname, counts] of Object.entries(clusterLayout.by_host)) {
      const partitionsCount = counts.total || 0;
      let role: ClusterNode["role"] = "leaf";
      if (counts.master > 0) role = "master";

      const node: ClusterNode = {
        id: hostname,
        role,
        partitions: partitionsCount,
        status: "online",
        health: "healthy",
      };
      nodeMap.set(hostname, node);
      nodes.push(node);
    }
  }

  // Enrich with nodes_detail from cluster overview
  if (clusterOverview?.nodes_detail) {
    for (const nd of clusterOverview.nodes_detail) {
      const ip = nd.ip_addr || String(nd.id || "");
      // Match by IP or hostname suffix
      const matchKey = matchHost(Array.from(nodeMap.keys()), ip) || ip;
      let node = nodeMap.get(matchKey);
      if (!node && ip) {
        // Create a new node if we have detail but no layout entry
        const role: ClusterNode["role"] =
          (nd.type || "").toUpperCase() === "MA"
            ? "master"
            : (nd.type || "").toUpperCase() === "CA"
            ? "aggregator"
            : "leaf";
        node = {
          id: ip,
          role,
          partitions: 0,
          status: (nd.state || "").toLowerCase() === "online" ? "online" : "offline",
          health: "healthy",
        };
        nodeMap.set(ip, node);
        nodes.push(node);
      }
      if (node && nd) {
        node.detail = nd;
        // Update status from detail
        if (nd.state && nd.state.toLowerCase() !== "online") {
          node.status = "offline";
        }
        // Score health from resource usage
        if (nd.max_memory_mb && nd.max_memory_mb > 0) {
          const memPct = (nd.memory_used_mb || 0) / nd.max_memory_mb * 100;
          if (memPct > 90) node.health = "critical";
          else if (memPct > 80 && node.health !== "critical") node.health = "warning";
        }
        if (nd.total_disk_mb && nd.total_disk_mb > 0) {
          const diskPct = (nd.total_disk_mb - (nd.available_disk_mb || 0)) / nd.total_disk_mb * 100;
          if (diskPct > 90) node.health = "critical";
          else if (diskPct > 80 && node.health !== "critical") node.health = "warning";
        }
      }
    }
  }

  // Update node status/health based on events
  if (nodeEvents) {
    for (const event of nodeEvents) {
      const nodeId = event.node_id;
      if (!nodeId) continue;
      // Try exact match or suffix match
      const matchKey = matchHost(Array.from(nodeMap.keys()), nodeId) || nodeId;
      const node = nodeMap.get(matchKey);
      if (node) {
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
  }

  // Build edges from replication status
  if (replicationStatus) {
    for (const rep of replicationStatus) {
      const master = rep.MasterHost;
      const slave = rep.SlaveHost;
      if (master && slave) {
        edges.push({ source: master, target: slave, type: "replication" });
      }
    }
  }

  return { nodes, edges };
}

export default function ClusterTopologyMap({
  clusterLayout,
  clusterOverview,
  nodeEvents,
  replicationStatus,
}: ClusterTopologyMapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [hoveredNode, setHoveredNode] = useState<ClusterNode | null>(null);
  const [selectedNode, setSelectedNode] = useState<ClusterNode | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  const { nodes, edges } = useMemo(
    () => buildTopologyGraph(clusterLayout, clusterOverview, nodeEvents, replicationStatus),
    [clusterLayout, clusterOverview, nodeEvents, replicationStatus]
  );

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const width = svgRef.current.clientWidth || 800;
    const height = 500;

    const simulation = d3
      .forceSimulation<SimNode>(nodes as SimNode[])
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(edges as any)
          .id((d: any) => d.id)
          .distance(120)
          .strength(0.6)
      )
      .force("charge", d3.forceManyBody().strength(-600))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide<SimNode>().radius((d: any) => 24 + (d.partitions || 0) * 2));

    d3.select(svgRef.current).selectAll("*").remove();

    const svg = d3
      .select(svgRef.current)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", `0 0 ${width} ${height}`)
      .style("cursor", "grab");

    // Zoom/pan container
    const g = svg.append("g").attr("class", "topology-zoom");

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on("zoom", (event: any) => {
        g.attr("transform", event.transform);
        svg.style("cursor", event.transform.k > 1 ? "zoom-in" : "grab");
      });

    svg.call(zoom as any);

    // Links
    const link = g
      .selectAll<SVGLineElement, SimLink>("line")
      .data(edges as any)
      .join("line")
      .attr("stroke", "#999")
      .attr("stroke-opacity", 0.4)
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", (d: any) => (d.type === "replication" ? "5,5" : "0"));

    // Node groups
    const nodeG = g
      .selectAll<SVGGElement, SimNode>("g.node-group")
      .data(nodes as any)
      .join("g")
      .attr("class", "node-group")
      .style("cursor", "pointer")
      .call(
        d3
          .drag<SVGGElement, SimNode>()
          .on("start", dragstarted)
          .on("drag", dragged)
          .on("end", dragended) as any
      );

    // Circles
    nodeG
      .append("circle")
      .attr("r", (d: any) => 20 + Math.min(d.partitions || 0, 20) * 1.5)
      .attr("fill", (d: any) => {
        if (d.status === "offline") return STATUS_COLORS.offline;
        return ROLE_COLORS[d.role] || ROLE_COLORS.unknown;
      })
      .attr("stroke", (d: any) => {
        if (d.id === selectedNode?.id) return "#000";
        if (d.health === "critical") return STATUS_COLORS.critical;
        if (d.health === "warning") return STATUS_COLORS.warning;
        return "transparent";
      })
      .attr("stroke-width", (d: any) =>
        d.id === selectedNode?.id ? 3 : d.health !== "healthy" ? 2.5 : 0
      )
      .attr("opacity", (d: any) => (d.status === "offline" ? 0.5 : 1));

    // Role badge text inside node
    nodeG
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.3em")
      .attr("font-size", 9)
      .attr("font-weight", "bold")
      .attr("fill", "#fff")
      .attr("pointer-events", "none")
      .text((d: any) => {
        if (d.role === "master") return "MA";
        if (d.role === "aggregator") return "CA";
        return "L";
      });

    // Hostname label below node
    nodeG
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", (d: any) => 20 + Math.min(d.partitions || 0, 20) * 1.5 + 14)
      .attr("font-size", 9)
      .attr("fill", "currentColor")
      .attr("class", "text-slate-600 dark:text-slate-400")
      .attr("pointer-events", "none")
      .text((d: any) => {
        const shortId = d.id.split(".")[0] || d.id;
        return shortId.length > 15 ? shortId.slice(0, 13) + "…" : shortId;
      });

    // Interaction handlers
    nodeG
      .on("mouseenter", (event: any, d: any) => {
        setHoveredNode(d);
        setTooltipPos({ x: event.pageX, y: event.pageY });
        // Highlight
        d3.select(event.currentTarget)
          .select("circle")
          .transition()
          .duration(150)
          .attr("stroke-width", 3)
          .attr("stroke", "#000");
      })
      .on("mousemove", (event: any) => {
        setTooltipPos({ x: event.pageX, y: event.pageY });
      })
      .on("mouseleave", (event: any, d: any) => {
        setHoveredNode(null);
        // Restore
        d3.select(event.currentTarget)
          .select("circle")
          .transition()
          .duration(150)
          .attr("stroke-width", () => {
            if (d.id === selectedNode?.id) return 3;
            if (d.health === "critical" || d.health === "warning") return 2.5;
            return 0;
          })
          .attr("stroke", () => {
            if (d.id === selectedNode?.id) return "#000";
            if (d.health === "critical") return STATUS_COLORS.critical;
            if (d.health === "warning") return STATUS_COLORS.warning;
            return "transparent";
          });
      })
      .on("click", (_event: any, d: any) => {
        setSelectedNode((prev) => (prev?.id === d.id ? null : d));
      });

    // Simulation tick
    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x || 0)
        .attr("y1", (d: any) => d.source.y || 0)
        .attr("x2", (d: any) => d.target.x || 0)
        .attr("y2", (d: any) => d.target.y || 0);

      nodeG.attr("transform", (d: any) => `translate(${d.x || 0},${d.y || 0})`);
    });

    function dragstarted(event: any, d: any) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }
    function dragged(event: any, d: any) {
      d.fx = event.x;
      d.fy = event.y;
    }
    function dragended(event: any, d: any) {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }

    return () => {
      simulation.stop();
    };
  }, [nodes, edges, selectedNode]);

  // Empty state
  if (nodes.length === 0) {
    return (
      <Card className="shadow-sm">
        <CardHeader>
          <CardTitle>Cluster Topology</CardTitle>
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

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <div className="flex items-start justify-between flex-wrap gap-2">
          <div>
            <CardTitle>Cluster Topology</CardTitle>
            <CardDescription>
              {nodes.length} nodes · {onlineCount} online{offlineCount > 0 ? ` · ${offlineCount} offline` : ""} ·{" "}
              {clusterLayout?.total_partitions || 0} partitions
            </CardDescription>
          </div>
          <div className="flex gap-2 flex-wrap">
            {criticalCount > 0 && <Badge variant="critical">{criticalCount} critical</Badge>}
            {warningCount > 0 && <Badge variant="warning">{warningCount} warning</Badge>}
            {offlineCount > 0 && <Badge variant="destructive">{offlineCount} offline</Badge>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="relative bg-slate-50 dark:bg-slate-900 rounded-b-lg overflow-hidden">
          <svg ref={svgRef} className="w-full" style={{ height: "500px" }} />

          {/* Hover tooltip */}
          {hoveredNode && (
            <div
              ref={tooltipRef}
              className="fixed z-50 pointer-events-none bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg shadow-xl p-3 text-xs max-w-xs"
              style={{
                left: tooltipPos.x + 14,
                top: tooltipPos.y + 14,
              }}
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
                        ? "text-green-600 dark:text-green-400"
                        : "text-red-600 dark:text-red-400"
                    }
                  >
                    {hoveredNode.status}
                  </span>
                </div>
                <div>
                  <span className="font-medium">Partitions:</span> {hoveredNode.partitions}
                </div>
                <div>
                  <span className="font-medium">Health:</span>{" "}
                  <span
                    className={
                      hoveredNode.health === "critical"
                        ? "text-red-600 dark:text-red-400"
                        : hoveredNode.health === "warning"
                        ? "text-amber-600 dark:text-amber-400"
                        : "text-green-600 dark:text-green-400"
                    }
                  >
                    {hoveredNode.health}
                  </span>
                </div>
                {hoveredNode.detail?.ip_addr && (
                  <div className="font-mono text-[10px] pt-1 border-t border-slate-200 dark:border-slate-800 mt-1">
                    {hoveredNode.detail.ip_addr}:{hoveredNode.detail.port || ""}
                  </div>
                )}
                {hoveredNode.detail?.max_memory_mb != null && hoveredNode.detail.max_memory_mb > 0 && (
                  <div className="font-mono text-[10px]">
                    MEM: {formatBytes(hoveredNode.detail.memory_used_mb)} /{" "}
                    {formatBytes(hoveredNode.detail.max_memory_mb)}
                  </div>
                )}
                {hoveredNode.detail?.total_disk_mb != null && hoveredNode.detail.total_disk_mb > 0 && (
                  <div className="font-mono text-[10px]">
                    DISK:{" "}
                    {formatBytes(
                      hoveredNode.detail.total_disk_mb - (hoveredNode.detail.available_disk_mb || 0)
                    )}{" "}
                    / {formatBytes(hoveredNode.detail.total_disk_mb)}
                  </div>
                )}
                {hoveredNode.detail?.uptime_seconds != null &&
                  hoveredNode.detail.uptime_seconds > 0 && (
                    <div className="font-mono text-[10px]">
                      Uptime: {formatUptime(hoveredNode.detail.uptime_seconds)}
                    </div>
                  )}
                {hoveredNode.detail?.version && (
                  <div className="font-mono text-[10px]">v{hoveredNode.detail.version}</div>
                )}
              </div>
            </div>
          )}

          {/* Legend */}
          <div className="absolute bottom-4 left-4 bg-white dark:bg-slate-950 rounded-lg border border-slate-200 dark:border-slate-800 p-3 text-xs shadow-lg">
            <div className="font-bold mb-2">Legend</div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded-full" style={{ backgroundColor: ROLE_COLORS.master }} />
                <span>Master (MA)</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded-full" style={{ backgroundColor: ROLE_COLORS.leaf }} />
                <span>Leaf</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded-full" style={{ backgroundColor: ROLE_COLORS.aggregator }} />
                <span>Aggregator (CA)</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded-full opacity-50" style={{ backgroundColor: STATUS_COLORS.offline }} />
                <span>Offline</span>
              </div>
              <div className="flex items-center gap-2 pt-1 border-t border-slate-200 dark:border-slate-800 mt-1">
                <svg width="20" height="3">
                  <line
                    x1="0"
                    y1="1.5"
                    x2="20"
                    y2="1.5"
                    stroke="#999"
                    strokeWidth="1.5"
                    strokeDasharray="5,5"
                  />
                </svg>
                <span>Replication</span>
              </div>
            </div>
          </div>

          {/* Zoom hint */}
          <div className="absolute top-4 right-4 text-[10px] text-slate-400 dark:text-slate-500 bg-white/80 dark:bg-slate-950/80 rounded px-2 py-1">
            Scroll to zoom · Drag nodes to rearrange · Click for details
          </div>
        </div>

        {/* Selected node details panel */}
        {selectedNode && (
          <div className="border-t border-slate-200 dark:border-slate-800 p-4 bg-white dark:bg-slate-950">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h4 className="text-sm font-bold">{selectedNode.id}</h4>
                <p className="text-xs text-muted-foreground">
                  {ROLE_LABELS[selectedNode.role]} · {selectedNode.partitions} partitions
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
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-xs"
                  onClick={() => setSelectedNode(null)}
                >
                  ✕ Close
                </button>
              </div>
            </div>
            {selectedNode.detail && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                <DetailItem label="IP Address" value={`${selectedNode.detail.ip_addr || "—"}:${selectedNode.detail.port || ""}`} mono />
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
                      ? `${formatBytes(selectedNode.detail.memory_used_mb)} / ${formatBytes(selectedNode.detail.max_memory_mb)}`
                      : "—"
                  }
                  mono
                />
                <DetailItem
                  label="Disk"
                  value={
                    selectedNode.detail.total_disk_mb
                      ? `${formatBytes(selectedNode.detail.total_disk_mb - (selectedNode.detail.available_disk_mb || 0))} / ${formatBytes(selectedNode.detail.total_disk_mb)}`
                      : "—"
                  }
                  mono
                />
                <DetailItem
                  label="Uptime"
                  value={formatUptime(selectedNode.detail.uptime_seconds)}
                  mono
                />
                <DetailItem label="State" value={selectedNode.detail.state || selectedNode.status} />
              </div>
            )}
            {!selectedNode.detail && (
              <p className="text-xs text-muted-foreground">No detailed metrics available for this node.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DetailItem({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</div>
      <div className={cn("font-medium", mono && "font-mono text-[11px]")}>{value}</div>
    </div>
  );
}
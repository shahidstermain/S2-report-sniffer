import React, { useEffect, useRef, useMemo, useState } from "react";
import * as d3 from "d3";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Topology visualization for a SingleStore cluster using D3 force layout.
 * Shows nodes (master/leaf/aggregator), partitions, and replica relationships.
 */

interface ClusterNode {
  id: string; // hostname
  role: "master" | "leaf" | "aggregator" | "unknown";
  partitions: number;
  status: "online" | "offline" | "unknown";
  health: "healthy" | "warning" | "critical";
  details?: {
    memory_used_pct?: number;
    disk_used_pct?: number;
    uptime_sec?: number;
  };
}

interface ClusterEdge {
  source: string;
  target: string;
  type: "replication" | "partition"; // replication edge or shared partition
}

interface SimulationNode extends ClusterNode, d3.SimulationNodeDatum {
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface SimulationLink extends ClusterEdge {
  source: SimulationNode;
  target: SimulationNode;
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
  };
  nodeEvents?: Array<{
    node_id: string;
    event_type: string;
    severity?: string;
  }>;
  replicationStatus?: Array<{
    MasterHost?: string;
    SlaveHost?: string;
  }>;
}

const ROLE_COLORS = {
  master: "#FF6B6B", // red
  leaf: "#4ECDC4", // teal
  aggregator: "#45B7D1", // blue
  unknown: "#95A5A6", // gray
};

const STATUS_COLORS = {
  healthy: "#00C853",
  warning: "#FF9800",
  critical: "#F44336",
  offline: "#9E9E9E",
};

const buildTopologyGraph = (
  clusterLayout?: ClusterTopologyMapProps["clusterLayout"],
  nodeEvents?: ClusterTopologyMapProps["nodeEvents"],
  replicationStatus?: ClusterTopologyMapProps["replicationStatus"]
): { nodes: ClusterNode[]; edges: ClusterEdge[] } => {
  const nodes: ClusterNode[] = [];
  const edges: ClusterEdge[] = [];
  const nodeMap = new Map<string, ClusterNode>();

  // Build nodes from cluster layout
  if (clusterLayout?.by_host) {
    for (const [hostname, counts] of Object.entries(clusterLayout.by_host)) {
      const partitionsCount = (counts.total || 0);
      let role: ClusterNode["role"] = "leaf";
      if (counts.master > 0) role = "master";
      else if (counts.master === 0 && counts.slave > 0) role = "leaf";

      const node: ClusterNode = {
        id: hostname,
        role,
        partitions: partitionsCount,
        status: "online", // default; may be overridden by nodeEvents
        health: "healthy", // default; will be scored later
      };

      nodeMap.set(hostname, node);
      nodes.push(node);
    }
  }

  // Update node status based on events
  if (nodeEvents) {
    for (const event of nodeEvents) {
      const nodeId = event.node_id || event.MasterHost || event.SlaveHost;
      if (!nodeId) continue;

      const node = nodeMap.get(nodeId);
      if (node) {
        if (event.event_type?.toLowerCase().includes("offline")) {
          node.status = "offline";
        }
        if (event.severity === "CRITICAL" || event.severity === "critical") {
          node.health = "critical";
        } else if (event.severity === "WARNING" || event.severity === "warning") {
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
        edges.push({
          source: master,
          target: slave,
          type: "replication",
        });
      }
    }
  }

  return { nodes, edges };
};

export default function ClusterTopologyMap({
  clusterLayout,
  clusterOverview,
  nodeEvents,
  replicationStatus,
}: ClusterTopologyMapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const { nodes, edges } = useMemo(() => buildTopologyGraph(clusterLayout, nodeEvents, replicationStatus), [
    clusterLayout,
    nodeEvents,
    replicationStatus,
  ]);

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const width = svgRef.current.clientWidth || 800;
    const height = 500;

    // D3 simulation
    const simulation = d3
      .forceSimulation<SimulationNode>(nodes as SimulationNode[])
      .force("link", d3.forceLink<SimulationNode, SimulationLink>(edges as any)
        .id((d: any) => d.id)
        .distance(100)
        .strength(0.5)
      )
      .force("charge", d3.forceManyBody().strength(-500))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide(40));

    // Clear previous render
    d3.select(svgRef.current).selectAll("*").remove();

    const svg = d3
      .select(svgRef.current)
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", `0 0 ${width} ${height}`);

    // Draw links
    const link = svg
      .selectAll<SVGLineElement, SimulationLink>("line")
      .data(edges as any)
      .join("line")
      .attr("stroke", "#999")
      .attr("stroke-opacity", 0.4)
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", (d: any) => (d.type === "replication" ? "5,5" : "0"));

    // Draw nodes
    const node = svg
      .selectAll<SVGCircleElement, SimulationNode>("circle")
      .data(nodes as any)
      .join("circle")
      .attr("r", (d: any) => 20 + (d.partitions || 0) * 2)
      .attr("fill", (d: any) => {
        if (d.status === "offline") return STATUS_COLORS.offline;
        return ROLE_COLORS[d.role] || ROLE_COLORS.unknown;
      })
      .attr("stroke", (d: any) => {
        if (d.id === hoveredNode) return "#000";
        if (d.health === "critical") return STATUS_COLORS.critical;
        if (d.health === "warning") return STATUS_COLORS.warning;
        return "transparent";
      })
      .attr("stroke-width", (d: any) => (d.id === hoveredNode ? 2 : d.health !== "healthy" ? 2 : 0))
      .on("mouseenter", (_, d: any) => setHoveredNode(d.id))
      .on("mouseleave", () => setHoveredNode(null))
      .call(d3.drag<SVGCircleElement, SimulationNode>()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended)
      );

    // Labels
    const labels = svg
      .selectAll<SVGTextElement, SimulationNode>("text")
      .data(nodes as any)
      .join("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.3em")
      .attr("font-size", 10)
      .attr("fill", "#000")
      .attr("pointer-events", "none")
      .text((d: any) => d.id.split(".")[0] || d.id); // short hostname

    // Tooltip group (invisible, for potential future use)
    node.append("title").text((d: any) => 
      `${d.id}\n${d.role} (${d.partitions} partitions)\nStatus: ${d.status}`
    );

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x || 0)
        .attr("y1", (d: any) => d.source.y || 0)
        .attr("x2", (d: any) => d.target.x || 0)
        .attr("y2", (d: any) => d.target.y || 0);

      node.attr("cx", (d: any) => d.x || 0).attr("cy", (d: any) => d.y || 0);

      labels.attr("x", (d: any) => d.x || 0).attr("y", (d: any) => d.y || 0);
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
  }, [nodes, edges, hoveredNode]);

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

  const onlineCount = nodes.filter(n => n.status === "online").length;
  const criticalCount = nodes.filter(n => n.health === "critical").length;
  const warningCount = nodes.filter(n => n.health === "warning").length;

  return (
    <Card className="shadow-sm">
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle>Cluster Topology</CardTitle>
            <CardDescription>
              {nodes.length} nodes · {onlineCount} online · {clusterLayout?.total_partitions || 0} partitions
            </CardDescription>
          </div>
          <div className="flex gap-2">
            {criticalCount > 0 && <Badge variant="critical">{criticalCount} critical</Badge>}
            {warningCount > 0 && <Badge variant="warning">{warningCount} warning</Badge>}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="relative bg-slate-50 dark:bg-slate-900 rounded-b-lg overflow-hidden">
          <svg ref={svgRef} className="w-full" style={{ height: "500px" }} />

          {/* Legend */}
          <div className="absolute bottom-4 left-4 bg-white dark:bg-slate-950 rounded-lg border border-slate-200 dark:border-slate-800 p-3 text-xs shadow-lg">
            <div className="font-bold mb-2">Legend</div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded-full" style={{ backgroundColor: ROLE_COLORS.master }} />
                <span>Master</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded-full" style={{ backgroundColor: ROLE_COLORS.leaf }} />
                <span>Leaf</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-4 rounded-full" style={{ backgroundColor: ROLE_COLORS.aggregator }} />
                <span>Aggregator</span>
              </div>
              <div className="flex items-center gap-2 pt-1 border-t border-slate-200 dark:border-slate-800 mt-1">
                <div className="w-3 h-px bg-slate-400" style={{ borderTop: "3px dashed #999" }} />
                <span>Replication</span>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

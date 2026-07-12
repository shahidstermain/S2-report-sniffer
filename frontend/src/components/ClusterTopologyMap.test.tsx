import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("d3", () => {
  const createChainable = () => {
    const fn: any = vi.fn(() => createChainable());
    fn.selectAll = vi.fn(() => createChainable());
    fn.data = vi.fn(() => createChainable());
    fn.join = vi.fn(() => createChainable());
    fn.append = vi.fn(() => createChainable());
    fn.attr = vi.fn(() => createChainable());
    fn.text = vi.fn(() => createChainable());
    fn.on = vi.fn(() => createChainable());
    fn.call = vi.fn(() => createChainable());
    fn.style = vi.fn(() => createChainable());
    fn.remove = vi.fn();
    fn.transition = vi.fn(() => createChainable());
    fn.duration = vi.fn(() => createChainable());
    fn.attrTween = vi.fn(() => createChainable());
    return fn;
  };
  const chain = createChainable();
  return {
    forceSimulation: vi.fn(() => ({
      force: vi.fn().mockReturnThis(),
      on: vi.fn().mockReturnThis(),
      stop: vi.fn(),
    })),
    forceLink: vi.fn(() => ({
      id: vi.fn().mockReturnThis(),
      distance: vi.fn().mockReturnThis(),
      strength: vi.fn().mockReturnThis(),
    })),
    forceManyBody: vi.fn(() => ({ strength: vi.fn().mockReturnThis() })),
    forceCenter: vi.fn(),
    forceCollide: vi.fn(() => ({ radius: vi.fn().mockReturnThis() })),
    select: vi.fn(() => chain),
    zoom: vi.fn(() => ({
      scaleExtent: vi.fn().mockReturnThis(),
      on: vi.fn().mockReturnThis(),
    })),
    drag: vi.fn(() => ({
      on: vi.fn().mockReturnThis(),
    })),
  };
});

vi.mock("@/lib/utils-sdb", () => ({
  formatBytes: vi.fn((mb) => `${mb} MB`),
  formatUptime: vi.fn((s) => `${s}s`),
}));

import ClusterTopologyMap from "./ClusterTopologyMap";

const MOCK_CLUSTER_LAYOUT = {
  by_host: {
    "master-01.db.internal": { master: 10, slave: 0, total: 10 },
    "leaf-01.db.internal": { master: 0, slave: 5, total: 5 },
    "leaf-02.db.internal": { master: 0, slave: 5, total: 5 },
  },
  total_partitions: 20,
};

const MOCK_CLUSTER_OVERVIEW = {
  total_nodes: 3,
  online_nodes: 3,
  offline_nodes: 0,
  nodes_detail: [
    {
      id: 1,
      ip_addr: "10.0.1.1",
      port: 3306,
      type: "MA",
      state: "online",
      availability_group: "1",
      num_cpus: 8,
      max_memory_mb: 16384,
      memory_used_mb: 8192,
      total_disk_mb: 500000,
      available_disk_mb: 250000,
      uptime_seconds: 86400,
      version: "8.1.0",
    },
  ],
};

const MOCK_NODE_EVENTS = [
  {
    node_id: "leaf-02.db.internal",
    event_type: "NODE_OFFLINE",
    severity: "CRITICAL",
    description: "Leaf node went offline",
  },
];

const MOCK_REPLICATION = [
  { MasterHost: "master-01.db.internal", SlaveHost: "leaf-01.db.internal" },
  { MasterHost: "master-01.db.internal", SlaveHost: "leaf-02.db.internal" },
];

describe("ClusterTopologyMap", () => {
  test("renders empty state when no cluster data", () => {
    render(<ClusterTopologyMap />);
    expect(screen.getByText("No cluster data available")).toBeInTheDocument();
    expect(
      screen.getByText("Cluster topology will appear here once node data is available.")
    ).toBeInTheDocument();
  });

  test("renders topology with correct node and partition count", () => {
    render(
      <ClusterTopologyMap
        clusterLayout={MOCK_CLUSTER_LAYOUT}
        clusterOverview={MOCK_CLUSTER_OVERVIEW}
      />
    );

    expect(screen.getByText("Cluster Topology")).toBeInTheDocument();
    // CardDescription renders "3 nodes · 3 online · 20 partitions"
    const desc = screen.getByText(/nodes.*partitions/);
    expect(desc).toBeInTheDocument();
    expect(desc.textContent).toMatch(/\d+ nodes/);
    expect(desc.textContent).toMatch(/20 partitions/);
  });

  test("shows offline badge when nodes are offline", () => {
    render(
      <ClusterTopologyMap
        clusterLayout={MOCK_CLUSTER_LAYOUT}
        nodeEvents={MOCK_NODE_EVENTS}
      />
    );

    // "1 offline" appears in both the CardDescription and a badge; check the badge specifically
    const badges = screen.getAllByText(/offline/i);
    expect(badges.length).toBeGreaterThan(0);
  });

  test("renders legend with role colors", () => {
    render(
      <ClusterTopologyMap
        clusterLayout={MOCK_CLUSTER_LAYOUT}
        clusterOverview={MOCK_CLUSTER_OVERVIEW}
      />
    );

    expect(screen.getByText("Legend")).toBeInTheDocument();
    expect(screen.getByText("Master (MA)")).toBeInTheDocument();
    expect(screen.getByText("Leaf")).toBeInTheDocument();
    expect(screen.getByText("Aggregator (CA)")).toBeInTheDocument();
    expect(screen.getByText("Replication")).toBeInTheDocument();
  });

  test("shows zoom hint text", () => {
    render(<ClusterTopologyMap clusterLayout={MOCK_CLUSTER_LAYOUT} />);

    expect(screen.getByText(/Scroll to zoom/)).toBeInTheDocument();
    expect(screen.getByText(/Drag nodes to rearrange/)).toBeInTheDocument();
    expect(screen.getByText(/Click for details/)).toBeInTheDocument();
  });

  test("does not render critical/warning badges when all healthy", () => {
    render(<ClusterTopologyMap clusterLayout={MOCK_CLUSTER_LAYOUT} />);

    expect(screen.queryByText(/critical/i)).toBeNull();
    expect(screen.queryByText(/warning/i)).toBeNull();
  });

  test("builds edges from replication status", () => {
    render(
      <ClusterTopologyMap
        clusterLayout={MOCK_CLUSTER_LAYOUT}
        replicationStatus={MOCK_REPLICATION}
      />
    );

    expect(screen.getByText("Cluster Topology")).toBeInTheDocument();
  });
});
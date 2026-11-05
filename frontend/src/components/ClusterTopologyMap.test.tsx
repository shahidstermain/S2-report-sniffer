import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("d3", () => {
  const createChainable = () => {
    const fn: any = vi.fn(() => createChainable());
    fn.select = vi.fn(() => createChainable());
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
    fn.empty = vi.fn(() => false);
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

import ClusterTopologyMap, { buildTopologyGraph } from "./ClusterTopologyMap";

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
    // CardDescription renders "3 nodes · 3 online · 20 partition copies"
    const desc = screen.getByText(/nodes.*partition copies/);
    expect(desc).toBeInTheDocument();
    expect(desc.textContent).toMatch(/\d+ nodes/);
    expect(desc.textContent).toMatch(/20 partition copies/);
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
    expect(screen.getByText("Master Aggregator (MA)")).toBeInTheDocument();
    expect(screen.getByText("Leaf")).toBeInTheDocument();
    expect(screen.getByText("Child Aggregator (CA)")).toBeInTheDocument();
    expect(screen.getByText("Healthy replication")).toBeInTheDocument();
  });

  test("shows zoom hint text", () => {
    render(<ClusterTopologyMap clusterLayout={MOCK_CLUSTER_LAYOUT} />);

    expect(screen.getByText(/Scroll to zoom/)).toBeInTheDocument();
    expect(screen.getByText(/Click node for details/)).toBeInTheDocument();
  });

  test("does not render critical/warning badges when all healthy", () => {
    render(<ClusterTopologyMap clusterLayout={MOCK_CLUSTER_LAYOUT} />);

    expect(screen.queryByText(/^\d+ critical$/i)).toBeNull();
    expect(screen.queryByText(/^\d+ warning$/i)).toBeNull();
  });

  test("shows replication state when lag patterns provided", () => {
    render(
      <ClusterTopologyMap
        clusterLayout={MOCK_CLUSTER_LAYOUT}
        replicationLagPatterns={{
          replication_state: "degraded",
          lagging_count: 2,
          max_lag_sec: 12.5,
          lagging_pairs: [
            { master: "master-01.db.internal", slave: "leaf-01.db.internal", lag_sec: 12.5, severity: "warning" },
          ],
        }}
      />
    );

    expect(screen.getByText(/Replication degraded/i)).toBeInTheDocument();
  });

  test("accepts legacy nodes_detail {rows: [...]} wrappers without throwing", () => {
    const wrappedOverview = {
      ...MOCK_CLUSTER_OVERVIEW,
      nodes_detail: { rows: MOCK_CLUSTER_OVERVIEW.nodes_detail },
    };

    expect(() =>
      buildTopologyGraph(MOCK_CLUSTER_LAYOUT, wrappedOverview as any)
    ).not.toThrow();

    const { nodes } = buildTopologyGraph(MOCK_CLUSTER_LAYOUT, wrappedOverview as any);
    expect(nodes.some((n) => n.detail?.type === "MA")).toBe(true);

    render(
      <ClusterTopologyMap
        clusterLayout={MOCK_CLUSTER_LAYOUT}
        clusterOverview={wrappedOverview as any}
      />
    );
    expect(screen.getByText("Cluster Topology")).toBeInTheDocument();
  });

  test("applies per-node engine memory utilization from backend map shape", () => {
    const { nodes } = buildTopologyGraph(
      MOCK_CLUSTER_LAYOUT,
      undefined,
      undefined,
      undefined,
      undefined,
      {
        per_node: {
          "leaf-01.db.internal": {
            engine_used_pct: 91,
            status: "critical",
          },
        },
      }
    );

    expect(nodes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "leaf-01.db.internal",
          engineMemPct: 91,
          health: "critical",
        }),
      ])
    );
  });

  test("keeps leaf role when hostname has master partitions but no detail type", () => {
    const { nodes } = buildTopologyGraph(
      {
        by_host: {
          "leaf-with-masters.db.internal": { master: 8, slave: 2, total: 10 },
        },
        total_partitions: 10,
      },
      undefined
    );

    expect(nodes).toEqual([
      expect.objectContaining({
        id: "leaf-with-masters.db.internal",
        role: "leaf",
        masterPartitions: 8,
        slavePartitions: 2,
      }),
    ]);
  });
});

test("draws the MA from collector inventory when the catalog omits it", () => {
  render(<ClusterTopologyMap clusterOverview={{ nodes_detail: [
    { ip_addr: "leaf", type: "LEAF", state: "online" },
  ] }} nodeInventory={[{ hostname: "quiet-ma", role: "Master Aggregator" }]} />);
  expect(screen.getByText("MA")).toBeInTheDocument();
  expect(screen.getByText("quiet-ma")).toBeInTheDocument();
});

test("keeps colocated MA and leaf endpoints separate in either snapshot order", () => {
  const rows = [
    { id: 1, ip_addr: "shared", port: 3306, type: "AGGREGATOR" },
    { id: 2, ip_addr: "shared", port: 3307, type: "LEAF" },
  ];
  for (const details of [rows, [...rows].reverse()]) {
    const { nodes } = buildTopologyGraph(
      { by_host: { shared: { master: 5, replica: 2, total: 7 } } },
      { nodes_detail: details, topology: { aggregators: [
        { NodeId: 1, Host: "shared", Port: 3306, Master_Aggregator: "1" },
      ] } }, undefined, undefined, undefined, undefined, [{ hostname: "shared", role: "MA" }],
    );
    expect(nodes).toHaveLength(2);
    expect(nodes).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "shared:3306", role: "master", partitions: 0 }),
      expect.objectContaining({ id: "shared:3307", role: "leaf", partitions: 7 }),
    ]));
  }
});

test("leaves the master tier empty when there is no evidence for an MA", () => {
  const { nodes } = buildTopologyGraph(undefined, { topology: { aggregators: [
    { Host: "ca-1", Master_Aggregator: "0" },
  ] } });
  expect(nodes.map((n) => n.role)).toEqual(["aggregator"]);
});

describe("complete partition inventories", () => {
  const overview = { nodes_detail: [
    { id: 1, ip_addr: "shared", port: 3306, type: "MA", state: "online" },
    { id: 2, ip_addr: "shared", port: 3307, type: "LEAF", state: "online" },
    { id: 3, ip_addr: "shared", port: 3308, type: "LEAF", state: "online" },
  ] };
  const layout = {
    summary_version: 2, available: true, classification_complete: true,
    total_partitions: 6002, reference_rows: 3,
    by_role: { master: 3001, replica: 3001 },
    by_host: { shared: { master: 3001, replica: 3001, total: 6002 } },
    by_node: [
      { host: "shared", port: "3307", master: 3001, replica: 0, total: 3001 },
      { host: "shared", port: "3308", master: 0, replica: 3001, total: 3001 },
    ],
  };
  test("assigns exact endpoint counts and zero data copies to the MA", () => {
    const graph = buildTopologyGraph(layout, overview);
    expect(graph.nodes).toHaveLength(3);
    expect(graph.nodes.map(n => [n.id, n.partitions, n.partitionsKnown])).toEqual([
      ["shared:3306", 0, true], ["shared:3307", 3001, true], ["shared:3308", 3001, true],
    ]);
    expect(graph.nodes.filter(n => n.role === "master")).toHaveLength(1);
  });
  test("shows reference exclusions and uses only leaf counts for skew", () => {
    render(<ClusterTopologyMap clusterOverview={overview} clusterLayout={layout} />);
    expect(screen.getByText(/6,002 partition copies/)).toBeInTheDocument();
    expect(screen.getByTestId("reference-records-note")).toHaveTextContent("3 reference database records excluded");
    expect(screen.getByText(/skew 1.0x/)).toBeInTheDocument();
  });
  test("does not show skew or measured zeroes for incomplete saved counts", () => {
    const partial = { ...layout, counts_are_lower_bounds: true, by_node: [layout.by_node[0]] };
    const graph = buildTopologyGraph(partial, overview);
    expect(graph.nodes.find(n => n.id === "shared:3308")?.partitionsKnown).toBe(false);
    render(<ClusterTopologyMap clusterOverview={overview} clusterLayout={partial} />);
    expect(screen.getByTestId("partition-coverage-note")).toBeInTheDocument();
    expect(screen.queryByText(/skew .*x/)).not.toBeInTheDocument();
  });
  test("does not assign ambiguous host-only counts to multiple leaves", () => {
    const graph = buildTopologyGraph({ by_host: layout.by_host }, overview);
    expect(graph.nodes.filter(n => n.role === "leaf").every(n => !n.partitionsKnown)).toBe(true);
  });
  test("supports documented NodeID and leader roles in topology fallback", () => {
    const graph = buildTopologyGraph(undefined, { topology: {
      aggregators: [{ Host: "ma", Port: 3306, NodeID: 9, Role: "leader", State: "online" }],
      leaves: [{ Host: "leaf", Port: 3307, NodeID: 10, State: "online" }],
    } });
    expect(graph.nodes.find(n => n.role === "master")?.detail?.id).toBe(9);
  });
});

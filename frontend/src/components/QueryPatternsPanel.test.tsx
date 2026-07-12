import { describe, test, expect } from "vitest";
import { render } from "@testing-library/react";
import QueryPatternsPanel from "./QueryPatternsPanel";

const mockQueryEntry = {
  elapsed_sec: 42.5,
  query_text: "SELECT * FROM large_table WHERE id = 1",
  user: "app_user",
  database: "prod_db",
  memory_used_mb: 128,
  node_id: "node-1",
};

const mockRepeated = {
  normalized_sql: "SELECT * FROM large_table WHERE id = ?",
  count: 15,
  max_elapsed_sec: 38.2,
  sample_query: "SELECT * FROM large_table WHERE id = 1",
};

const mockQueryPatterns = {
  slow_queries: [mockQueryEntry],
  runaway_queries: [mockQueryEntry],
  top_by_memory: [mockQueryEntry],
  repeated_patterns: [mockRepeated],
  slow_count: 1,
  runaway_count: 1,
  max_elapsed_sec: 42.5,
  total_memory_used_mb: 128,
};

describe("QueryPatternsPanel", () => {
  test("renders without crashing with valid data", () => {
    const { container } = render(
      <QueryPatternsPanel queryPatterns={mockQueryPatterns} />
    );
    expect(container.firstChild).not.toBeNull();
  });

  test("renders null when queryPatterns is undefined", () => {
    const { container } = render(<QueryPatternsPanel />);
    expect(container.firstChild).toBeNull();
  });

  test("renders null when pattern arrays are empty", () => {
    const { container } = render(
      <QueryPatternsPanel
        queryPatterns={{
          slow_queries: [],
          runaway_queries: [],
          top_by_memory: [],
          repeated_patterns: [],
          slow_count: 0,
          runaway_count: 0,
          max_elapsed_sec: 0,
          total_memory_used_mb: 0,
        }}
      />
    );
    expect(container.firstChild).toBeNull();
  });
});
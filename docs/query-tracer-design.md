# Query Tracer — Feature Design

**Status:** Phase 0 MVP implemented  
**Last reviewed:** 2026-07-17  
**Terminology:** Follow [`TERMINOLOGY.md`](TERMINOLOGY.md). Stable internal fields such as `runaway_queries` and `runaway_patterns` remain compatibility fields and must not appear as “Runaway Queries” in user-facing copy.

## 1. Purpose

Support Engineers investigating query incidents from a static SingleStore Cluster Report must correlate processlist rows, blocked-query chains, query text, tracelog evidence, topology, partitions, resource pools, and Workload Management across multiple nodes.

Query Tracer creates one evidence-linked narrative answering:

> Where was this query observed, which stages can be inferred, and where is it most likely waiting or failing?

The feature does **not** claim to provide live distributed tracing. Every stage must show whether it is observed, inferred, or unavailable.

## 2. SingleStore query execution model

SingleStore is a shared-nothing distributed database. A client sends SQL to an Aggregator. The Aggregator parses, optimizes, compiles or reuses a plan, routes work to Leaf partitions, gathers results, and returns them to the client.

```text
Client
  │
  ▼
Master Aggregator or Child Aggregator
  │  parse → optimize → compile/reuse → route
  ▼
Leaf partition(s)
  │  scan → join → aggregate → repartition/broadcast when required
  ▼
Aggregator
  │  gather / gather merge
  ▼
Client
```

### Execution stages

| Stage | Typical location | Evidence available from a Cluster Report |
|---|---|---|
| Parse and normalize | Aggregator | query text, activity name, compilation tracelog entries |
| Optimize | Aggregator | plan warnings, routing inference, future `EXPLAIN` data |
| Compile or reuse | Aggregator and Leaf nodes | compilation timing, plancache signals, tracelog errors |
| Route and distribute | Aggregator to Leaf nodes | shard-key inference, partition layout, topology |
| Execute | Leaf partitions | processlist, blocked queries, workload metrics, memory |
| Gather results | Aggregator | processlist state, network and timeout evidence |

### Routing inference

- Equality predicates covering every shard-key column may route to one partition.
- An `IN` list on shard-key values may route to a subset of partitions.
- Queries without a usable shard-key restriction may fan out to all partitions.
- Misaligned distributed joins may require Repartition or Broadcast operations.

Routing remains an inference unless an authoritative plan is present.

## 3. Terminology and heuristic boundaries

### User-facing labels

- **Long-Running Queries** — queries whose captured elapsed time exceeds the Sniffer five-minute prioritization threshold.
- **Queries Above the Sniffer Elapsed-Time Threshold** — captured elapsed time from 30 seconds through five minutes.
- **Long-Running Query Patterns** — repeated normalized query patterns whose observed executions include long durations.
- **Lock wait**, **Blocked Query**, **Queued Query**, and **Sleeping Lock Holder** — use only when supported by the corresponding processlist or blocked-query fields.

SingleStore documentation uses *long running queries* but does not define one universal duration threshold for every workload. The durations above are Report Sniffer heuristics and must be labeled accordingly.

### Stable compatibility fields

The following names are internal and remain stable:

- `runawayQueries`
- `slowQueries`
- `runaway_queries`
- `runaway_patterns`
- `slow_queries`
- trace types such as `runaway` and `slow`

Presentation code maps these fields to the labels above.

## 4. Available Cluster Report signals

### Parsed today

| Signal | Typical collector or file | Normalized output | Tracer use |
|---|---|---|---|
| Query text and activity mapping | `informationSchemaMvQueries.json` | `queries[]` | identity and pattern matching |
| Per-node processlist | `informationSchemaProcesslist.json` | `cluster_overview.processlist` | elapsed time, state, connection, query text |
| Cluster-wide processlist | `informationSchemaMvProcesslist.json` | `cluster_overview.mv_processlist` | cross-node state and queue information |
| Blocked queries | `informationSchemaMvBlockedQueries.json` | `cluster_overview.blocked_queries` | blocking graph and wait stage |
| Workload Management | `showWorkloadManagementStatus.json` | `workload_management[]` | queued or governed work |
| Resource pools | `informationSchemaResourcePools.json` | `resource_pools[]` | pool context and saturation evidence |
| Partition layout | distributed-database collectors and `MV_NODES` | `partitions`, `cluster_layout` | fan-out and placement inference |
| Allocation memory | extended status collectors | `alloc_memory` | memory context |
| Tracelogs | `memsqlTracelogs/*_memsql.log` | raw/parsed search | compilation, timeout, retry, and failure evidence |
| Node topology | `informationSchemaMvNodes.json` | `cluster_overview` | Master Aggregator, Child Aggregator, and Leaf placement |
| Replication state | replication collectors and tracelogs | `replication_lag_patterns` | adjacent failure context |
| Query analysis | processlist/query correlation | `query_analysis` | Long-Running Queries, patterns, and lock holders |

### High-value future signals

| Signal | Value |
|---|---|
| `MV_ACTIVITIES` | task-level CPU, memory, network, lock, and blob-cache context |
| `MV_FINISHED_TASKS` | completed task profiles and historical execution context |
| `MV_PLANCACHE` / `PLANCACHE` | plan reuse, execution counts, and cumulative statistics |
| `MV_WORKLOAD_MANAGEMENT_STATUS` | queue depth and governance state |
| `EXPLAIN`, `PROFILE`, or Visual Explain export | authoritative operator and routing tree |
| `activity_tracking_id` | stronger cross-source correlation |

## 5. Failure and wait modes

| Condition | Likely stage | Evidence |
|---|---|---|
| Lock wait timeout | execute / lock acquisition | `MV_BLOCKED_QUERIES`, processlist, tracelog |
| DDL, compile, or cluster-operation blocking | pre-execute or execute | blocking type and chain |
| Long-Running Query | execute or wait | `TIME`, state, query text, blocked rows |
| Workload Management queue | pre-execute | Workload Management status, resource pool, queue reason |
| Compilation timeout or memory pressure | compile | compilation samples and tracelog errors |
| `ETIMEDOUT` | distribute or execute | tracelog context and affected nodes |
| Partition skew or rebalance | route / storage | partition layout and `MV_EVENTS` |
| Synchronous-to-asynchronous transition | replication | tracelog and replication analysis |
| Blob-cache wait in Helios | execute on Leaf node | future `MV_ACTIVITIES` fields |

A long elapsed time does not by itself prove active execution. The query may be waiting on a lock, queue, network operation, compilation, or another query.

## 6. User personas

### L2/L3 Support Engineer

- Receives an offline Cluster Report.
- Needs an evidence-backed hypothesis quickly.
- Must explain confidence and missing signals.
- Often has no live cluster access during initial triage.

### Customer SRE or DBA

- Imports a Cluster Report into the desktop application.
- Wants a clear path from query symptom to evidence and recommended action.
- Needs terminology and documentation links consistent with SingleStore.

## 7. User experience

### Entry points

- Workload and Queries tab.
- Query Pattern Analysis.
- Long-Running Query or lock-contention finding.
- Blocked query table.
- **Trace query** action from query rows and repeated patterns.

### Candidate picker

Each candidate displays:

- user and database
- elapsed time
- state
- resource pool when present
- query preview or normalized pattern
- source (`MV_PROCESSLIST`, `PROCESSLIST`, query map, or blocked queries)
- trace type in documentation-aligned language
- confidence tier

### Flow view

```text
Client → Aggregator → Leaf partition(s) → Aggregator → Client
```

Each stage includes:

- status: healthy, warning, critical, or unknown
- evidence state: observed, inferred, or unavailable
- associated node or role
- supporting evidence links
- confidence contribution

### Timeline view

The timeline combines only timestamped evidence:

- processlist snapshot time when available
- tracelog lines
- compilation events
- lock or blocked-query events
- `MV_EVENTS`
- replication transitions

Do not fabricate ordering when timestamps are unavailable.

### Evidence actions

- View in Logs
- View blocked-query chain
- View node
- View processlist row
- View related finding
- Copy investigation summary

## 8. Confidence model

Confidence is based on observable factors rather than a single opaque score.

Example factors:

| Factor | Effect |
|---|---|
| exact query text match | strong positive |
| activity-name match | strong positive |
| connection or process ID match | strong positive |
| matching node and time window | positive |
| only normalized query-pattern match | moderate |
| only category-level finding match | weak |
| missing timestamps or node identity | negative |
| contradictory processlist states | negative |

Suggested tiers:

- **High** — multiple exact identifiers or direct blocked-query evidence.
- **Medium** — strong text/pattern correlation with supporting node or time evidence.
- **Low** — stage is primarily inferred from topology or generic findings.

The interface should expose the factors that produced the tier.

## 9. Backend model

### Trace identity

A trace ID should be deterministic for a stored Cluster Report and selector. It may use a SHA-256 digest of normalized selector fields.

Selector fields may include:

- process ID
- connection ID
- activity name
- query text hash
- normalized SQL fingerprint
- node ID

### Trace payload

```json
{
  "trace_id": "sha256:...",
  "trace_type": "lock_wait",
  "query_text": "SELECT ...",
  "confidence": {
    "score": 78,
    "tier": "high",
    "factors": []
  },
  "stages": [],
  "edges": [],
  "events": [],
  "evidence": [],
  "limitations": []
}
```

`trace_type` values remain stable API values. Frontend helpers convert them to user-facing labels.

### API surface

```text
GET  /api/reports/{id}/query-traces
POST /api/reports/{id}/query-traces/resolve
GET  /api/reports/{id}/query-traces/{trace_id}
```

Existing related APIs:

```text
GET /api/reports/{id}/overview
GET /api/reports/{id}/queries
GET /api/reports/{id}/logs/search
GET /api/reports/{id}/triage
```

## 10. Correlation strategy

1. Normalize the selector.
2. Match exact process or connection identifiers.
3. Match activity name and query text.
4. Fall back to normalized SQL fingerprint.
5. Attach processlist and blocked-query rows.
6. Attach Workload Management and resource-pool context.
7. Attach relevant tracelog lines using actual message terms.
8. Add topology and partition-routing inference.
9. Add related findings by checker type and affected node.
10. Calculate confidence and limitations.

Never use a checker ID such as `runawayQueries` as a tracelog search term; it does not appear in `memsql.log`.

## 11. Honest limitations

Cluster Reports are static and collector-dependent. Query Tracer may not know:

- exact client-side timing
- the complete distributed operator tree
- every task participating in a query
- precise execution ordering without timestamps
- whether a query was actively consuming CPU or waiting for the entire observed duration
- current cluster state after the report was generated

The UI must use language such as **observed**, **inferred**, **likely**, and **not available** rather than presenting inferred stages as facts.

## 12. Security and privacy

- All correlation runs locally.
- Query text can contain sensitive values and must be handled as customer data.
- Anonymization must occur before persistent storage when enabled.
- Do not include raw query text in telemetry.
- Export and Glean handoff remain explicit user actions.
- Presentation terminology normalization must not rewrite raw SQL, tracelog evidence, or serialized API values.

## 13. Testing

### Backend

- deterministic trace IDs
- exact and normalized query matching
- `MV_PROCESSLIST` versus per-node `PROCESSLIST`
- blocked-query graph construction
- confidence factors and limitations
- empty and partial collector inputs
- stable legacy API fields

### Frontend

- candidate counts use backend summaries rather than truncated arrays
- stable trace types display documentation-aligned labels
- deep links open the correct trace
- query text and raw evidence remain unchanged
- legacy “Runaway Queries” is not rendered
- loading, empty, error, and partial-data states

### Integration

- import a complete Cluster Report
- select a Long-Running Query
- verify flow, timeline, evidence links, and confidence
- validate that **View in Logs** uses a real tracelog pattern
- compare behavior for full, local-only, and sparse reports

## 14. Delivery phases

### Phase 0 — Implemented MVP

- trace candidate API
- trace resolution and retrieval
- flow and timeline components
- entry points from workload/query screens
- stable trace IDs and confidence tiers

### Phase 1 — Evidence navigation

- stronger deep links to Logs, blocked queries, nodes, and findings
- highlighted source evidence
- clearer limitations and missing-collector explanations

### Phase 2 — Richer query metrics

- parse `MV_ACTIVITIES`, `MV_FINISHED_TASKS`, and plancache signals
- add task-level and plan-reuse context
- integrate Workload Management queue metrics

### Phase 3 — Authoritative plan import

- accept offline `EXPLAIN`, `PROFILE`, or Visual Explain exports
- replace routing inference with observed plan operators where available

### Phase 4 — Optional live attach

A future live mode must be explicitly separated from static Cluster Report analysis and use different confidence and privacy controls.

## 15. Documentation references

- Cluster Components
- Query Execution
- Code Generation
- Query Plan Operations
- Shard Keys
- `SHOW PROCESSLIST`
- `MV_PROCESSLIST`
- `MV_BLOCKED_QUERIES`
- Workload Management
- Query Errors — Long Running Queries
- Trace Log Location and Management

Use current SingleStore documentation URLs and verify them before adding grounding links.

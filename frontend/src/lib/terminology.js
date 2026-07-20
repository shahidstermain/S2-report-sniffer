const RULES = [
  {
    pattern: /\bSingleStore diagnostics bundles\b/gi,
    replacement: "SingleStore Cluster Reports",
  },
  {
    pattern: /\bSingleStore diagnostics bundle\b/gi,
    replacement: "SingleStore Cluster Report",
  },
  {
    pattern: /\bSingleStore diagnostic bundles\b/gi,
    replacement: "SingleStore Cluster Reports",
  },
  {
    pattern: /\bSingleStore diagnostic bundle\b/gi,
    replacement: "SingleStore Cluster Report",
  },
  {
    pattern: /\bdiagnostic bundles\b/gi,
    replacement: "Cluster Reports",
  },
  {
    pattern: /\bdiagnostic bundle\b/gi,
    replacement: "Cluster Report",
  },
  {
    pattern: /\bsupport bundles\b/gi,
    replacement: "Cluster Reports",
  },
  {
    pattern: /\bsupport bundle\b/gi,
    replacement: "Cluster Report",
  },
  {
    pattern: /\breport bundles\b/gi,
    replacement: "Cluster Reports",
  },
  {
    pattern: /\breport bundle\b/gi,
    replacement: "Cluster Report",
  },
  {
    pattern: /\bdiagnostic reports\b/gi,
    replacement: "Cluster Reports",
  },
  {
    pattern: /\bdiagnostic report\b/gi,
    replacement: "Cluster Report",
  },
  {
    pattern: /\bdiagnostic snapshots\b/gi,
    replacement: "Cluster Reports",
  },
  {
    pattern: /\bdiagnostic snapshot\b/gi,
    replacement: "Cluster Report",
  },
  {
    pattern: /\bdiagnostic dashboard\b/gi,
    replacement: "Cluster Report dashboard",
  },
  {
    pattern: /\bRunaway Queries\b/gi,
    replacement: "Long-Running Queries",
  },
  {
    pattern: /\bRunaway Query\b/gi,
    replacement: "Long-Running Query",
  },
  {
    pattern: /\brunaway query patterns\b/gi,
    replacement: "long-running query patterns",
  },
  {
    pattern: /\brunaway query pattern\b/gi,
    replacement: "long-running query pattern",
  },
  {
    pattern: /\bSlow Queries\b/g,
    replacement: "Queries Above the Sniffer Elapsed-Time Threshold",
  },
  {
    pattern: /\bslow queries\b/g,
    replacement: "queries above the Sniffer elapsed-time threshold",
  },
  {
    pattern: /\bProcess List\b/g,
    replacement: "Processlist",
  },
  {
    pattern: /\bprocess list\b/g,
    replacement: "processlist",
  },
  {
    pattern: /\bHealth Score\b/g,
    replacement: "Cluster Health Score",
  },
  {
    pattern: /\bhealth score\b/g,
    replacement: "cluster health score",
  },
  {
    pattern: /\bLog Explorer\b/g,
    replacement: "Tracelog Explorer",
  },
  {
    pattern: /\btrace logs\b/gi,
    replacement: "tracelogs",
  },
  {
    pattern: /\btrace log\b/gi,
    replacement: "tracelog",
  },
  {
    pattern: /\bRecommendations tab\b/gi,
    replacement: "Issues tab",
  },
  {
    pattern: /\bprimary and secondary partitions\b/gi,
    replacement: "master and replica partitions",
  },
  {
    pattern: /\bprimary partitions\b/gi,
    replacement: "master partitions",
  },
  {
    pattern: /\bprimary partition\b/gi,
    replacement: "master partition",
  },
  {
    pattern: /\bsecondary partitions\b/gi,
    replacement: "replica partitions",
  },
  {
    pattern: /\bsecondary partition\b/gi,
    replacement: "replica partition",
  },
];

/**
 * Normalize legacy or generic user-facing copy to the terminology used by
 * SingleStore documentation. Stable IDs, API fields, and collector names are
 * intentionally outside the scope of this function.
 */
export function normalizeTerminology(value) {
  if (typeof value !== "string" || value.length === 0) return value;

  let normalized = value;
  for (const { pattern, replacement } of RULES) {
    normalized = normalized.replace(pattern, replacement);
  }

  // Avoid double-prefixing strings that were already documentation-aligned.
  normalized = normalized
    .replace(/\bCluster Cluster Health Score\b/g, "Cluster Health Score")
    .replace(/\bcluster cluster health score\b/g, "cluster health score")
    .replace(/\bSingleStore Cluster Cluster Reports?\b/g, (match) =>
      match.endsWith("Reports")
        ? "SingleStore Cluster Reports"
        : "SingleStore Cluster Report"
    );

  return normalized;
}

export const TERMINOLOGY_RULE_COUNT = RULES.length;

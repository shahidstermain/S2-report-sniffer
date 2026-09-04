import { useLocation } from "react-router-dom";
import { Info } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { glossaryForPage } from "./metricGlossary";
import { pageKeyFromPath } from "./tourRegistry";
import { useGuidedMode } from "./GuidedModeProvider";

const PAGE_COPY = {
  reports: {
    title: "Report list",
    body: "This page manages Cluster Reports, imports local folders, compares snapshots, and summarizes workspace activity.",
  },
  overview: {
    title: "Overview",
    body: "Start here for the investigation narrative: backend-owned severity, topology, memory, disk, backup, query, and issue signals.",
  },
  "disk-intelligence": {
    title: "Disk Intelligence",
    body: "Explains storage pressure, estimated reclaimable space, table skew, and HA-adjusted caveats. Estimates are labeled as Sniffer heuristics.",
  },
  charts: {
    title: "Charts",
    body: "Visualizes trends and distributions extracted from the Cluster Report. Missing collectors are shown as unavailable rather than fabricated values.",
  },
  diagnostics: {
    title: "Diagnostics",
    body: "Combines extended diagnostics such as events, CPU, and network signals when retained report data is available.",
  },
  nodes: {
    title: "Nodes",
    body: "Shows per-node role, state, resource pressure, and signals that help separate topology issues from workload pressure.",
  },
  storage: {
    title: "Storage",
    body: "Shows database disk usage, table storage, partition skew, and supporting disk inventory signals.",
  },
  queries: {
    title: "Queries",
    body: "Uses processlist snapshots and query traces to explain long-running, blocked, high-memory, and repeated workload patterns.",
  },
  logs: {
    title: "Logs",
    body: "Displays parsed logs. For detailed evidence, use Log Search with actual tracelog text or patterns.",
  },
  "log-search": {
    title: "Log Search",
    body: "Searches raw retained tracelogs when available, with parsed logs fallback. Use patterns like ETIMEDOUT or fsync is behind.",
  },
  config: {
    title: "Config",
    body: "Surfaces variables, process limits, license and OS checks that can explain reliability or performance risks.",
  },
  recommendations: {
    title: "Issues",
    body: "Shows grounded findings, basis labels, suggested next actions, and links into logs or query investigation paths.",
  },
};

export default function ExplainPagePanel() {
  const { explainPage } = useGuidedMode();
  const location = useLocation();
  if (!explainPage) return null;
  const pageKey = pageKeyFromPath(location.pathname);
  const copy = PAGE_COPY[pageKey] || PAGE_COPY.overview;
  const glossary = glossaryForPage(pageKey).slice(0, 3);

  return (
    <Alert className="mb-4 border-primary/25 bg-primary/5" data-guide-id="guided.explainPage">
      <Info className="text-primary" />
      <AlertTitle>{copy.title}</AlertTitle>
      <AlertDescription>
        <p>{copy.body}</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          {glossary.map((item) => (
            <div key={item.id} className="rounded-md border bg-background/80 p-2">
              <p className="text-xs font-semibold">{item.title}</p>
              <p className="text-[11px] text-muted-foreground mt-1">{item.interpret}</p>
            </div>
          ))}
        </div>
      </AlertDescription>
    </Alert>
  );
}

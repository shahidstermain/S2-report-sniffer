declare module "@/lib/nextSteps" {
  export function humanizeCheckerId(checkerId: string): string;
  export function humanizeTraceType(traceType: string): string;
  export function normalizeFindingTitle(title: string, checkerId?: string): string;
  export function buildFindingsLookup(findings: unknown[]): Record<string, unknown>;
  export function buildSuggestedNextSteps(findings?: unknown[]): unknown[];
  export function severityStyle(severity: string): Record<string, string>;
}
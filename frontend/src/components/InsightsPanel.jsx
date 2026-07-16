import { AlertTriangle } from "lucide-react";
import { buildSuggestedNextSteps, severityStyle } from "@/lib/nextSteps";

export default function InsightsPanel({ findings = [] }) {
  const nextSteps = buildSuggestedNextSteps(findings);

  return (
    <div className="space-y-4" data-testid="insights-panel">
      {nextSteps.length > 0 && (
        <section className="border border-[var(--ss-divider)] p-4 space-y-3" data-testid="insights-next-steps">
          <h3 className="text-sm font-bold uppercase tracking-wider">Suggested Next Steps</h3>
          <p className="text-[10px] text-[var(--ss-mid-gray)]">
            Priority order derived from report findings
          </p>
          <ol className="space-y-2">
            {nextSteps.map((step) => {
              const style = severityStyle(step.severity);
              return (
                <li key={`${step.findingId}-${step.priority}`} className="border border-[var(--ss-divider)] p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-mono text-zinc-400">#{step.priority}</span>
                    <span
                      className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded"
                      style={{ color: style.color, background: style.bg }}
                    >
                      {step.severity}
                    </span>
                    <span className="text-xs font-semibold">{step.title}</span>
                  </div>
                  <p className="text-xs text-[var(--ss-mid-gray)]">{step.action}</p>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {!findings?.length && (
        <div className="border border-[var(--ss-divider)] p-4 text-xs text-[var(--ss-mid-gray)] flex items-start gap-2">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          Load a report with findings to see suggested next steps.
        </div>
      )}
    </div>
  );
}

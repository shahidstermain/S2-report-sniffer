import { cn } from "@/lib/utils";

export interface TimelineEvent {
  id: string;
  label: string;
  observed: boolean;
  inferred?: boolean;
  timestamp?: string | null;
  stage_id?: string;
  note?: string;
  elapsed_sec?: number;
  source?: string;
}

export interface TimelineLane {
  role: string;
  label: string;
  events: TimelineEvent[];
}

export interface TraceTimeline {
  snapshot_timestamp?: string | null;
  collection_note?: string;
  lanes: TimelineLane[];
}

interface QueryTraceTimelineProps {
  timeline: TraceTimeline;
  selectedStageId?: string | null;
  onSelectStage?: (stageId: string | null) => void;
}

const ROLE_COLORS: Record<string, string> = {
  CLIENT: "#95A5A6",
  MA: "#FF6B6B",
  CA: "#45B7D1",
  LEAF: "#4ECDC4",
};

export default function QueryTraceTimeline({
  timeline,
  selectedStageId,
  onSelectStage,
}: QueryTraceTimelineProps) {
  const lanes = timeline?.lanes || [];
  if (lanes.length === 0) {
    return (
      <div className="rounded border border-border p-6 text-center text-xs text-muted-foreground">
        No timeline events available for this trace.
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-[#050507] overflow-hidden" data-testid="query-trace-timeline">
      {timeline.snapshot_timestamp && (
        <div className="px-3 py-2 border-b border-border text-[10px] text-muted-foreground flex items-center justify-between flex-wrap gap-2 bg-[#0d0f14]">
          <div>
            Snapshot window ends: <span className="font-mono text-foreground">{timeline.snapshot_timestamp}</span>
          </div>
          <div className="italic text-[9px] text-gray-400">
            Lanes align aggregator ingress, leaf execution, lock waits, and tracelog hits captured during report collection.
          </div>
        </div>
      )}
      <div className="divide-y divide-border">
        {lanes.map((lane) => {
          const roleColor = ROLE_COLORS[lane.role] || ROLE_COLORS.CA;
          return (
            <div key={`${lane.role}-${lane.label}`} className="px-3 py-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: roleColor }} />
                <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                  {lane.label}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {lane.events.map((event) => {
                  const selected = selectedStageId && event.stage_id === selectedStageId;
                  return (
                    <button
                      key={event.id}
                      type="button"
                      data-testid={`timeline-event-${event.id}`}
                      onClick={() => onSelectStage?.(selected ? null : event.stage_id || null)}
                      className={cn(
                        "text-left min-w-[140px] max-w-[220px] rounded border px-2 py-2 text-[10px] transition-colors",
                        event.observed ? "border-solid" : "border-dashed",
                        selected ? "border-[#00d992] bg-[#00d992]/10" : "border-border bg-[#111318] hover:bg-[#151820]"
                      )}
                    >
                      <div className="font-semibold text-foreground truncate" title={event.label}>
                        {event.label}
                      </div>
                      <div className="text-muted-foreground mt-1">
                        {event.observed ? "observed" : "inferred"}
                        {event.elapsed_sec ? ` · ${event.elapsed_sec}s` : ""}
                      </div>
                      {event.timestamp && (
                        <div className="font-mono text-[9px] text-muted-foreground mt-1 truncate">
                          {event.timestamp}
                        </div>
                      )}
                      {event.note && (
                        <div className="text-[9px] text-muted-foreground mt-1 line-clamp-2" title={event.note}>
                          {event.note}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      {timeline.collection_note && (
        <p className="px-3 py-2 border-t border-border text-[10px] text-muted-foreground italic">
          {timeline.collection_note}
        </p>
      )}
    </div>
  );
}

import { ArrowUpRight, ArrowDownRight, Minus, FileArchive, Clock, Calendar, AlertTriangle, AlertCircle, Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function TrendBadge({ delta, pct, dir, invertColors = false }) {
  if (dir === "flat") {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-muted-foreground">
        <Minus data-icon="inline-start" /> 0%
      </span>
    );
  }
  const positive = (dir === "up" && !invertColors) || (dir === "down" && invertColors);
  const colorClass = positive ? "text-[var(--ss-success)]" : "text-[var(--ss-critical)]";
  const Icon = dir === "up" ? ArrowUpRight : ArrowDownRight;
  const sign = dir === "up" ? "+" : "";
  return (
    <span className={cn("inline-flex items-center gap-0.5 text-[10px] font-semibold tabular-nums", colorClass)}>
      <Icon data-icon="inline-start" />
      {sign}{Math.abs(pct)}% <span className="font-medium text-muted-foreground">({sign}{delta})</span>
    </span>
  );
}

function KpiCard({ id, label, value, sub, trend, icon: Icon, active, onSelect, invertTrend }) {
  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={() => onSelect && onSelect(id)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect?.(id); } }}
      className={cn(
        "cursor-pointer transition-shadow hover:border-primary/40 hover:shadow-md",
        active && "border-primary ring-1 ring-primary/30 shadow-md"
      )}
      data-testid={`kpi-${id}`}
    >
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">
            {label}
          </span>
          {Icon && <Icon className="text-muted-foreground" />}
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold tabular-nums text-foreground">
            {value}
          </span>
          {trend && <TrendBadge {...trend} invertColors={invertTrend} />}
        </div>
        {sub && (
          <p className="text-[11px] mt-1 text-muted-foreground">{sub}</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function KpiStrip({ totals, periods, status, activeFilter, onSelect }) {
  const items = [
    {
      id: "all",
      label: "Total reports",
      value: totals,
      sub: `${periods.last30d} in last 30 days`,
      icon: FileArchive,
    },
    {
      id: "last24h",
      label: "Last 24h",
      value: periods.last24h,
      trend: periods.trend24h,
      sub: "vs prior 24h",
      icon: Clock,
    },
    {
      id: "last7d",
      label: "Last 7 days",
      value: periods.last7d,
      trend: periods.trend7d,
      sub: "vs prior 7d",
      icon: Calendar,
    },
    {
      id: "critical",
      label: "Critical",
      value: status.critical,
      sub: `${status.healthy} healthy`,
      icon: AlertCircle,
      invertTrend: true,
    },
    {
      id: "warning",
      label: "Warning",
      value: status.warning,
      sub: `${status.ready} ready`,
      icon: AlertTriangle,
    },
    {
      id: "processing",
      label: "Processing",
      value: status.processing,
      sub: `${status.error} errored`,
      icon: Loader2,
    },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {items.map((it) => (
        <KpiCard
          key={it.id}
          {...it}
          active={activeFilter === it.id}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

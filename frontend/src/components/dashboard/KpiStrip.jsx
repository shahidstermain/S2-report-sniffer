import { ArrowUpRight, ArrowDownRight, Minus, FileArchive, Clock, Calendar, AlertTriangle, AlertCircle, Loader2 } from "lucide-react";

function TrendBadge({ delta, pct, dir, invertColors = false }) {
  if (dir === "flat") {
    return (
      <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold" style={{ color: "var(--text-muted)" }}>
        <Minus size={11} /> 0%
      </span>
    );
  }
  const positive = (dir === "up" && !invertColors) || (dir === "down" && invertColors);
  const color = positive ? "var(--ss-success)" : "var(--ss-critical)";
  const Icon = dir === "up" ? ArrowUpRight : ArrowDownRight;
  const sign = dir === "up" ? "+" : "";
  return (
    <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold tabular-nums" style={{ color }}>
      <Icon size={11} />
      {sign}{Math.abs(pct)}% <span style={{ color: "var(--text-muted)" }} className="font-medium">({sign}{delta})</span>
    </span>
  );
}

function KpiCard({ id, label, value, sub, trend, icon: Icon, active, onSelect, invertTrend }) {
  return (
    <button
      type="button"
      onClick={() => onSelect && onSelect(id)}
      className={`kpi-card text-left w-full ${active ? "active" : ""}`}
      data-testid={`kpi-${id}`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: "var(--text-muted)" }}>
          {label}
        </span>
        {Icon && <Icon size={14} style={{ color: "var(--text-muted)" }} />}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold tabular-nums" style={{ color: "var(--text-primary)" }}>
          {value}
        </span>
        {trend && <TrendBadge {...trend} invertColors={invertTrend} />}
      </div>
      {sub && (
        <div className="text-[11px] mt-1" style={{ color: "var(--text-muted)" }}>
          {sub}
        </div>
      )}
    </button>
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

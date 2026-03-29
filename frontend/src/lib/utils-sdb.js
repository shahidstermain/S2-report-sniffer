export function formatBytes(mb) {
  if (mb == null || isNaN(mb)) return "—";
  const num = Number(mb);
  if (num >= 1048576) return `${(num / 1048576).toFixed(1)} TB`;
  if (num >= 1024) return `${(num / 1024).toFixed(1)} GB`;
  return `${num} MB`;
}

export function formatUptime(seconds) {
  if (!seconds) return "—";
  const s = Number(seconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  if (days > 0) return `${days}d ${hours}h`;
  const mins = Math.floor((s % 3600) / 60);
  return `${hours}h ${mins}m`;
}

export function formatNumber(n) {
  if (n == null || isNaN(n)) return "—";
  return Number(n).toLocaleString();
}

export function severityColor(severity) {
  switch ((severity || "").toUpperCase()) {
    case "CRITICAL": case "FATAL": case "ERROR": return "status-critical";
    case "WARNING": case "WARN": return "status-warning";
    case "HEALTHY": case "INFO": case "NOTICE": return "status-success";
    default: return "text-zinc-500";
  }
}

export function severityBadgeClass(severity) {
  switch ((severity || "").toLowerCase()) {
    case "critical": return "badge-critical";
    case "warning": return "badge-warning";
    case "healthy": case "info": return "badge-healthy";
    default: return "bg-zinc-100 text-zinc-600 border border-zinc-200";
  }
}

export function healthColor(health) {
  switch ((health || "").toLowerCase()) {
    case "critical": return "#F44336";
    case "warning": return "#FF9800";
    case "healthy": return "#00C853";
    default: return "#6B6B80";
  }
}

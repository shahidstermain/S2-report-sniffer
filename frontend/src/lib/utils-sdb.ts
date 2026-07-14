type HealthLike = {
  health_score?: number | string | null | undefined;
  health_grade?: string | null | undefined;
};

export function formatMegabytes(mb: number | null | undefined): string {
  if (mb == null || Number.isNaN(Number(mb))) return "—";
  const num = Number(mb);
  if (num >= 1048576) return `${(num / 1048576).toFixed(1)} TB`;
  if (num >= 1024) return `${(num / 1024).toFixed(1)} GB`;
  return `${num} MB`;
}

export function formatBytes(bytes: number | string | null | undefined): string {
  if (bytes == null || bytes === "" || Number.isNaN(Number(bytes))) return "—";
  const num = Number(bytes);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = num;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit >= 3 ? 2 : 1)} ${units[unit]}`;
}

export function getHealthScore(value: number | string | null | undefined): number | null {
  const num = Number(value);
  if (!Number.isFinite(num)) return null;
  return Math.max(0, Math.min(100, Math.round(num)));
}

export function healthGradeFromScore(score: number | null | undefined): string | null {
  if (score == null || !Number.isFinite(score)) return null;
  if (score >= 90) return "A";
  if (score >= 80) return "B";
  if (score >= 70) return "C";
  if (score >= 60) return "D";
  return "F";
}

export function getHealthGrade(report: HealthLike | null | undefined): string | null {
  const grade = String(report?.health_grade || "").trim().toUpperCase();
  if (grade && ["A", "B", "C", "D", "F"].includes(grade)) return grade;
  return healthGradeFromScore(getHealthScore(report?.health_score));
}

export function getHealthBucket(report: HealthLike | null | undefined): "healthy" | "warning" | "critical" | "unknown" {
  const legacy = String(report?.health_score || "").trim().toLowerCase();
  if (legacy === "healthy" || legacy === "warning" || legacy === "critical") return legacy;

  const grade = getHealthGrade(report);
  if (grade === "F") return "critical";
  if (grade === "C" || grade === "D") return "warning";
  if (grade === "A" || grade === "B") return "healthy";
  return "unknown";
}

export function formatUptime(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const s = Number(seconds);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  if (days > 0) return `${days}d ${hours}h`;
  const mins = Math.floor((s % 3600) / 60);
  return `${hours}h ${mins}m`;
}

export function formatNumber(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return "—";
  return Number(n).toLocaleString();
}

export function severityColor(severity: string | null | undefined): string {
  switch ((severity || "").toUpperCase()) {
    case "CRITICAL":
    case "FATAL":
    case "ERROR":
      return "status-critical";
    case "WARNING":
    case "WARN":
      return "status-warning";
    case "HEALTHY":
    case "INFO":
    case "NOTICE":
      return "status-success";
    default:
      return "text-zinc-500";
  }
}

export function severityBadgeClass(severity: string | null | undefined): string {
  switch ((severity || "").toLowerCase()) {
    case "critical":
      return "badge-critical";
    case "warning":
      return "badge-warning";
    case "healthy":
    case "info":
      return "badge-healthy";
    default:
      return "bg-zinc-100 text-zinc-600 border border-zinc-200";
  }
}

export function healthColor(health: string | null | undefined): string {
  const normalized = (health || "").toLowerCase();
  switch (normalized) {
    case "critical":
    case "f":
      return "#F44336";
    case "warning":
    case "c":
    case "d":
      return "#FF9800";
    case "healthy":
    case "a":
    case "b":
      return "#00C853";
    default:
      return "#6B6B80";
  }
}

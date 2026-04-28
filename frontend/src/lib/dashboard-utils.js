// Pure data transforms for the homepage dashboard.
// Keep these UI-free so they can be tested in isolation.

const DAY_MS = 24 * 60 * 60 * 1000;

function toMs(value) {
  if (!value) return 0;
  const t = new Date(value).getTime();
  return Number.isFinite(t) ? t : 0;
}

export function bucketByPeriod(reports, now = Date.now()) {
  let last24h = 0, prev24h = 0;
  let last7d = 0, prev7d = 0;
  let last30d = 0;
  for (const r of reports) {
    const t = toMs(r.uploaded_at);
    if (!t) continue;
    const age = now - t;
    if (age >= 0 && age < DAY_MS) last24h++;
    else if (age >= DAY_MS && age < 2 * DAY_MS) prev24h++;
    if (age >= 0 && age < 7 * DAY_MS) last7d++;
    else if (age >= 7 * DAY_MS && age < 14 * DAY_MS) prev7d++;
    if (age >= 0 && age < 30 * DAY_MS) last30d++;
  }
  return { last24h, prev24h, last7d, prev7d, last30d };
}

export function computeStatusBreakdown(reports) {
  const counts = { ready: 0, processing: 0, error: 0, healthy: 0, warning: 0, critical: 0, unknown: 0 };
  for (const r of reports) {
    const status = String(r.status || "").toLowerCase();
    if (status === "ready") counts.ready++;
    else if (status === "processing") counts.processing++;
    else if (status === "error") counts.error++;
    else counts.unknown++;

    if (status === "ready") {
      const h = String(r.health_score || "").toLowerCase();
      if (h === "critical") counts.critical++;
      else if (h === "warning") counts.warning++;
      else if (h === "healthy") counts.healthy++;
    }
  }
  return counts;
}

export function computeDeploymentBreakdown(reports) {
  const map = new Map();
  for (const r of reports) {
    const m = String(r.deployment_method || "Unknown").trim() || "Unknown";
    map.set(m, (map.get(m) || 0) + 1);
  }
  const total = reports.length || 1;
  return [...map.entries()]
    .map(([label, count]) => ({ label, count, pct: Math.round((count / total) * 100) }))
    .sort((a, b) => b.count - a.count);
}

export function buildUploadsTimeline(reports, days = 14, now = Date.now()) {
  const buckets = new Array(days).fill(0).map((_, i) => {
    const dayStart = new Date(now - (days - 1 - i) * DAY_MS);
    dayStart.setHours(0, 0, 0, 0);
    return {
      date: dayStart.getTime(),
      label: dayStart.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      count: 0,
      critical: 0,
      warning: 0,
      healthy: 0,
    };
  });
  const startMs = buckets[0].date;
  const endMs = buckets[buckets.length - 1].date + DAY_MS;
  for (const r of reports) {
    const t = toMs(r.uploaded_at);
    if (!t || t < startMs || t >= endMs) continue;
    const idx = Math.floor((t - startMs) / DAY_MS);
    if (idx < 0 || idx >= days) continue;
    buckets[idx].count++;
    const h = String(r.health_score || "").toLowerCase();
    if (h === "critical") buckets[idx].critical++;
    else if (h === "warning") buckets[idx].warning++;
    else if (h === "healthy") buckets[idx].healthy++;
  }
  return buckets;
}

export function deltaFrom(current, previous) {
  if (!previous && !current) return { delta: 0, pct: 0, dir: "flat" };
  if (!previous) return { delta: current, pct: 100, dir: current > 0 ? "up" : "flat" };
  const delta = current - previous;
  const pct = Math.round((delta / previous) * 100);
  const dir = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  return { delta, pct, dir };
}

export function filterReports(reports, { search, statusFilter }) {
  const q = (search || "").trim().toLowerCase();
  return reports.filter((r) => {
    if (statusFilter && statusFilter !== "all") {
      const status = String(r.status || "").toLowerCase();
      const health = String(r.health_score || "").toLowerCase();
      if (statusFilter === "processing" && status !== "processing") return false;
      if (statusFilter === "error" && status !== "error") return false;
      if (statusFilter === "critical" && (status !== "ready" || health !== "critical")) return false;
      if (statusFilter === "warning" && (status !== "ready" || health !== "warning")) return false;
      if (statusFilter === "healthy" && (status !== "ready" || health !== "healthy")) return false;
    }
    if (q) {
      const hay = [
        r.report_name, r.deployment_method, r.detected_format,
        r.version, r.health_score, r.status,
      ].map((v) => String(v || "").toLowerCase()).join(" ");
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function sortReports(reports, { key, dir }) {
  if (!key) return reports;
  const sign = dir === "asc" ? 1 : -1;
  const get = (r) => {
    switch (key) {
      case "uploaded_at": return toMs(r.uploaded_at);
      case "file_size": return Number(r.file_size) || 0;
      case "node_count": return Number(r.node_count) || 0;
      case "recommendation_count": return Number(r.recommendation_count) || 0;
      case "report_name": return String(r.report_name || "").toLowerCase();
      case "status": return String(r.status || "").toLowerCase();
      case "health_score": return String(r.health_score || "").toLowerCase();
      case "deployment_method": return String(r.deployment_method || "").toLowerCase();
      default: return 0;
    }
  };
  return [...reports].sort((a, b) => {
    const va = get(a), vb = get(b);
    if (va < vb) return -1 * sign;
    if (va > vb) return 1 * sign;
    return 0;
  });
}

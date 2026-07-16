/**
 * Clipboard helpers — work in browser, Electron (IPC preferred), and legacy execCommand.
 *
 * In the packaged Electron app (sandboxed renderer), navigator.clipboard.writeText
 * is often present but fails or no-ops. Prefer the main-process IPC bridge when
 * exposed by preload so Copy Summary / Glean handoff actually land on the system clipboard.
 */

function desktopBridge() {
  return typeof window !== "undefined" ? window.s2rsDesktop : undefined;
}

export async function copyTextToClipboard(text) {
  const value = String(text ?? "");
  if (!value) {
    throw new Error("Nothing to copy");
  }

  const desktop = desktopBridge();
  if (desktop?.clipboardWriteText) {
    await desktop.clipboardWriteText(value);
    return;
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
  } catch {
    // Clipboard API may be blocked in sandboxed or non-secure contexts.
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!ok) {
    throw new Error("Copy failed");
  }
}

export async function readTextFromClipboard() {
  const desktop = desktopBridge();
  if (desktop?.clipboardReadText) {
    return await desktop.clipboardReadText();
  }

  try {
    if (navigator.clipboard?.readText) {
      return await navigator.clipboard.readText();
    }
  } catch {
    // Fall through.
  }

  throw new Error("Clipboard read unavailable");
}

/**
 * Build a paste-ready Issues summary for Slack / notes.
 * @param {{
 *   reportId?: string,
 *   reportName?: string,
 *   healthScore?: number | null,
 *   healthGrade?: string | null,
 *   triageSummary?: { act_now?: number, quick_wins?: number, act_soon?: number, backlog?: number } | null,
 *   triageData?: { act_now?: any[], quick_wins?: any[] } | null,
 *   recommendations?: any[],
 *   critCount?: number,
 *   warnCount?: number,
 *   infoCount?: number,
 * }} opts
 */
export function buildIssuesCopySummary(opts = {}) {
  const reportId = opts.reportId || "unknown";
  const reportName = opts.reportName || "";
  const healthScore = opts.healthScore;
  const healthGrade = opts.healthGrade;
  const s = opts.triageSummary;
  const triage = opts.triageData || {};
  const recs = Array.isArray(opts.recommendations) ? opts.recommendations : [];

  const healthLine =
    healthScore != null && Number.isFinite(Number(healthScore))
      ? `Finding Severity Index: ${Math.round(Number(healthScore))}/100${
          healthGrade ? ` (Grade ${healthGrade})` : ""
        }`
      : "Finding Severity Index: — (backend score unavailable)";

  const lines = [
    "S2 Report Sniffer — Issues summary",
    reportName ? `Report: ${reportName}` : null,
    `Report ID: ${reportId}`,
    healthLine,
    "(Finding Severity Index is a Sniffer score — not a SingleStore docs metric)",
  ].filter(Boolean);

  if (s) {
    lines.push(
      `Triage: Act Now ${s.act_now ?? 0} | Quick Wins ${s.quick_wins ?? 0} | Act Soon ${s.act_soon ?? 0} | Backlog ${s.backlog ?? 0}`
    );
  } else {
    lines.push(
      `Findings: ${opts.critCount ?? 0} CRITICAL | ${opts.warnCount ?? 0} WARNING | ${opts.infoCount ?? 0} INFO`
    );
  }

  const actNow =
    (Array.isArray(triage.act_now) && triage.act_now.length
      ? triage.act_now
      : recs.filter((r) => r?.severity === "critical")
    ).slice(0, 8);

  if (actNow.length) {
    lines.push("", "Act now:");
    for (const item of actNow) {
      const title = item?.title || item?.checker_id || "Finding";
      const sev = String(item?.severity || "critical").toUpperCase();
      const nodes = Array.isArray(item?.nodes) && item.nodes.length ? ` [${item.nodes.slice(0, 3).join(", ")}]` : "";
      lines.push(`- [${sev}] ${title}${nodes}`);
    }
  }

  const quickWins = (Array.isArray(triage.quick_wins) ? triage.quick_wins : []).slice(0, 5);
  if (quickWins.length) {
    lines.push("", "Quick wins:");
    for (const item of quickWins) {
      lines.push(`- ${item?.title || item?.checker_id || "Finding"}`);
    }
  }

  return lines.join("\n");
}

/** @deprecated Use copyTextToClipboard */
export const writeClipboardText = copyTextToClipboard;

export const GUIDED_MODE_VERSION = "2026.08";

const KEY_PREFIX = "s2rs.guidedMode.";

function canUseStorage() {
  return typeof window !== "undefined" && Boolean(window.localStorage);
}

export function loadGuidedPreference(key, fallback = null) {
  if (!canUseStorage()) return fallback;
  try {
    const raw = window.localStorage.getItem(KEY_PREFIX + key);
    return raw == null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function saveGuidedPreference(key, value) {
  if (!canUseStorage()) return;
  try {
    window.localStorage.setItem(KEY_PREFIX + key, JSON.stringify(value));
  } catch {
    // Local UI preference only; ignore private-mode quota failures.
  }
}

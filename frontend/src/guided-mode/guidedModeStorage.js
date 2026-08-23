export const GUIDED_MODE_VERSION = "2026.08";

const KEY_PREFIX = "s2rs.guidedMode.";

function getStorage() {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage || null;
  } catch {
    return null;
  }
}

export function loadGuidedPreference(key, fallback = null) {
  const storage = getStorage();
  if (!storage) return fallback;
  try {
    const raw = storage.getItem(KEY_PREFIX + key);
    return raw == null ? fallback : JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function saveGuidedPreference(key, value) {
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.setItem(KEY_PREFIX + key, JSON.stringify(value));
  } catch {
    // Local UI preference only; ignore private-mode quota failures.
  }
}

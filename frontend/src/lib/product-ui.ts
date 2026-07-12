export type CapabilityState = { available: boolean; reason: string };
export type Capabilities = { features?: Record<string, CapabilityState> } | null | undefined;

export function tabState(tabId: string, capabilities: Capabilities): CapabilityState {
  const state = capabilities?.features?.[tabId];
  if (!state) return { available: true, reason: "Available" };
  return {
    available: Boolean(state.available),
    reason: state.reason || (state.available ? "Available" : "Unavailable for this input"),
  };
}

export function firstAvailableTab(tabIds: string[], capabilities: Capabilities): string {
  return tabIds.find((id) => tabState(id, capabilities).available) || tabIds[0] || "overview";
}

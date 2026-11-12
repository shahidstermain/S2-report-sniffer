import { act } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import UpdateBanner from "./UpdateBanner";

function installUpdater() {
  const listeners = {};
  const subscribe = (name) => (callback) => {
    listeners[name] = callback;
    return () => {};
  };
  window.s2rsDesktop = {
    updater: {
      checkForUpdates: vi.fn(),
      downloadUpdate: vi.fn(),
      installUpdate: vi.fn(),
      getAutoUpdateEnabled: vi.fn(),
      setAutoUpdateEnabled: vi.fn(),
      onChecking: subscribe("checking"),
      onUpdateAvailable: subscribe("available"),
      onUpdateNotAvailable: subscribe("none"),
      onUpdateProgress: subscribe("progress"),
      onUpdateDownloaded: subscribe("downloaded"),
      onUpdateError: subscribe("error"),
      onManual: subscribe("manual"),
    },
  };
  return listeners;
}

describe("UpdateBanner", () => {
  beforeEach(() => {
    const values = new Map();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
        clear: () => values.clear(),
      },
    });
  });

  afterEach(() => {
    delete window.s2rsDesktop;
  });

  test("offers a download when an update is available", () => {
    const listeners = installUpdater();
    render(<UpdateBanner />);
    act(() => listeners.available({ version: "1.2.16" }));
    expect(screen.getByRole("button", { name: "Download update" })).toBeInTheDocument();
  });

  test("explains a manual install when the app cannot replace itself", () => {
    const listeners = installUpdater();
    render(<UpdateBanner />);
    act(() => listeners.manual({
      version: "1.2.16",
      message: "Move the app to Applications before updating",
    }));
    expect(screen.getByText("Move the app to Applications before updating")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open installer" })).toBeInTheDocument();
  });
});

import React from "react";
import { describe, test, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import ReportList from "./ReportList";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api", () => ({
  listReports: vi.fn().mockResolvedValue({ data: [] }),
  uploadReport: vi.fn(),
  importReport: vi.fn(),
  deleteReport: vi.fn(),
}));
vi.mock("@/lib/utils-sdb", () => ({
  healthColor: vi.fn().mockReturnValue("green"),
}));
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    ResponsiveContainer: ({ children }) => <div>{children}</div>,
  };
});

describe('ReportList Component', () => {
  test('renders header and main sections', async () => {
    render(
      <BrowserRouter>
        <ReportList />
      </BrowserRouter>
    );
    expect(screen.getByTestId('app-logo')).toHaveClass('w-[120px]', 'sm:w-[150px]', 'shrink-0');
    expect(screen.getByTestId('app-title')).toHaveClass('hidden', 'sm:inline');
    expect(screen.getAllByText('Report Sniffer').length).toBeGreaterThan(0);
    // Use findByText because listReports is async
    expect(await screen.findByText('No reports uploaded yet')).toBeInTheDocument();
  });

  test('file input accepts all supported archive types', async () => {
    render(
      <BrowserRouter>
        <ReportList />
      </BrowserRouter>
    );

    const input = screen.getByTestId('file-input');
    expect(input).toHaveAttribute(
      'accept',
      '.zip,.tar,.tar.gz,.tgz,.gz,application/zip,application/x-tar,application/gzip,application/x-gzip,application/octet-stream'
    );
    await waitFor(() => expect(screen.getByText('No reports uploaded yet')).toBeInTheDocument());
  });
});

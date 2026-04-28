import React from 'react';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import ReportList from './ReportList';

// Mock dependencies
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));
jest.mock('@/lib/api', () => ({
  listReports: jest.fn().mockResolvedValue({ data: [] }),
  uploadReport: jest.fn(),
  importReport: jest.fn(),
  deleteReport: jest.fn(),
}));
jest.mock('@/lib/utils-sdb', () => ({
  healthColor: jest.fn().mockReturnValue('green'),
}));

describe('ReportList Component', () => {
  test('renders header and main sections', async () => {
    render(
      <BrowserRouter>
        <ReportList />
      </BrowserRouter>
    );
    expect(screen.getByTestId('app-logo')).toBeInTheDocument();
    expect(screen.getAllByText('Report Sniffer').length).toBeGreaterThan(0);
    // Use findByText because listReports is async
    expect(await screen.findByText('No reports uploaded yet')).toBeInTheDocument();
  });

  test('file input accepts all supported archive types', () => {
    render(
      <BrowserRouter>
        <ReportList />
      </BrowserRouter>
    );

    const input = screen.getByTestId('file-input');
    expect(input).toHaveAttribute(
      'accept',
      '.tar.gz,.tgz,.tar,.gz,.zip,application/gzip,application/x-gzip,application/x-tar'
    );
  });
});

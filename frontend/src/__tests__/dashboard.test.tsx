/**
 * dashboard.test.tsx
 * Verifies the dashboard page renders key section headers without crashing.
 * All API calls are mocked to return empty/minimal data.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

const mockApiData = {
  getDashboardStats: vi.fn().mockResolvedValue({
    total_patients: 120,
    average_raf_score: 1.23,
    high_risk_patients: 30,
    revenue_opportunity: 45000,
  }),
  getDashboardTrends: vi.fn().mockResolvedValue([]),
  getPopulationSummary: vi.fn().mockResolvedValue({ low: 40, medium: 50, high: 30 }),
  getRevenueOpportunity: vi.fn().mockResolvedValue({ total: 45000, captured: 20000 }),
  getDataCompleteness: vi.fn().mockResolvedValue({ completeness: 88 }),
  getPatientScorecard: vi.fn().mockResolvedValue([]),
  getEmrStatus: vi.fn().mockResolvedValue({ connected: false }),
  connectDemoEmr: vi.fn().mockResolvedValue({}),
  getProviders: vi.fn().mockResolvedValue([]),
  getSuspectsSummary: vi.fn().mockResolvedValue({ total: 0, pending: 0 }),
  getWorkflowSummary: vi.fn().mockResolvedValue({ total: 0 }),
  default: { get: vi.fn(), post: vi.fn() },
};

vi.mock("@/lib/api", () => mockApiData);

vi.mock("@/components/error-boundary", () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/ui/tooltip", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock heavyweight chart sub-components to keep test fast
vi.mock("@/components/dashboard-charts", () => ({
  AnimatedNumber: ({ value }: { value: unknown }) => <span>{String(value)}</span>,
  Sparkline: () => <svg data-testid="sparkline" />,
  MiniBarChart: () => <svg data-testid="mini-bar" />,
  WaterfallChart: () => <svg data-testid="waterfall-chart" />,
  CircularGauge: () => <svg data-testid="circular-gauge" />,
  DateRangeSelector: ({ onChange }: { value?: unknown; onChange: (v: string) => void }) => (
    <select data-testid="date-range-selector" onChange={(e) => onChange(e.target.value)}>
      <option value="30d">Last 30 days</option>
    </select>
  ),
  ExportButton: () => <button data-testid="export-btn">Export</button>,
  RiskDonut: () => <svg data-testid="risk-donut" />,
  TrendLine: () => <svg data-testid="trend-line" />,
}));

// ── Helper ─────────────────────────────────────────────────────────────────────

async function renderDashboard() {
  // Dynamic import so mocks are in place before module evaluation
  const { default: DashboardPage } = await import("@/app/page");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DashboardPage />
    </QueryClientProvider>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Dashboard page", () => {
  it("renders without crashing", async () => {
    const { container } = await renderDashboard();
    expect(container).toBeTruthy();
  });

  it("renders the page heading", async () => {
    await renderDashboard();
    // Dashboard page title is "Population Health Intelligence"
    expect(
      screen.getAllByText(/population health intelligence/i).length
    ).toBeGreaterThan(0);
  });
});

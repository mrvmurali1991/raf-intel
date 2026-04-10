/**
 * system.test.tsx
 * Verifies the System Health page renders key sections and status indicators.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/system",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

const mockHealthResponse = {
  status: "healthy" as const,
  request_id: "abc-123",
  databases: { raf_db: true, auth_db: true },
  gemini_model: "gemini-1.5-pro",
  sync_scheduler: {
    running: true,
    check_interval_seconds: 300,
    retention_check_interval_hours: 24,
    last_retention_sweep: "2026-04-05T10:00:00Z",
  },
  monitoring: { error_count: 0 },
};

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: mockHealthResponse }),
  },
}));

vi.mock("@/contexts/auth-context", () => ({
  authApi: {
    get: vi.fn().mockImplementation((url: string) => {
      if (url.includes("users")) {
        return Promise.resolve({ data: [{ is_active: true }, { is_active: false }] });
      }
      if (url.includes("audit-log")) {
        return Promise.resolve({ data: [] });
      }
      if (url.includes("retention")) {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: {} });
    }),
  },
}));

// ── Helper ─────────────────────────────────────────────────────────────────────

async function renderSystemHealth() {
  const { default: SystemPage } = await import("@/app/system/page");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SystemPage />
    </QueryClientProvider>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("System Health page", () => {
  it("renders without crashing", async () => {
    const { container } = await renderSystemHealth();
    expect(container).toBeTruthy();
  });

  it("shows System Health heading", async () => {
    await renderSystemHealth();
    expect(screen.getAllByText(/system health/i).length).toBeGreaterThan(0);
  });

  it("shows Refresh button", async () => {
    await renderSystemHealth();
    expect(screen.getByRole("button", { name: /refresh/i })).toBeInTheDocument();
  });

  it("shows Service Health section", async () => {
    await renderSystemHealth();
    expect(screen.getAllByText(/service health/i).length).toBeGreaterThan(0);
  });

  it("shows audit log section", async () => {
    await renderSystemHealth();
    expect(screen.getAllByText(/audit log/i).length).toBeGreaterThan(0);
  });

  it("shows data retention section", async () => {
    await renderSystemHealth();
    expect(screen.getAllByText(/retention/i).length).toBeGreaterThan(0);
  });
});

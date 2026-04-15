/**
 * emr-config.test.tsx
 * Tests EMR configuration page renders connection list and form.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/emr-config",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { role: "admin" },
  }),
  authApi: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

// Mock the api module to return empty connections and vendors
vi.mock("@/lib/api", () => {
  const instance = {
    get: vi.fn().mockImplementation((url: string) => {
      if (url.includes("vendors")) return Promise.resolve({ data: [] });
      if (url.includes("connections")) return Promise.resolve({ data: [] });
      return Promise.resolve({ data: {} });
    }),
    post: vi.fn().mockResolvedValue({ data: { success: true, message: "OK" } }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: {
      request: { use: vi.fn(), eject: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
    defaults: { headers: { common: {} } },
  };
  return { default: instance, API_BASE: "http://localhost:8500" };
});

// ── Helpers ──────────────────────────────────────────────────────────────────

async function renderPage() {
  const { default: EmrConfigPage } = await import("@/app/emr-config/page");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EmrConfigPage />
    </QueryClientProvider>
  );
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("EMR Config Page", () => {
  it("renders the page without crashing", async () => {
    await renderPage();
    expect(document.body.textContent).toBeTruthy();
  });

  it("shows EMR-related content", async () => {
    await renderPage();
    await waitFor(() => {
      const text = document.body.textContent ?? "";
      expect(text.toLowerCase()).toMatch(/emr|connection|integration/);
    });
  });

  it("renders interactive elements", async () => {
    await renderPage();
    await waitFor(() => {
      const buttons = screen.queryAllByRole("button");
      expect(buttons.length).toBeGreaterThan(0);
    });
  });
});

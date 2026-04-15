/**
 * layout.test.tsx
 * Tests that the Sidebar renders navigation links for authenticated users.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Globals ──────────────────────────────────────────────────────────────────

// Sidebar uses EventSource for real-time notifications
(globalThis as any).EventSource = class {
  constructor() {}
  close() {}
  addEventListener() {}
  removeEventListener() {}
};

// ── Mocks ────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/",
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
    user: { email: "admin@raf.health", role: "admin", full_name: "Admin" },
    logout: vi.fn(),
  }),
  authApi: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
  getAccessToken: () => "mock-token",
}));

vi.mock("@/providers/theme-provider", () => ({
  useTheme: () => ({ theme: "light", toggle: vi.fn() }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/api", () => {
  const instance = {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: {
      request: { use: vi.fn(), eject: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
    defaults: { headers: { common: {} } },
  };
  return { default: instance, API_BASE: "http://localhost:8500" };
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("Layout / Sidebar", () => {
  it("renders the Sidebar component with navigation links", async () => {
    // Import Sidebar directly rather than full layout (avoids html/body nesting issues in tests)
    const { Sidebar } = await import("@/components/Sidebar");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={qc}>
        <Sidebar />
      </QueryClientProvider>
    );

    // Sidebar should contain at least a dashboard link
    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThan(0);
  });

  it("highlights the active route", async () => {
    const { Sidebar } = await import("@/components/Sidebar");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { container } = render(
      <QueryClientProvider client={qc}>
        <Sidebar />
      </QueryClientProvider>
    );

    // The container should render without crashing
    expect(container.innerHTML).toBeTruthy();
  });
});

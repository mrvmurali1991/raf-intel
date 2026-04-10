/**
 * Sidebar.test.tsx
 * Verifies nav links render, active state is applied, and admin section is visible.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ─────────────────────────────────────────────────────────────────────

// next/navigation
const mockPathname = vi.fn(() => "/");
vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

// next/link — render as plain <a>
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// Providers
vi.mock("@/providers/theme-provider", () => ({
  useTheme: () => ({ theme: "light", toggle: vi.fn() }),
}));

vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({
    user: { first_name: "Jane", last_name: "Doe", role: "admin", email: "jane@example.com" },
    isAuthenticated: true,
    logout: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  getEmrStatus: vi.fn().mockResolvedValue({ connected: true }),
  default: { get: vi.fn(), post: vi.fn() },
}));

vi.mock("@/components/NotificationCenter", () => ({
  NotificationCenter: () => <div data-testid="notification-center" />,
}));

vi.mock("@/components/KeyboardShortcuts", () => ({
  hasUsedKeyboardShortcuts: () => false,
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

import { Sidebar } from "@/components/Sidebar";

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Sidebar />
    </QueryClientProvider>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Sidebar", () => {
  beforeEach(() => {
    mockPathname.mockReturnValue("/");
  });

  it("renders the TMIAB RAF brand name", () => {
    renderSidebar();
    expect(screen.getAllByText("TMIAB").length).toBeGreaterThan(0);
    expect(screen.getAllByText("RAF").length).toBeGreaterThan(0);
  });

  it("renders main nav links", () => {
    renderSidebar();
    expect(screen.getAllByText("Dashboard").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Patients").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Review Queue").length).toBeGreaterThan(0);
  });

  it("renders analysis section links", () => {
    renderSidebar();
    expect(screen.getAllByText("Documents").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Claims").length).toBeGreaterThan(0);
  });

  it("renders admin section links", () => {
    renderSidebar();
    expect(screen.getAllByText("System Health").length).toBeGreaterThan(0);
    expect(screen.getAllByText("EMR Config").length).toBeGreaterThan(0);
  });

  it("marks the active link with aria-current=page when on /patients", () => {
    mockPathname.mockReturnValue("/patients");
    renderSidebar();
    // Find anchor tags with aria-current="page" — there may be 2 (desktop + mobile)
    const activeLinks = document.querySelectorAll('a[aria-current="page"]');
    expect(activeLinks.length).toBeGreaterThan(0);
    activeLinks.forEach((link) => {
      expect(link.getAttribute("href")).toBe("/patients");
    });
  });

  it("marks Dashboard active when on /", () => {
    mockPathname.mockReturnValue("/");
    renderSidebar();
    const activeLinks = document.querySelectorAll('a[aria-current="page"]');
    expect(activeLinks.length).toBeGreaterThan(0);
    activeLinks.forEach((link) => {
      expect(link.getAttribute("href")).toBe("/");
    });
  });

  it("renders user name in the profile section", () => {
    renderSidebar();
    expect(screen.getAllByText("Jane Doe").length).toBeGreaterThan(0);
  });

  it("renders sign-out button when authenticated", () => {
    renderSidebar();
    const logoutButtons = screen.getAllByRole("button", { name: /sign out/i });
    expect(logoutButtons.length).toBeGreaterThan(0);
  });
});

/**
 * documents.test.tsx
 * Verifies the documents page renders, shows tabs, and the OpenEMR tab is present.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/documents",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("next/image", () => ({
  default: (props: { src: string; alt: string; [k: string]: unknown }) => (
    // eslint-disable-next-line @next/next/no-img-element
    <img {...props} alt={props.alt} />
  ),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { documents: [], total: 0 } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
  searchPatients: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/components/ErrorBoundary", () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// ── Helper ─────────────────────────────────────────────────────────────────────

async function renderDocuments() {
  const { default: DocumentsPage } = await import("@/app/documents/page");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DocumentsPage />
    </QueryClientProvider>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Documents page", () => {
  it("renders without crashing", async () => {
    const { container } = await renderDocuments();
    expect(container).toBeTruthy();
  });

  it("shows Documents heading", async () => {
    await renderDocuments();
    expect(screen.getAllByText(/documents/i).length).toBeGreaterThan(0);
  });

  it("shows the OpenEMR tab", async () => {
    await renderDocuments();
    const openEmrTab = screen.getAllByText(/openemr/i);
    expect(openEmrTab.length).toBeGreaterThan(0);
  });

  it("shows upload area or empty state when no documents", async () => {
    await renderDocuments();
    // Either an upload CTA or an empty-state message should appear
    const uploadOrEmpty =
      screen.queryAllByText(/upload/i).length > 0 ||
      screen.queryAllByText(/no documents/i).length > 0 ||
      screen.queryAllByText(/drag/i).length > 0;
    expect(uploadOrEmpty).toBe(true);
  });

  it("can switch to OpenEMR tab", async () => {
    await renderDocuments();
    const user = userEvent.setup();
    const openEmrTab = screen.getAllByText(/openemr/i)[0];
    await user.click(openEmrTab);
    // After click the tab should still be present (no crash)
    expect(screen.getAllByText(/openemr/i).length).toBeGreaterThan(0);
  });
});

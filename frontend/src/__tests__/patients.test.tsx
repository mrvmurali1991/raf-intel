/**
 * patients.test.tsx
 * Verifies the patients page renders a list (or empty state) and key UI elements.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/patients",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

const mockPatients = [
  {
    id: 1,
    first_name: "Alice",
    last_name: "Smith",
    date_of_birth: "1960-05-10",
    raf_score: 1.45,
    hcc_count: 3,
    risk_level: "high",
    city: "Austin",
    state: "TX",
  },
  {
    id: 2,
    first_name: "Bob",
    last_name: "Jones",
    date_of_birth: "1970-08-22",
    raf_score: 0.82,
    hcc_count: 1,
    risk_level: "low",
    city: "Dallas",
    state: "TX",
  },
];

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn().mockResolvedValue({
      data: { patients: mockPatients, total: 2, page: 1, pages: 1 },
    }),
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
  searchPatients: vi.fn().mockResolvedValue(mockPatients),
}));

vi.mock("@/components/ErrorBoundary", () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/csv-export", () => ({
  downloadCSV: vi.fn(),
}));

vi.mock("@/lib/utils", () => ({
  calculateAge: vi.fn((dob: string) => {
    return new Date().getFullYear() - new Date(dob).getFullYear();
  }),
}));

// ── Helper ─────────────────────────────────────────────────────────────────────

async function renderPatients() {
  const { default: PatientsPage } = await import("@/app/patients/page");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PatientsPage />
    </QueryClientProvider>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Patients page", () => {
  it("renders without crashing", async () => {
    const { container } = await renderPatients();
    expect(container).toBeTruthy();
  });

  it("shows Patients heading", async () => {
    await renderPatients();
    expect(screen.getAllByText(/patients/i).length).toBeGreaterThan(0);
  });

  it("shows risk filter options", async () => {
    await renderPatients();
    // Risk filters are rendered as <option> elements inside a <select>
    expect(screen.getAllByRole("option", { name: /all/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("option", { name: /high risk/i }).length).toBeGreaterThan(0);
  });

  it("shows search input", async () => {
    await renderPatients();
    const searchInput = screen.getByPlaceholderText(/search/i);
    expect(searchInput).toBeInTheDocument();
  });
});

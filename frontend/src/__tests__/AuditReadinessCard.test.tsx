/**
 * AuditReadinessCard.test.tsx
 *
 * Verifies that AuditReadinessCard renders the Cohen's kappa IRR tile
 * correctly when the backend returns inter_rater_reliability data, and
 * renders gracefully when that field is absent (pre-rollout state).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---- Module mocks (top-level for Vitest hoisting) ---------------------------

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/recapture",
  useSearchParams: () => new URLSearchParams(),
}));

const mockGetRecaptureAuditReadiness = vi.fn();

vi.mock("@/lib/api", () => ({
  getRecaptureAuditReadiness: mockGetRecaptureAuditReadiness,
}));

// ---- Fixtures ----------------------------------------------------------------

const baseAuditResponse = {
  audit_ready_pct: 88.0,
  total_gaps: 36,
  with_evidence: 32,
  dual_signed: 28,
  missing_meat: [],
};

const irrKappaPayload = {
  method: "cohens_kappa",
  kappa: 0.5238,
  kappa_n: 20,
  agreement_pct: 52.38,
  band: "acceptable" as const,
  secondary_approved: 16,
  secondary_rejected: 4,
  pending_review: 0,
  note: "20 dual-coded gaps",
};

const irrProportionPayload = {
  method: "proportion_agreement",
  kappa: null,
  kappa_n: null,
  agreement_pct: 75.0,
  band: "acceptable" as const,
  secondary_approved: 12,
  secondary_rejected: 4,
  pending_review: 2,
  note: "proportion agreement only",
};

// ---- Helper ------------------------------------------------------------------

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

// ---- Tests -------------------------------------------------------------------

let AuditReadinessCard: React.FC;

beforeEach(async () => {
  vi.clearAllMocks();
  const mod = await import("@/components/AuditReadinessCard");
  AuditReadinessCard = mod.AuditReadinessCard;
});

describe("AuditReadinessCard — Cohen's kappa IRR tile", () => {
  it("renders kappa value 0.52 and 'Moderate' band label when method=cohens_kappa", async () => {
    mockGetRecaptureAuditReadiness.mockResolvedValue({
      ...baseAuditResponse,
      inter_rater_reliability: irrKappaPayload,
    });

    render(<AuditReadinessCard />, { wrapper: makeWrapper() });

    // Kappa value rendered to 2 decimal places
    const kappaEl = await screen.findByTestId("irr-kappa-value");
    expect(kappaEl.textContent).toBe("0.52");

    // Band label for "acceptable" maps to "Moderate"
    const bandEl = screen.getByTestId("irr-band-label");
    expect(bandEl.textContent).toBe("Moderate");

    // IRR tile container visible
    expect(screen.getByTestId("irr-tile")).toBeInTheDocument();

    // Proportion-fallback path must not be present when kappa is available
    expect(screen.queryByTestId("irr-agreement-value")).toBeNull();
  });

  it("renders agreement_pct only when method=proportion_agreement (no kappa field)", async () => {
    mockGetRecaptureAuditReadiness.mockResolvedValue({
      ...baseAuditResponse,
      inter_rater_reliability: irrProportionPayload,
    });

    render(<AuditReadinessCard />, { wrapper: makeWrapper() });

    const agreementEl = await screen.findByTestId("irr-agreement-value");
    expect(agreementEl.textContent).toBe("75.0%");

    // Kappa-specific element must not appear
    expect(screen.queryByTestId("irr-kappa-value")).toBeNull();
  });

  it("omits IRR tile entirely when inter_rater_reliability is null (pre-rollout)", async () => {
    mockGetRecaptureAuditReadiness.mockResolvedValue({
      ...baseAuditResponse,
      inter_rater_reliability: null,
    });

    render(<AuditReadinessCard />, { wrapper: makeWrapper() });

    // Gauge still renders
    await waitFor(() => {
      expect(screen.getByText("88.0%")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("irr-tile")).toBeNull();
    expect(screen.queryByTestId("irr-kappa-value")).toBeNull();
  });

  it("omits IRR tile when inter_rater_reliability is absent from payload", async () => {
    mockGetRecaptureAuditReadiness.mockResolvedValue({
      ...baseAuditResponse,
      // inter_rater_reliability intentionally omitted
    });

    render(<AuditReadinessCard />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(screen.getByText("88.0%")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("irr-tile")).toBeNull();
  });

  it("still renders breakdown stats alongside the kappa tile", async () => {
    mockGetRecaptureAuditReadiness.mockResolvedValue({
      ...baseAuditResponse,
      inter_rater_reliability: irrKappaPayload,
    });

    render(<AuditReadinessCard />, { wrapper: makeWrapper() });

    await screen.findByTestId("irr-kappa-value");

    expect(screen.getByText("36")).toBeInTheDocument(); // total_gaps
    expect(screen.getByText("32")).toBeInTheDocument(); // with_evidence
    expect(screen.getByText("28")).toBeInTheDocument(); // dual_signed
  });
});

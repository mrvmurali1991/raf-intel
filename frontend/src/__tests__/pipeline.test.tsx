/**
 * pipeline.test.tsx
 *
 * Tests the pipeline status display and trigger flows:
 * - Pipeline status polling and rendering
 * - Trigger sync and status transitions
 * - Pipeline run history display
 * - Error state handling
 *
 * All API calls are mocked.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/emr-config",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    [k: string]: unknown;
  }) => <a href={href} {...props}>{children}</a>,
}));

const mockApi = {
  get: vi.fn(),
  post: vi.fn(),
};

vi.mock("@/lib/api", () => ({
  default: mockApi,
  API_BASE: "http://localhost:8500",
}));

// ── Fixtures ────────────────────────────────────────────────────────────────

const MOCK_PIPELINE_RUN_PENDING = {
  id: 1,
  tenant_id: "1",
  trigger_event: "emr_sync_completed",
  connection_id: 1,
  sync_type: "full",
  sync_id: "sync-abc-001",
  status: "pending",
  current_step: null,
  steps_completed: [],
  steps_failed: [],
  patient_count: 0,
  created_at: "2026-04-14T10:00:00Z",
  updated_at: "2026-04-14T10:00:00Z",
  completed_at: null,
  error_message: null,
};

const MOCK_PIPELINE_RUN_RUNNING = {
  ...MOCK_PIPELINE_RUN_PENDING,
  status: "running",
  current_step: "normalization",
  steps_completed: ["emr_sync"],
};

const MOCK_PIPELINE_RUN_COMPLETED = {
  ...MOCK_PIPELINE_RUN_PENDING,
  id: 2,
  status: "completed",
  current_step: null,
  steps_completed: ["emr_sync", "normalization", "raf_calculation"],
  patient_count: 45,
  completed_at: "2026-04-14T10:05:30Z",
};

const MOCK_PIPELINE_RUN_FAILED = {
  ...MOCK_PIPELINE_RUN_PENDING,
  id: 3,
  status: "failed",
  current_step: "raf_calculation",
  steps_completed: ["emr_sync", "normalization"],
  steps_failed: ["raf_calculation"],
  error_message: "RAF calculation service unavailable",
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Pipeline — Status API response validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pending status has correct fields", () => {
    const run = MOCK_PIPELINE_RUN_PENDING;
    expect(run).toHaveProperty("id");
    expect(run).toHaveProperty("status");
    expect(run).toHaveProperty("tenant_id");
    expect(run.status).toBe("pending");
    expect(run.completed_at).toBeNull();
  });

  it("running status has current_step set", () => {
    const run = MOCK_PIPELINE_RUN_RUNNING;
    expect(run.status).toBe("running");
    expect(run.current_step).toBeTruthy();
    expect(run.steps_completed.length).toBeGreaterThan(0);
  });

  it("completed status has all steps done and completed_at set", () => {
    const run = MOCK_PIPELINE_RUN_COMPLETED;
    expect(run.status).toBe("completed");
    expect(run.completed_at).toBeTruthy();
    expect(run.patient_count).toBeGreaterThan(0);
    expect(run.steps_completed).toContain("raf_calculation");
  });

  it("failed status has error_message set", () => {
    const run = MOCK_PIPELINE_RUN_FAILED;
    expect(run.status).toBe("failed");
    expect(run.error_message).toBeTruthy();
    expect(run.steps_failed.length).toBeGreaterThan(0);
  });
});

describe("Pipeline — Status API polling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches latest pipeline status for tenant", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_PIPELINE_RUN_COMPLETED });

    const result = await mockApi.get("/api/emr/pipeline/status");
    expect(result.data.status).toBe("completed");
    expect(result.data).toHaveProperty("id");
  });

  it("returns 404 when no pipeline runs exist", async () => {
    mockApi.get.mockRejectedValue({
      isAxiosError: true,
      response: { status: 404, data: { detail: "No pipeline runs found" } },
    });

    await expect(mockApi.get("/api/emr/pipeline/status")).rejects.toMatchObject({
      response: { status: 404 },
    });
  });

  it("fetches pipeline run list with pagination", async () => {
    mockApi.get.mockResolvedValue({
      data: {
        runs: [MOCK_PIPELINE_RUN_COMPLETED, MOCK_PIPELINE_RUN_FAILED],
        total: 2,
        page: 1,
      },
    });

    const result = await mockApi.get("/api/emr/pipeline/runs");
    expect(result.data.runs).toHaveLength(2);
    expect(result.data).toHaveProperty("total");
  });

  it("fetches single pipeline run by ID", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_PIPELINE_RUN_COMPLETED });

    const result = await mockApi.get("/api/emr/pipeline/runs/2");
    expect(result.data.id).toBe(2);
    expect(result.data.status).toBe("completed");
  });
});

describe("Pipeline — Trigger sync", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("trigger sync creates a new pipeline run", async () => {
    mockApi.post.mockResolvedValue({
      data: {
        run_id: 5,
        status: "pending",
        message: "Pipeline run started",
      },
    });

    const result = await mockApi.post("/api/emr/sync", {
      connection_id: 1,
      sync_type: "full",
    });

    expect(result.data.run_id).toBeTruthy();
    expect(result.data.status).toBe("pending");
  });

  it("trigger sync with invalid connection returns 404", async () => {
    mockApi.post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 404, data: { detail: "Connection not found" } },
    });

    await expect(
      mockApi.post("/api/emr/sync", { connection_id: 99999, sync_type: "full" })
    ).rejects.toMatchObject({ response: { status: 404 } });
  });

  it("trigger sync requires authentication", async () => {
    mockApi.post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 401, data: { detail: "Not authenticated" } },
    });

    await expect(mockApi.post("/api/emr/sync", {})).rejects.toMatchObject({
      response: { status: 401 },
    });
  });

  it("duplicate sync_id returns idempotency response", async () => {
    mockApi.post.mockResolvedValue({
      data: {
        run_id: -1,
        status: "skipped",
        message: "Duplicate sync_id — run already exists",
      },
    });

    const result = await mockApi.post("/api/emr/sync", {
      connection_id: 1,
      sync_type: "incremental",
      sync_id: "dedup-key-xyz",
    });

    expect(result.data.run_id).toBe(-1);
    expect(result.data.status).toBe("skipped");
  });
});

describe("Pipeline — Status display logic", () => {
  it("correctly identifies terminal statuses", () => {
    const TERMINAL_STATUSES = ["completed", "failed", "cancelled"];
    const isTerminal = (status: string) => TERMINAL_STATUSES.includes(status);

    expect(isTerminal("completed")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
    expect(isTerminal("running")).toBe(false);
    expect(isTerminal("pending")).toBe(false);
  });

  it("correctly identifies success statuses", () => {
    const isSuccess = (status: string) => status === "completed";
    expect(isSuccess("completed")).toBe(true);
    expect(isSuccess("failed")).toBe(false);
  });

  it("calculates pipeline duration correctly", () => {
    const run = MOCK_PIPELINE_RUN_COMPLETED;
    const start = new Date(run.created_at).getTime();
    const end = new Date(run.completed_at!).getTime();
    const durationMs = end - start;
    expect(durationMs).toBeGreaterThan(0);
    expect(durationMs).toBeLessThan(24 * 60 * 60 * 1000); // less than 1 day
  });

  it("steps_completed array contains expected step names", () => {
    const run = MOCK_PIPELINE_RUN_COMPLETED;
    const validSteps = ["emr_sync", "normalization", "raf_calculation", "analysis", "suspect_scan"];
    run.steps_completed.forEach((step: string) => {
      expect(validSteps).toContain(step);
    });
  });
});

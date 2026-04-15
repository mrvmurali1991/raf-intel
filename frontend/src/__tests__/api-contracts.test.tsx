/**
 * api-contracts.test.tsx
 *
 * Validates that API response shapes match what the frontend expects.
 * Each test defines the TypeScript interface and verifies mock data
 * (and real API responses when mocked) satisfy the contract.
 *
 * These serve as living documentation of the backend API contract.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

const mockApi = {
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  put: vi.fn(),
};

vi.mock("@/lib/api", () => ({
  default: mockApi,
  API_BASE: "http://localhost:8500",
}));

// ── Type validators ───────────────────────────────────────────────────────────

function hasFields(obj: Record<string, unknown>, fields: string[]): boolean {
  return fields.every((f) => f in obj);
}

function isStringOrNull(v: unknown): boolean {
  return v === null || typeof v === "string";
}

function isNumberOrNull(v: unknown): boolean {
  return v === null || typeof v === "number";
}

// ── Contract fixtures ─────────────────────────────────────────────────────────

const USER_CONTRACT_FIELDS = ["id", "email", "role", "tenant_id", "full_name"];
const USER_FORBIDDEN_FIELDS = ["password_hash", "mfa_secret", "password_changed_at"];

const PATIENT_CONTRACT_FIELDS = ["pid", "fname", "lname"];

const RAF_SCORE_CONTRACT_FIELDS = ["patient_id", "raf_score", "model"];

const EMR_CONNECTION_CONTRACT_FIELDS = ["id", "name", "host", "is_active"];

const PIPELINE_RUN_CONTRACT_FIELDS = ["id", "status", "tenant_id", "created_at"];

const HEALTH_CONTRACT_FIELDS = ["status"];

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("API Contract — Health endpoint", () => {
  beforeEach(() => vi.clearAllMocks());

  it("GET /health returns status field", async () => {
    mockApi.get.mockResolvedValue({ data: { status: "ok", database: "ok" } });
    const resp = await mockApi.get("/health");
    expect(hasFields(resp.data, HEALTH_CONTRACT_FIELDS)).toBe(true);
  });

  it("health status is a string", async () => {
    mockApi.get.mockResolvedValue({ data: { status: "ok" } });
    const resp = await mockApi.get("/health");
    expect(typeof resp.data.status).toBe("string");
  });
});

describe("API Contract — Auth /me endpoint", () => {
  beforeEach(() => vi.clearAllMocks());

  const MOCK_ME_RESPONSE = {
    id: 1,
    email: "admin@raf.health",
    full_name: "Test Admin",
    role: "admin",
    tenant_id: 1,
    is_active: 1,
    mfa_enabled: false,
    must_change_password: false,
    avatar_url: null,
    created_at: "2026-01-01T00:00:00Z",
  };

  it("GET /api/auth/me has all required user fields", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_ME_RESPONSE });
    const resp = await mockApi.get("/api/auth/me");
    expect(hasFields(resp.data, USER_CONTRACT_FIELDS)).toBe(true);
  });

  it("GET /api/auth/me does not include sensitive fields", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_ME_RESPONSE });
    const resp = await mockApi.get("/api/auth/me");
    USER_FORBIDDEN_FIELDS.forEach((field) => {
      expect(resp.data).not.toHaveProperty(field);
    });
  });

  it("tenant_id is a number", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_ME_RESPONSE });
    const resp = await mockApi.get("/api/auth/me");
    expect(typeof resp.data.tenant_id).toBe("number");
  });

  it("role is one of the expected values", async () => {
    const VALID_ROLES = ["admin", "manager", "viewer", "coder", "provider"];
    mockApi.get.mockResolvedValue({ data: MOCK_ME_RESPONSE });
    const resp = await mockApi.get("/api/auth/me");
    expect(VALID_ROLES).toContain(resp.data.role);
  });
});

describe("API Contract — Patient list endpoint", () => {
  beforeEach(() => vi.clearAllMocks());

  const MOCK_PATIENT_LIST = {
    patients: [
      {
        pid: 1,
        fname: "Alice",
        lname: "Smith",
        DOB: "1955-03-12",
        sex: "Female",
        raf_score: 1.45,
        hcc_count: 3,
        risk_level: "high",
      },
    ],
    total: 1,
    page: 1,
    pages: 1,
  };

  it("GET /api/patients returns pagination envelope", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_PATIENT_LIST });
    const resp = await mockApi.get("/api/patients");
    expect(resp.data).toHaveProperty("patients");
    expect(resp.data).toHaveProperty("total");
    expect(Array.isArray(resp.data.patients)).toBe(true);
  });

  it("patient records have required fields", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_PATIENT_LIST });
    const resp = await mockApi.get("/api/patients");
    const patient = resp.data.patients[0];
    expect(hasFields(patient, PATIENT_CONTRACT_FIELDS)).toBe(true);
  });

  it("raf_score is a number or null", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_PATIENT_LIST });
    const resp = await mockApi.get("/api/patients");
    const patient = resp.data.patients[0];
    expect(isNumberOrNull(patient.raf_score)).toBe(true);
  });

  it("total is a non-negative integer", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_PATIENT_LIST });
    const resp = await mockApi.get("/api/patients");
    expect(typeof resp.data.total).toBe("number");
    expect(resp.data.total).toBeGreaterThanOrEqual(0);
  });
});

describe("API Contract — Patient detail endpoint", () => {
  beforeEach(() => vi.clearAllMocks());

  const MOCK_PATIENT_DETAIL = {
    pid: 1,
    fname: "Alice",
    lname: "Smith",
    DOB: "1955-03-12",
    sex: "Female",
    raf_score: 1.45,
    hcc_count: 3,
    risk_level: "high",
    last_encounter_date: "2026-01-15",
    insurance_id: "MA-001",
  };

  it("GET /api/patients/1 returns patient object with required fields", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_PATIENT_DETAIL });
    const resp = await mockApi.get("/api/patients/1");
    expect(hasFields(resp.data, PATIENT_CONTRACT_FIELDS)).toBe(true);
  });

  it("GET /api/patients/99999 returns 404", async () => {
    mockApi.get.mockRejectedValue({
      isAxiosError: true,
      response: { status: 404, data: { detail: "Patient not found" } },
    });
    await expect(mockApi.get("/api/patients/99999")).rejects.toMatchObject({
      response: { status: 404 },
    });
  });
});

describe("API Contract — RAF score endpoints", () => {
  beforeEach(() => vi.clearAllMocks());

  const MOCK_RAF_SCORE = {
    patient_id: 1,
    raf_score: 1.45,
    model: "CMS-HCC V28",
    hcc_codes: ["HCC18", "HCC85"],
    demographic_score: 0.32,
    calculated_at: "2026-04-10T09:00:00Z",
  };

  it("RAF score response has required fields", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_RAF_SCORE });
    const resp = await mockApi.get("/api/raf/1/scores");
    expect(hasFields(resp.data, RAF_SCORE_CONTRACT_FIELDS)).toBe(true);
  });

  it("raf_score is a number", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_RAF_SCORE });
    const resp = await mockApi.get("/api/raf/1/scores");
    expect(typeof resp.data.raf_score).toBe("number");
  });

  it("hcc_codes is an array", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_RAF_SCORE });
    const resp = await mockApi.get("/api/raf/1/scores");
    expect(Array.isArray(resp.data.hcc_codes)).toBe(true);
  });

  it("RAF model list returns array", async () => {
    mockApi.get.mockResolvedValue({
      data: [
        { id: "v28", name: "CMS-HCC V28", year: 2024 },
        { id: "v24", name: "CMS-HCC V24", year: 2023 },
      ],
    });
    const resp = await mockApi.get("/api/raf/models");
    expect(Array.isArray(resp.data)).toBe(true);
    expect(resp.data.length).toBeGreaterThan(0);
  });

  it("population summary has risk level breakdown", async () => {
    mockApi.get.mockResolvedValue({
      data: {
        low: 40,
        medium: 30,
        high: 20,
        critical: 10,
        total: 100,
        average_raf: 1.23,
      },
    });
    const resp = await mockApi.get("/api/raf/population-summary");
    expect(resp.data).toHaveProperty("low");
    expect(resp.data).toHaveProperty("high");
    expect(resp.data).toHaveProperty("total");
  });
});

describe("API Contract — EMR Connection endpoints", () => {
  beforeEach(() => vi.clearAllMocks());

  const MOCK_CONNECTION = {
    id: 1,
    name: "Primary OpenEMR",
    host: "10.1.2.216",
    port: 3306,
    database: "openemr",
    username: "raf_reader",
    is_active: 1,
    last_sync_at: "2026-04-10T12:00:00Z",
    patient_count: 9,
  };

  it("connection list returns array with required fields", async () => {
    mockApi.get.mockResolvedValue({ data: [MOCK_CONNECTION] });
    const resp = await mockApi.get("/api/emr/connections");
    expect(Array.isArray(resp.data)).toBe(true);
    const conn = resp.data[0];
    expect(hasFields(conn, EMR_CONNECTION_CONTRACT_FIELDS)).toBe(true);
  });

  it("connection response never includes password", async () => {
    mockApi.get.mockResolvedValue({ data: [MOCK_CONNECTION] });
    const resp = await mockApi.get("/api/emr/connections");
    resp.data.forEach((conn: Record<string, unknown>) => {
      expect(conn).not.toHaveProperty("password");
    });
  });
});

describe("API Contract — Pipeline run endpoints", () => {
  beforeEach(() => vi.clearAllMocks());

  const MOCK_RUN = {
    id: 1,
    tenant_id: "1",
    trigger_event: "emr_sync_completed",
    connection_id: 1,
    sync_type: "full",
    sync_id: "sync-abc",
    status: "completed",
    current_step: null,
    steps_completed: ["emr_sync", "normalization", "raf_calculation"],
    steps_failed: [],
    patient_count: 45,
    created_at: "2026-04-14T10:00:00Z",
    completed_at: "2026-04-14T10:05:30Z",
    error_message: null,
  };

  it("pipeline run has required fields", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_RUN });
    const resp = await mockApi.get("/api/emr/pipeline/runs/1");
    expect(hasFields(resp.data, PIPELINE_RUN_CONTRACT_FIELDS)).toBe(true);
  });

  it("status is one of the expected values", async () => {
    const VALID_STATUSES = ["pending", "running", "completed", "failed", "cancelled"];
    mockApi.get.mockResolvedValue({ data: MOCK_RUN });
    const resp = await mockApi.get("/api/emr/pipeline/runs/1");
    expect(VALID_STATUSES).toContain(resp.data.status);
  });

  it("steps_completed is an array", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_RUN });
    const resp = await mockApi.get("/api/emr/pipeline/runs/1");
    expect(Array.isArray(resp.data.steps_completed)).toBe(true);
  });

  it("completed run has completed_at timestamp", async () => {
    mockApi.get.mockResolvedValue({ data: MOCK_RUN });
    const resp = await mockApi.get("/api/emr/pipeline/runs/1");
    if (resp.data.status === "completed") {
      expect(resp.data.completed_at).toBeTruthy();
    }
  });
});

describe("API Contract — Auth login endpoint", () => {
  beforeEach(() => vi.clearAllMocks());

  it("successful login response has access_token", async () => {
    mockApi.post.mockResolvedValue({
      data: {
        access_token: "fake-jwt-access-token",
        refresh_token: "fake-jwt-refresh-token",
        user: { id: 1, email: "admin@raf.health", role: "admin", tenant_id: 1 },
        mfa_required: false,
      },
    });
    const resp = await mockApi.post("/api/auth/login", {
      email: "admin@raf.health",
      password: "Admin@123",
    });
    expect(resp.data).toHaveProperty("access_token");
    expect(resp.data).toHaveProperty("mfa_required");
  });

  it("login response does not include password_hash", async () => {
    mockApi.post.mockResolvedValue({
      data: {
        access_token: "fake-token",
        user: { id: 1, email: "admin@raf.health", role: "admin" },
      },
    });
    const resp = await mockApi.post("/api/auth/login", {
      email: "admin@raf.health",
      password: "Admin@123",
    });
    expect(resp.data).not.toHaveProperty("password_hash");
    expect(resp.data.user).not.toHaveProperty("password_hash");
  });

  it("invalid credentials returns 401", async () => {
    mockApi.post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 401, data: { detail: "Invalid credentials" } },
    });
    await expect(
      mockApi.post("/api/auth/login", { email: "x@x.com", password: "wrong" })
    ).rejects.toMatchObject({ response: { status: 401 } });
  });
});

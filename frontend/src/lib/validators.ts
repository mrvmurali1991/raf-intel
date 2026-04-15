/**
 * lib/validators.ts
 *
 * Zod schemas for form validation across the application.
 * Import individual schemas where needed; never duplicate validation logic.
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------

export const loginSchema = z.object({
  email: z
    .string()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  password: z
    .string()
    .min(1, "Password is required"),
});

export type LoginFormData = z.infer<typeof loginSchema>;

// ---------------------------------------------------------------------------
// EMR Connection
// ---------------------------------------------------------------------------

export const emrConnectionSchema = z.object({
  name: z
    .string()
    .min(1, "Connection name is required")
    .max(100, "Name must be 100 characters or fewer"),
  vendor: z.string().min(1, "Vendor is required"),
  connection_type: z.enum(["fhir_r4", "rest_api"], {
    error: "Connection type is required",
  }),
  fhir_base_url: z
    .string()
    .url("Enter a valid URL")
    .optional()
    .or(z.literal("")),
  auth_type: z
    .enum(["none", "basic", "bearer", "oauth2", "api_key"])
    .default("oauth2"),
  client_id: z.string().optional(),
  client_secret: z.string().optional(),
  token_url: z
    .string()
    .url("Enter a valid token URL")
    .optional()
    .or(z.literal("")),
  scope: z.string().optional(),
  api_base_url: z
    .string()
    .url("Enter a valid API URL")
    .optional()
    .or(z.literal("")),
  username: z.string().optional(),
  password: z.string().optional(),
}).superRefine((data, ctx) => {
  if (data.connection_type === "fhir_r4" && !data.fhir_base_url) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "FHIR base URL is required for FHIR R4 connections",
      path: ["fhir_base_url"],
    });
  }
  if (data.connection_type === "rest_api" && !data.api_base_url) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "API base URL is required for REST API connections",
      path: ["api_base_url"],
    });
  }
  if (data.auth_type === "oauth2") {
    if (!data.client_id) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Client ID is required for OAuth2",
        path: ["client_id"],
      });
    }
    if (!data.client_secret) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Client secret is required for OAuth2",
        path: ["client_secret"],
      });
    }
  }
});

export type EmrConnectionFormData = z.infer<typeof emrConnectionSchema>;

// ---------------------------------------------------------------------------
// Patient search
// ---------------------------------------------------------------------------

export const patientSearchSchema = z.object({
  query: z
    .string()
    .min(2, "Enter at least 2 characters to search")
    .max(200, "Search query is too long"),
  filters: z
    .object({
      risk_level: z.enum(["all", "low", "medium", "high"]).optional(),
      provider_id: z.string().optional(),
      has_suspects: z.boolean().optional(),
    })
    .optional(),
});

export type PatientSearchData = z.infer<typeof patientSearchSchema>;

// ---------------------------------------------------------------------------
// User create / update
// ---------------------------------------------------------------------------

const userRoles = ["admin", "manager", "clinician", "coder", "auditor", "viewer"] as const;

export const userCreateSchema = z.object({
  email: z
    .string()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  first_name: z
    .string()
    .min(1, "First name is required")
    .max(50, "First name must be 50 characters or fewer"),
  last_name: z
    .string()
    .min(1, "Last name is required")
    .max(50, "Last name must be 50 characters or fewer"),
  role: z.enum(userRoles, { error: "Role is required" }),
  password: z
    .string()
    .min(12, "Password must be at least 12 characters")
    .regex(/[A-Z]/, "Password must contain an uppercase letter")
    .regex(/[a-z]/, "Password must contain a lowercase letter")
    .regex(/[0-9]/, "Password must contain a number"),
  title: z.string().max(100).optional(),
  npi: z
    .string()
    .regex(/^\d{10}$/, "NPI must be exactly 10 digits")
    .optional()
    .or(z.literal("")),
});

export type UserCreateData = z.infer<typeof userCreateSchema>;

export const userUpdateSchema = userCreateSchema
  .omit({ password: true })
  .extend({
    password: z
      .string()
      .min(12, "Password must be at least 12 characters")
      .regex(/[A-Z]/, "Password must contain an uppercase letter")
      .regex(/[a-z]/, "Password must contain a lowercase letter")
      .regex(/[0-9]/, "Password must contain a number")
      .optional()
      .or(z.literal("")),
  });

export type UserUpdateData = z.infer<typeof userUpdateSchema>;

// ---------------------------------------------------------------------------
// Forgot / Reset password
// ---------------------------------------------------------------------------

export const forgotPasswordSchema = z.object({
  email: z
    .string()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
});

export const resetPasswordSchema = z
  .object({
    new_password: z
      .string()
      .min(12, "Password must be at least 12 characters"),
    confirm_password: z.string(),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });

// ---------------------------------------------------------------------------
// MFA code
// ---------------------------------------------------------------------------

export const mfaCodeSchema = z.object({
  code: z
    .string()
    .regex(/^\d{6}$/, "Enter the 6-digit code from your authenticator app"),
});

export const mfaRecoverySchema = z.object({
  code: z.string().min(1, "Recovery code is required"),
});

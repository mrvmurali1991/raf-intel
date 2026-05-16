"use server";

/**
 * Server Actions for /settings — foundation for future migration.
 *
 * Pattern: forward cookies to /api/auth/refresh to obtain a fresh access
 * token server-side, then call the backend with Bearer auth.  This avoids
 * exposing the in-memory access token (which only lives in the browser) to
 * the server layer.
 *
 * TODO(migration): Once all settings mutations are converted, remove the
 * legacy axios paths in ProfileSection and call only this action.
 */

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8500";

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export interface UpdateProfileState {
  status: "idle" | "success" | "error";
  message: string;
}

// ---------------------------------------------------------------------------
// Helper: exchange the httpOnly refresh-token cookie for a fresh access token.
// The browser's httpOnly cookie is readable server-side via next/headers.
// ---------------------------------------------------------------------------

async function getServerAccessToken(): Promise<string> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");

  const res = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    headers: {
      Cookie: cookieHeader,
      "Content-Type": "application/json",
    },
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error("Session expired — please sign in again.");
  }

  const data = (await res.json()) as { access_token: string };
  return data.access_token;
}

// ---------------------------------------------------------------------------
// updateProfile — Server Action for profile name / title / avatar update.
//
// Preferred path: called via useActionState + <form action={updateProfile}>.
// Fallback path:  the existing authApi.put("/api/auth/me") in ProfileSection
//                 remains in place and is used for instant optimistic updates.
// ---------------------------------------------------------------------------

export async function updateProfile(
  _prev: UpdateProfileState,
  formData: FormData,
): Promise<UpdateProfileState> {
  // --- validate ---
  const firstName = (formData.get("first_name") as string | null)?.trim() ?? "";
  const lastName = (formData.get("last_name") as string | null)?.trim() ?? "";
  const title = (formData.get("title") as string | null)?.trim() ?? "";
  const avatarUrl = (formData.get("avatar_url") as string | null)?.trim() ?? "";

  if (!firstName || !lastName) {
    return { status: "error", message: "First name and last name are required." };
  }

  // --- get fresh token server-side ---
  let accessToken: string;
  try {
    accessToken = await getServerAccessToken();
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Authentication failed.";
    return { status: "error", message };
  }

  // --- call backend ---
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      first_name: firstName,
      last_name: lastName,
      title,
      avatar_url: avatarUrl,
    }),
    cache: "no-store",
  });

  if (!res.ok) {
    let detail = "Failed to update profile.";
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore parse error
    }
    return { status: "error", message: detail };
  }

  revalidatePath("/settings");

  return { status: "success", message: "Profile updated successfully." };
}

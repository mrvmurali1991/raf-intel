import { cookies, headers } from "next/headers";
import { AdminDashboard } from "@/components/dashboards/AdminDashboard";
import { CoderDashboard } from "@/components/dashboards/CoderDashboard";
import { ProviderDashboard } from "@/components/dashboards/ProviderDashboard";
import { AIHealthBanner } from "@/components/AIHealthBanner";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8500";

/** Resolve the current user's role by forwarding cookies to the backend. */
async function getRole(): Promise<string | null> {
  const cookieStore = await cookies();
  const isAuthed = cookieStore.get("raf_authenticated")?.value === "true";
  if (!isAuthed) return null;

  // Forward all cookies so the backend can read the httpOnly refresh token.
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");

  try {
    // Step 1: exchange refresh token for a new access token.
    const refreshRes = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: { Cookie: cookieHeader },
      cache: "no-store",
    });
    if (!refreshRes.ok) return null;
    const { access_token } = (await refreshRes.json()) as {
      access_token?: string;
    };
    if (!access_token) return null;

    // Step 2: fetch user info.
    const meRes = await fetch(`${API_BASE}/api/auth/me`, {
      headers: {
        Authorization: `Bearer ${access_token}`,
        Cookie: cookieHeader,
      },
      cache: "no-store",
    });
    if (!meRes.ok) return null;
    const user = (await meRes.json()) as { role?: string };
    return user.role ?? null;
  } catch {
    return null;
  }
}

export default async function DashboardOrchestrator() {
  const role = await getRole();

  let Dashboard: React.ComponentType;
  if (role === "provider" || role === "clinician") {
    Dashboard = ProviderDashboard;
  } else if (role === "coder") {
    Dashboard = CoderDashboard;
  } else {
    // admin, manager, auditor, AND unknown/null (SSR-cookie race) all land here.
    // AdminDashboard is the full Population Health Intelligence view — the safe
    // default when role detection fails (middleware redirects unauthenticated users
    // before this code runs, so a null role here means SSR couldn't read cookies).
    Dashboard = AdminDashboard;
  }

  return (
    <>
      <AIHealthBanner />
      <Dashboard />
    </>
  );
}

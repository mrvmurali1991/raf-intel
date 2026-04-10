"use client";

/**
 * ProtectedRoute — thin pass-through wrapper (kept for backward compatibility).
 *
 * Authentication in this app is enforced in TWO places, NOT here:
 *   1. Next.js middleware (frontend/middleware.ts → src/proxy.ts), which runs
 *      on every request and handles server-side redirects for unauthenticated
 *      users.
 *   2. <AuthLayout> (src/components/auth-layout.tsx), which is mounted once in
 *      the root layout and gates all client-rendered pages behind the auth
 *      context — redirecting to /login when the session is missing and showing
 *      a full-page spinner while the auth state bootstraps.
 *
 * Because those two layers already cover every protected page, this component
 * no longer performs any auth checks of its own. It is retained as a simple
 * pass-through so that existing imports (<ProtectedRoute>...</ProtectedRoute>)
 * continue to compile. New code should NOT use this wrapper — rely on
 * AuthLayout + middleware instead.
 */

interface ProtectedRouteProps {
  children: React.ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  // Intentionally a no-op wrapper. See file-level docstring above — the real
  // auth gates live in middleware.ts and AuthLayout.
  return <>{children}</>;
}

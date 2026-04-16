"use client";

/**
 * auth-context.tsx
 *
 * Owns the entire authentication lifecycle:
 *   - Access token in memory (_accessToken module variable)
 *   - Refresh token in sessionStorage (cleared on tab close)
 *   - Lightweight boolean cookie for Next.js middleware SSR guard
 *   - Axios interceptors on BOTH authApi and lib/api's default instance
 *   - Interval-based silent token refresh (2 min before expiry)
 *   - 15-min idle timeout with activity tracking
 *   - MFA two-step flow via completeMfaVerify
 *   - must_change_password enforcement
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  ReactNode,
} from "react";
import axios from "axios";
import { useRouter } from "next/navigation";
import api, { registerAuthInterceptors, type AuthInterceptorHandles } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Decoded JWT payload fields accessed by this module. */
interface JwtPayload {
  /** Unix timestamp (seconds) when the token expires. */
  exp: number;
  /** Subject — typically the user id. */
  sub?: string;
  tenant_id?: string;
  role?: string;
  /** Allow additional standard JWT claims without widening to `any`. */
  iat?: number;
  iss?: string;
  aud?: string | string[];
}

export interface User {
  id: string | number;
  email: string;
  full_name?: string;
  first_name?: string;
  last_name?: string;
  role: string;
  tenant_id?: string;
  avatar_url?: string;
  npi?: string;
  title?: string;
  permissions?: string[];
  mfa_enabled?: boolean;
  must_change_password?: boolean;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  mustChangePassword: boolean;
  login: (email: string, password: string) => Promise<LoginResult>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<void>;
  updateProfile: (
    data: Partial<Pick<User, "first_name" | "last_name" | "title" | "avatar_url">>
  ) => Promise<void>;
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>;
  completeMfaVerify: (mfaToken: string, code: string, isRecovery?: boolean) => Promise<void>;
  clearMustChangePassword: () => void;
  switchTenant: (tenantId: string) => Promise<void>;
  /** The axios instance pre-configured for auth endpoints. */
  authApi: typeof authApi;
}

/** Returned by login() so the caller knows whether MFA is required next. */
export interface LoginResult {
  mfa_required: boolean;
  mfa_token?: string;
}

// ---------------------------------------------------------------------------
// authApi — dedicated axios instance for /api/auth/* calls.
// Auth-route calls use this directly so they are never caught by the 401
import { API_BASE } from "@/lib/api";

// retry interceptor (which would create an infinite loop on /api/auth/refresh).
// ---------------------------------------------------------------------------

export const authApi = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
  withCredentials: true,
});

// Attach Bearer token to authApi requests as well (needed for /api/auth/me,
// /api/auth/change-password, /api/auth/logout, /api/auth/mfa/*).
// We use a module-level interceptor here (not ejected) — it reads the live
// _accessToken value at call time.
authApi.interceptors.request.use((config) => {
  if (_accessToken) {
    config.headers["Authorization"] = `Bearer ${_accessToken}`;
  }
  return config;
});

// ---------------------------------------------------------------------------
// In-memory access token (module-level — survives re-renders, cleared on tab close)
// ---------------------------------------------------------------------------

// In-memory only — never persisted to sessionStorage
let _accessToken: string | null = null;

export function getAccessToken(): string | null {
  return _accessToken;
}

function setAccessToken(token: string | null) {
  _accessToken = token;
  // Set default Authorization header on BOTH api instances directly
  // so requests made BEFORE the interceptor registers still have the token
  if (token) {
    api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
    authApi.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  } else {
    delete api.defaults.headers.common["Authorization"];
    delete authApi.defaults.headers.common["Authorization"];
  }
}

// ---------------------------------------------------------------------------
// Refresh token — httpOnly cookie set by the backend
// The browser automatically sends this cookie with requests to /api/auth/refresh.
// JavaScript cannot read or modify it, eliminating XSS theft of the refresh token.
// ---------------------------------------------------------------------------

// Legacy cleanup: remove any refresh token accidentally stored in browser storage
if (typeof window !== "undefined") {
  sessionStorage.removeItem("raf_refresh_token");
  localStorage.removeItem("raf_refresh_token");
}

// ---------------------------------------------------------------------------
// Proxy auth cookie
// Non-sensitive boolean flag read by src/proxy.ts to guard SSR routes.
// Contains zero token data — the actual JWT is validated by the backend.
// ---------------------------------------------------------------------------

function setAuthCookie() {
  if (typeof document === "undefined") return;
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `raf_authenticated=true; path=/; SameSite=Strict; Max-Age=28800${secure}`;
}

function clearAuthCookie() {
  if (typeof document === "undefined") return;
  document.cookie =
    "raf_authenticated=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Strict";
}

// ---------------------------------------------------------------------------
// Idle timeout
// ---------------------------------------------------------------------------

const IDLE_TIMEOUT_MS = 15 * 60 * 1_000; // 15 minutes
const IDLE_CHECK_INTERVAL_MS = 30_000; // check every 30 s

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AuthContext = createContext<AuthContextType | undefined>(undefined);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [mustChangePassword, setMustChangePassword] = useState(false);

  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastActivityRef = useRef(Date.now());
  // Holds eject handles for the interceptors registered on lib/api's instance.
  const apiInterceptorHandlesRef = useRef<AuthInterceptorHandles | null>(null);

  const router = useRouter();

  // -------------------------------------------------------------------------
  // JWT helpers
  // -------------------------------------------------------------------------

  function parseJwtPayload(token: string): JwtPayload | null {
    try {
      const base64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(atob(base64)) as JwtPayload;
    } catch {
      return null;
    }
  }

  // -------------------------------------------------------------------------
  // Token refresh scheduling
  // -------------------------------------------------------------------------

  /** Schedule a silent refresh 2 minutes before the access token expires. */
  function scheduleRefresh(accessToken: string) {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    const payload = parseJwtPayload(accessToken);
    if (!payload || typeof payload.exp !== "number") return;
    const expiresInMs = payload.exp * 1_000 - Date.now();
    const refreshInMs = Math.max(expiresInMs - 2 * 60 * 1_000, 0);
    refreshTimerRef.current = setTimeout(async () => {
      try {
        await doRefresh();
      } catch {
        // Refresh failed — the response interceptor on lib/api will handle
        // any subsequent 401 and call performLogout if needed.
      }
    }, refreshInMs);
  }

  /**
   * Core refresh logic.
   * The refresh token is sent automatically by the browser as an httpOnly cookie.
   * Uses authApi directly (bypasses the lib/api 401 interceptor) to avoid
   * infinite retry loops if the refresh endpoint itself returns 401.
   */
  async function doRefresh(): Promise<string> {
    const { data } = await authApi.post<{
      access_token: string;
      refresh_token?: string;
    }>("/api/auth/refresh");

    setAccessToken(data.access_token);
    scheduleRefresh(data.access_token);
    return data.access_token;
  }

  // -------------------------------------------------------------------------
  // Shared logout helper (no navigation — callers decide where to go)
  // -------------------------------------------------------------------------

  const isLoggingInRef = useRef(false);

  function performLogout() {
    // Don't clear tokens if we're in the middle of logging in
    if (isLoggingInRef.current) return;
    setAccessToken(null);
    setUser(null);
    setMustChangePassword(false);
    clearAuthCookie();
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }

  // -------------------------------------------------------------------------
  // Register auth interceptors on lib/api's instance
  //
  // We do this synchronously (not inside an async dynamic import) so that
  // the token is attached to the very first API call made after mount.
  // The cleanup function returned by useEffect properly ejects interceptors,
  // which matters for React Strict Mode (double-mount) and HMR.
  // -------------------------------------------------------------------------

  useEffect(() => {
    const handles = registerAuthInterceptors(
      // Token getter — reads the live module variable synchronously
      () => _accessToken,
      // Refresh callback — called by the 401 interceptor before retrying
      doRefresh,
      // Logout callback — called when refresh itself fails
      // Only logout if we're not already on the login page
      () => {
        if (typeof window !== "undefined" && window.location.pathname === "/login") return;
        performLogout();
        router.push("/login?reason=session_expired");
      }
    );

    apiInterceptorHandlesRef.current = handles;

    return () => {
      handles.ejectRequest();
      handles.ejectResponse();
      apiInterceptorHandlesRef.current = null;
    };
     
  }, []);

  // -------------------------------------------------------------------------
  // Idle timeout tracking
  // -------------------------------------------------------------------------

  useEffect(() => {
    const activityEvents = ["mousedown", "keydown", "scroll", "touchstart", "mousemove"];

    const resetTimer = () => {
      lastActivityRef.current = Date.now();
    };

    activityEvents.forEach((e) =>
      window.addEventListener(e, resetTimer, { passive: true })
    );

    const idleCheck = setInterval(() => {
      if (user && Date.now() - lastActivityRef.current > IDLE_TIMEOUT_MS) {
        performLogout();
        router.push("/login?reason=idle");
      }
    }, IDLE_CHECK_INTERVAL_MS);

    return () => {
      activityEvents.forEach((e) => window.removeEventListener(e, resetTimer));
      clearInterval(idleCheck);
    };
     
  }, [user]);

  // -------------------------------------------------------------------------
  // Session boot — restore session from stored refresh token on first mount
  // -------------------------------------------------------------------------

  useEffect(() => {
    async function init() {
      // 1. Try the access token first (stored in sessionStorage)
      const existingToken = getAccessToken();
      if (existingToken) {
        try {
          const { data } = await authApi.get<User>("/api/auth/me", {
            headers: { Authorization: `Bearer ${existingToken}` },
          });
          setUser(data);
          setAuthCookie();
          scheduleRefresh(existingToken);
          setIsLoading(false);
          return;
        } catch {
          // Access token expired — fall through to refresh
          setAccessToken(null);
        }
      }

      // 2. Try refresh (browser sends httpOnly cookie automatically)
      try {
        const newAccessToken = await doRefresh();
        const { data } = await authApi.get<User>("/api/auth/me", {
          headers: { Authorization: `Bearer ${newAccessToken}` },
        });
        setUser(data);
        setAuthCookie();
      } catch {
        // Only wipe the cookie when we're not in the middle of a login flow
        // and the cookie hasn't been set by a concurrent login() call.
        // Without this guard the init() refresh attempt (which races with a
        // just-completed login) would immediately clear the cookie that
        // login() just set, causing the middleware to redirect back to /login.
        const alreadyAuthed =
          typeof document !== "undefined" &&
          document.cookie.includes("raf_authenticated=true");
        if (!isLoggingInRef.current && !alreadyAuthed) {
          setAccessToken(null);
          clearAuthCookie();
        }
      } finally {
        setIsLoading(false);
      }
    }

    init();
     
  }, []);

  // -------------------------------------------------------------------------
  // Cleanup refresh timer on unmount
  // -------------------------------------------------------------------------

  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  // -------------------------------------------------------------------------
  // Public auth actions
  // -------------------------------------------------------------------------

  const login = useCallback(
    async (email: string, password: string): Promise<LoginResult> => {
      isLoggingInRef.current = true;
      try {
        const { data } = await authApi.post<{
          access_token?: string;
          refresh_token?: string;
          user?: User;
          mfa_required?: boolean;
          mfa_token?: string;
          must_change_password?: boolean;
        }>("/api/auth/login", { email, password });

        // MFA required — return early; the login page will present the MFA form.
        if (data.mfa_required) {
          return { mfa_required: true, mfa_token: data.mfa_token };
        }

        if (!data.access_token || !data.user) {
          throw new Error("Unexpected login response from server.");
        }

        setAccessToken(data.access_token);
        scheduleRefresh(data.access_token);
        setUser(data.user);
        setAuthCookie();

        if (data.must_change_password) {
          setMustChangePassword(true);
        }

        return { mfa_required: false };
      } finally {
        isLoggingInRef.current = false;
      }
    },
     
    []
  );

  /**
   * Finalise the session after a successful MFA challenge.
   * Pass isRecovery=true when the user entered a backup recovery code.
   */
  const completeMfaVerify = useCallback(
    async (mfaToken: string, code: string, isRecovery = false) => {
      const endpoint = isRecovery
        ? "/api/auth/mfa/verify-recovery"
        : "/api/auth/mfa/verify";

      const { data } = await authApi.post<{
        access_token: string;
        refresh_token?: string;
        user: User;
        must_change_password?: boolean;
      }>(endpoint, { mfa_token: mfaToken, code });

      setAccessToken(data.access_token);
      scheduleRefresh(data.access_token);
      setUser(data.user);
      setAuthCookie();

      if (data.must_change_password) {
        setMustChangePassword(true);
      }
    },
     
    []
  );

  const logout = useCallback(async () => {
    try {
      // Best-effort server-side token invalidation
      // The browser automatically sends the httpOnly refresh token cookie
      await authApi.post("/api/auth/logout");
    } catch {
      // Always clear local state even if the network call fails
    }
    performLogout();
    router.push("/login");
     
  }, [router]);

  const refreshToken = useCallback(async () => {
    await doRefresh();
     
  }, []);

  const updateProfile = useCallback(
    async (
      data: Partial<Pick<User, "first_name" | "last_name" | "title" | "avatar_url">>
    ) => {
      const { data: updated } = await authApi.put<User>("/api/auth/me", data);
      setUser(updated);
    },
    []
  );

  const changePassword = useCallback(
    async (oldPassword: string, newPassword: string) => {
      await authApi.put("/api/auth/change-password", {
        old_password: oldPassword,
        new_password: newPassword,
      });
      setMustChangePassword(false);
    },
    []
  );

  const clearMustChangePassword = useCallback(() => {
    setMustChangePassword(false);
  }, []);

  const switchTenant = useCallback(async (tenantId: string) => {
    const { data } = await authApi.post<{
      access_token: string;
      tenant_id: string;
    }>("/api/auth/switch-tenant", { tenant_id: tenantId });
    setAccessToken(data.access_token);
    scheduleRefresh(data.access_token);
    // Update user with new tenant_id
    setUser((prev) => prev ? { ...prev, tenant_id: data.tenant_id } : prev);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        mustChangePassword,
        login,
        logout,
        refreshToken,
        updateProfile,
        changePassword,
        completeMfaVerify,
        clearMustChangePassword,
        switchTenant,
        authApi,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

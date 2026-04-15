/**
 * login.test.tsx
 * Tests login form validation, submission, and error display.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mocks ────────────────────────────────────────────────────────────────────

const mockPush = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  usePathname: () => "/login",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [k: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock("@/components/ui/tooltip", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const mockLogin = vi.fn();
vi.mock("@/contexts/auth-context", () => ({
  useAuth: () => ({
    login: mockLogin,
    isAuthenticated: false,
    isLoading: false,
  }),
  authApi: {
    post: vi.fn().mockResolvedValue({ data: {} }),
    get: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

// ── Helpers ──────────────────────────────────────────────────────────────────

function getEmailField() {
  return document.getElementById("email") as HTMLInputElement;
}

function getPasswordField() {
  return document.getElementById("password") as HTMLInputElement;
}

async function renderLogin() {
  const { default: LoginPage } = await import("@/app/login/page");
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LoginPage />
    </QueryClientProvider>
  );
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders email and password fields", async () => {
    await renderLogin();
    expect(getEmailField()).toBeInTheDocument();
    expect(getPasswordField()).toBeInTheDocument();
  });

  it("shows validation error for empty email", async () => {
    await renderLogin();
    const user = userEvent.setup();
    const submitBtn = screen.getByRole("button", { name: /secure sign in/i });
    await user.click(submitBtn);
    await waitFor(() => {
      expect(screen.getByText(/email is required/i)).toBeInTheDocument();
    });
    expect(mockLogin).not.toHaveBeenCalled();
  });

  it("shows validation error for invalid email format", async () => {
    await renderLogin();
    const user = userEvent.setup();
    await user.type(getEmailField(), "notanemail");
    await user.type(getPasswordField(), "somepassword");
    await user.click(screen.getByRole("button", { name: /secure sign in/i }));
    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    });
    expect(mockLogin).not.toHaveBeenCalled();
  });

  it("calls login on valid submission", async () => {
    mockLogin.mockResolvedValue({});
    await renderLogin();
    const user = userEvent.setup();
    await user.type(getEmailField(), "admin@raf.health");
    await user.type(getPasswordField(), "Admin@123");
    await user.click(screen.getByRole("button", { name: /secure sign in/i }));
    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith("admin@raf.health", "Admin@123");
    });
  });

  it("displays API error on login failure", async () => {
    mockLogin.mockRejectedValue({
      response: { data: { detail: "Invalid credentials" }, status: 401 },
    });
    await renderLogin();
    const user = userEvent.setup();
    await user.type(getEmailField(), "admin@raf.health");
    await user.type(getPasswordField(), "wrongpassword");
    await user.click(screen.getByRole("button", { name: /secure sign in/i }));
    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });

  it("toggles password visibility", async () => {
    await renderLogin();
    const user = userEvent.setup();
    const pwField = getPasswordField();
    expect(pwField).toHaveAttribute("type", "password");
    // Find the toggle button near the password field
    const toggleBtn = screen.getAllByLabelText(/show password/i)[0];
    await user.click(toggleBtn);
    expect(pwField).toHaveAttribute("type", "text");
  });
});

"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw, Copy, Check, LogIn, WifiOff, ServerCrash } from "lucide-react";
import { Button } from "@/components/ui/button";
import logger from "@/lib/logger";

/* ------------------------------------------------------------------ */
/*  Error classification                                               */
/* ------------------------------------------------------------------ */

type ErrorCategory = "network" | "auth" | "server" | "generic";

function classifyError(error: Error): ErrorCategory {
  const msg = error.message?.toLowerCase() ?? "";
  const name = error.name?.toLowerCase() ?? "";

  // Network / fetch failures
  if (
    name === "typeerror" && msg.includes("fetch") ||
    msg.includes("network") ||
    msg.includes("failed to fetch") ||
    msg.includes("networkerror") ||
    msg.includes("unable to reach") ||
    msg.includes("err_connection") ||
    msg.includes("econnrefused")
  ) {
    return "network";
  }

  // HTTP status codes embedded in error messages
  if (msg.includes("401") || msg.includes("403") || msg.includes("unauthorized") || msg.includes("forbidden")) {
    return "auth";
  }
  if (msg.includes("500") || msg.includes("internal server error")) {
    return "server";
  }

  return "generic";
}

const ERROR_CONFIG: Record<
  ErrorCategory,
  { title: string; message: string; icon: typeof AlertTriangle }
> = {
  network: {
    title: "Connection Problem",
    message: "Unable to reach the server. Check your connection and try again.",
    icon: WifiOff,
  },
  auth: {
    title: "Session Expired",
    message: "Your session may have expired. Please log in again.",
    icon: LogIn,
  },
  server: {
    title: "Server Error",
    message: "Something went wrong on our end. Our team has been notified.",
    icon: ServerCrash,
  },
  generic: {
    title: "Something Went Wrong",
    message: "An unexpected error occurred.",
    icon: AlertTriangle,
  },
};

/* ------------------------------------------------------------------ */
/*  Props / State                                                      */
/* ------------------------------------------------------------------ */

interface Props {
  children: ReactNode;
  /** Override the heading shown in the error UI */
  fallbackTitle?: string;
  /** Completely replace the error UI */
  fallback?: ReactNode;
  /** Called before the boundary resets — use to refetch data */
  onReset?: () => void;
  /** When true the "Copy error details" button is shown */
  isAdmin?: boolean;
}

interface State {
  hasError: boolean;
  error: Error | null;
  copied: boolean;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, copied: false };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    logger.error("ErrorBoundary", "Uncaught error in component tree", {
      error: error.message,
      stack: error.stack,
      componentStack: info.componentStack,
    });
  }

  /* ----- actions ----- */

  handleRetry = () => {
    this.props.onReset?.();
    this.setState({ hasError: false, error: null, copied: false });
  };

  handleCopyDetails = async () => {
    const { error } = this.state;
    if (!error) return;
    const details = [
      `Error: ${error.name}: ${error.message}`,
      "",
      error.stack ?? "(no stack trace)",
    ].join("\n");
    try {
      await navigator.clipboard.writeText(details);
      this.setState({ copied: true });
      setTimeout(() => this.setState({ copied: false }), 2000);
    } catch {
      // clipboard API may be blocked
    }
  };

  /* ----- render ----- */

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const category = this.state.error
        ? classifyError(this.state.error)
        : "generic";
      const config = ERROR_CONFIG[category];
      const Icon = config.icon;

      return (
        <div
          role="alert"
          aria-live="assertive"
          className="flex flex-col items-center justify-center gap-4 py-20 text-center animate-in fade-in duration-500"
        >
          <div className="rounded-2xl bg-destructive/10 p-5">
            <Icon className="h-10 w-10 text-destructive" />
          </div>

          <h2 className="text-xl font-bold tracking-tight">
            {this.props.fallbackTitle || config.title}
          </h2>

          <p className="max-w-md text-sm text-muted-foreground">
            {config.message}
          </p>

          {process.env.NODE_ENV === "development" && this.state.error && (
            <pre className="max-w-lg overflow-auto rounded-lg bg-muted p-3 text-left text-xs text-muted-foreground">
              {this.state.error.message}
            </pre>
          )}

          <div className="flex gap-3">
            {category === "auth" ? (
              <Button
                onClick={() => {
                  window.location.href = "/login";
                }}
                variant="default"
                className="gap-2"
              >
                <LogIn className="h-4 w-4" />
                Log In
              </Button>
            ) : (
              <Button onClick={this.handleRetry} variant="default" className="gap-2">
                <RefreshCw className="h-4 w-4" />
                Try Again
              </Button>
            )}
            <Button
              onClick={() => window.location.reload()}
              variant="outline"
            >
              Reload Page
            </Button>
            {this.props.isAdmin && this.state.error && (
              <Button
                onClick={this.handleCopyDetails}
                variant="ghost"
                className="gap-2"
              >
                {this.state.copied ? (
                  <Check className="h-4 w-4" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
                {this.state.copied ? "Copied" : "Copy error details"}
              </Button>
            )}
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;

"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import logger from "@/lib/logger";

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    logger.error("ErrorBoundary", "Uncaught error in component tree", {
      error: error.message,
      stack: error.stack,
      componentStack: info.componentStack,
    });
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center gap-4 py-20 text-center animate-in fade-in duration-500">
          <div className="rounded-2xl bg-destructive/10 p-5">
            <AlertTriangle className="h-10 w-10 text-destructive" />
          </div>
          <h2 className="text-xl font-bold tracking-tight">
            {this.props.fallbackTitle || "Something went wrong"}
          </h2>
          <p className="max-w-md text-sm text-muted-foreground">
            An unexpected error occurred. Please try again or refresh the page.
          </p>
          {process.env.NODE_ENV === "development" && this.state.error && (
            <pre className="max-w-lg overflow-auto rounded-lg bg-muted p-3 text-left text-xs text-muted-foreground">
              {this.state.error.message}
            </pre>
          )}
          <div className="flex gap-3">
            <Button onClick={this.handleRetry} variant="default" className="gap-2">
              <RefreshCw className="h-4 w-4" />
              Try Again
            </Button>
            <Button
              onClick={() => window.location.reload()}
              variant="outline"
            >
              Reload Page
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

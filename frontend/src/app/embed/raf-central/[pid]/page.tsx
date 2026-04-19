"use client";

/**
 * /embed/raf-central/[pid]
 *
 * Iframe-only route consumed by OpenEMR's chart sidebar. The host plugin
 * mints a short-lived HMAC-signed JWT (shared secret: OPENEMR_EMBED_SECRET
 * on the backend, mirrored in the PHP plugin) and hands it to this page as
 * a `t` query parameter:
 *
 *   https://raf.example.com/embed/raf-central/12345?t=<embed_token>
 *
 * On mount the page calls `POST /api/auth/embed/exchange` exactly once,
 * which trades the embed JWT for a real RAF access + refresh token pair
 * scoped to the tenant. After that, every inline action inside
 * RAFCentralPanel goes through the authenticated axios instance exactly
 * like it does in the main app — no special-casing required.
 *
 * Failure modes:
 *   - missing `t` param              → "Missing embed token"
 *   - expired / tampered token       → "Session could not be established"
 *   - upstream server error          → generic "Try again" message
 *
 * Nothing on this page is clickable or selectable outside the panel — the
 * goal is for the iframe to visually blend into the OpenEMR chart.
 */

import { use, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2, AlertTriangle } from "lucide-react";
import { useAuth } from "@/contexts/auth-context";
import { RAFCentralPanel } from "@/components/RAFCentralPanel";

type HandshakeState =
  | { kind: "pending" }
  | { kind: "ready" }
  | { kind: "error"; message: string };

export default function RafCentralEmbedPage({
  params,
}: {
  params: Promise<{ pid: string }>;
}) {
  const { pid } = use(params);
  const searchParams = useSearchParams();
  const { isAuthenticated, completeEmbedExchange } = useAuth();
  const [state, setState] = useState<HandshakeState>({ kind: "pending" });
  // React Strict Mode double-invokes effects; guard so the one-shot token
  // exchange only runs once.
  const didExchangeRef = useRef(false);

  useEffect(() => {
    if (didExchangeRef.current) return;
    didExchangeRef.current = true;

    // If the iframe is reopened and we already have a session, skip the
    // exchange entirely.
    if (isAuthenticated) {
      setState({ kind: "ready" });
      return;
    }

    const token = searchParams.get("t");
    if (!token) {
      setState({
        kind: "error",
        message:
          "Missing embed token. OpenEMR must launch this panel with a signed token.",
      });
      return;
    }

    completeEmbedExchange(token)
      .then(() => setState({ kind: "ready" }))
      .catch((err: unknown) => {
        const msg =
          err instanceof Error
            ? err.message
            : "Session could not be established.";
        setState({ kind: "error", message: msg });
      });
  }, [searchParams, isAuthenticated, completeEmbedExchange]);

  if (state.kind === "pending") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background p-6 text-sm text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
        Connecting to RAF Central…
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background p-6 text-center text-sm">
        <AlertTriangle className="h-8 w-8 text-amber-500" />
        <div className="font-medium text-foreground">{state.message}</div>
        <div className="text-xs text-muted-foreground">
          Reload the OpenEMR patient chart to retry.
        </div>
      </div>
    );
  }

  // Fully authenticated — render the same panel that the main app uses,
  // with `embedded` styling so it fills the iframe edge-to-edge.
  return (
    <div className="min-h-screen bg-background p-3">
      <RAFCentralPanel patientId={Number(pid)} embedded />
    </div>
  );
}

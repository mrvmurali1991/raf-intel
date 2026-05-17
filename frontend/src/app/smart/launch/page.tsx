"use client";

/**
 * SMART on FHIR launch page (client component).
 *
 * Entry point for EHR-launch flows. The EHR redirects the user's browser
 * to this page with `iss` (FHIR base URL) and `launch` (opaque token)
 * query parameters; we generate a PKCE pair, discover the EHR's authorize
 * endpoint via its `/.well-known/smart-configuration`, and redirect.
 *
 * Spec: https://hl7.org/fhir/smart-app-launch/STU2.2/
 */

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

// ---------------------------------------------------------------------------
// PKCE helpers (browser-only — uses Web Crypto)
// ---------------------------------------------------------------------------

function base64UrlEncode(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function generatePkcePair(): Promise<{ verifier: string; challenge: string }> {
  const verifier = base64UrlEncode(crypto.getRandomValues(new Uint8Array(32)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: base64UrlEncode(digest) };
}

// ---------------------------------------------------------------------------
// Configuration (override via env at build time)
// ---------------------------------------------------------------------------

const CLIENT_ID =
  process.env.NEXT_PUBLIC_SMART_CLIENT_ID || "raf-intelligence";

const DEFAULT_SCOPE =
  process.env.NEXT_PUBLIC_SMART_SCOPE ||
  [
    "openid",
    "fhirUser",
    "launch",
    "launch/patient",
    "patient/Patient.read",
    "patient/Condition.read",
    "patient/Condition.write",
  ].join(" ");

function getRedirectUri(): string {
  if (typeof window === "undefined") return "";
  const fromEnv = process.env.NEXT_PUBLIC_SMART_REDIRECT_URI;
  if (fromEnv) return fromEnv;
  return `${window.location.origin}/smart/callback`;
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function SmartLaunchPage() {
  const params = useSearchParams();
  const [status, setStatus] = useState<"working" | "error">("working");
  const [message, setMessage] = useState("Preparing SMART on FHIR launch…");
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const iss = params?.get("iss") ?? "";
    const launch = params?.get("launch") ?? "";

    (async () => {
      try {
        const { verifier, challenge } = await generatePkcePair();
        const state = base64UrlEncode(crypto.getRandomValues(new Uint8Array(16)));
        sessionStorage.setItem("smart_code_verifier", verifier);
        sessionStorage.setItem("smart_state", state);
        sessionStorage.setItem("smart_iss", iss);

        const redirectUri = getRedirectUri();
        const qs = new URLSearchParams({
          response_type: "code",
          client_id: CLIENT_ID,
          redirect_uri: redirectUri,
          scope: DEFAULT_SCOPE,
          state,
          aud: iss,
          code_challenge: challenge,
          code_challenge_method: "S256",
        });
        if (launch) qs.set("launch", launch);

        // Discover the EHR's authorize endpoint.
        let authorizeEndpoint = `${iss}/authorize`;
        if (iss) {
          setMessage(`Discovering SMART configuration at ${iss}…`);
          try {
            const cfgRes = await fetch(
              `${iss.replace(/\/$/, "")}/.well-known/smart-configuration`,
              { credentials: "omit" },
            );
            if (cfgRes.ok) {
              const cfg = await cfgRes.json();
              if (cfg.authorization_endpoint) {
                authorizeEndpoint = String(cfg.authorization_endpoint);
              }
            }
          } catch {
            // Discovery failure — fall back to <iss>/authorize.
          }
        } else {
          // Standalone launch — talk to this server's own SMART endpoints.
          authorizeEndpoint = `${window.location.origin}/smart/authorize`;
        }

        setMessage("Redirecting to the EHR for authorization…");
        window.location.replace(`${authorizeEndpoint}?${qs.toString()}`);
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        setStatus("error");
        setMessage(`SMART launch failed: ${detail}`);
      }
    })();
  }, [params]);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0f172a",
        color: "#e2e8f0",
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
        padding: "24px",
      }}
    >
      <section
        role="status"
        aria-live="polite"
        style={{
          background: "#1e293b",
          padding: "32px 40px",
          borderRadius: 12,
          maxWidth: 520,
          width: "100%",
          textAlign: "center",
          boxShadow: "0 10px 30px rgba(0,0,0,0.4)",
        }}
      >
        <h1 style={{ marginTop: 0, color: "#38bdf8", fontSize: "1.25rem" }}>
          Launching RAF Intelligence
        </h1>
        {status === "working" ? (
          <>
            <div
              aria-hidden="true"
              style={{
                width: 28,
                height: 28,
                border: "3px solid #334155",
                borderTopColor: "#38bdf8",
                borderRadius: "50%",
                margin: "20px auto",
                animation: "smart-spin 1s linear infinite",
              }}
            />
            <p style={{ marginBottom: 0 }}>{message}</p>
            <style>{`@keyframes smart-spin { to { transform: rotate(360deg); } }`}</style>
          </>
        ) : (
          <p style={{ color: "#fca5a5", marginBottom: 0 }}>{message}</p>
        )}
        <noscript>
          <p>JavaScript is required to complete the SMART launch.</p>
        </noscript>
      </section>
    </main>
  );
}

"use client";

import { useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import api from "@/lib/api";

export default function OAuth2CallbackPage() {
  const params = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("Exchanging authorization code…");

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state");
    const error = params.get("error");

    if (error) {
      setStatus("error");
      setMessage(`Authorization denied: ${error} — ${params.get("error_description") || ""}`);
      return;
    }

    if (!code || !state) {
      setStatus("error");
      setMessage("Missing code or state parameter in callback URL.");
      return;
    }

    api
      .post("/api/emr/connections/oauth2/callback", { code, state })
      .then((res) => {
        setStatus("success");
        setMessage(res.data.message || "Authorization successful! Tokens stored.");
        // Redirect back after a short delay
        setTimeout(() => router.push("/emr-config"), 2000);
      })
      .catch((err) => {
        setStatus("error");
        const detail = err.response?.data?.detail || err.message || "Token exchange failed";
        setMessage(String(detail));
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  /* eslint-enable react-hooks/set-state-in-effect */

  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "60vh" }}>
      <div style={{
        maxWidth: 440, width: "100%", padding: 32, borderRadius: 12,
        background: "#fff", boxShadow: "0 2px 12px rgba(0,0,0,0.08)", textAlign: "center",
      }}>
        {status === "loading" && (
          <>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
            <div style={{ fontSize: 15, color: "#475569" }}>{message}</div>
          </>
        )}
        {status === "success" && (
          <>
            <div style={{ fontSize: 32, marginBottom: 12 }}>✅</div>
            <div style={{ fontSize: 15, color: "#16a34a", fontWeight: 600 }}>{message}</div>
            <div style={{ fontSize: 13, color: "#64748b", marginTop: 8 }}>Redirecting to EMR Config…</div>
          </>
        )}
        {status === "error" && (
          <>
            <div style={{ fontSize: 32, marginBottom: 12 }}>❌</div>
            <div style={{ fontSize: 15, color: "#dc2626", fontWeight: 600 }}>{message}</div>
            <button
              onClick={() => router.push("/emr-config")}
              style={{
                marginTop: 16, padding: "8px 20px", borderRadius: 6, border: "none",
                background: "#2563eb", color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer",
              }}
            >
              Back to EMR Config
            </button>
          </>
        )}
      </div>
    </div>
  );
}

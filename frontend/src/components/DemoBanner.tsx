"use client";

/**
 * DemoBanner — Persistent banner shown when the app is in demo mode.
 * Displayed at the top of the main content area with a link to connect a real EMR.
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import Link from "next/link";
import { AlertCircle, X, Database } from "lucide-react";
import { getEmrStatus } from "@/lib/api";

export function DemoBanner() {
  const [dismissed, setDismissed] = useState(false);

  const { data: status } = useQuery({
    queryKey: ["emr-status"],
    queryFn: getEmrStatus,
    refetchInterval: 60_000,
    retry: 1,
  });

  // Show only when connected AND in demo mode
  const isDemo = (status as any)?.is_demo === true;

  if (!isDemo || dismissed) return null;

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        background: "linear-gradient(90deg, #FEF3C7 0%, #FFF7ED 100%)",
        border: "1px solid #FED7AA",
        borderRadius: 10,
        padding: "10px 18px",
        marginBottom: 16,
        fontSize: 13,
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#92400E" }}>
        <AlertCircle size={16} />
        <span>
          <strong>Demo Mode</strong> — You are viewing sample data.{" "}
          <Link href="/emr-config" style={{ color: "#D97706", fontWeight: 600, textDecoration: "underline" }}>
            Connect your EMR
          </Link>{" "}
          to see real patient data.
        </span>
      </div>
      <button
        onClick={() => setDismissed(true)}
        style={{ background: "none", border: "none", cursor: "pointer", color: "#A16207", padding: 4 }}
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}

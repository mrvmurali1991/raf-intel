"use client";

import React, { useState, useEffect } from "react";
import type { AuditPackagesResponse } from "@/lib/api";
import { downloadAuditPackage } from "@/lib/api";
import {
  EmptyState,
} from "@/components/healthcare-ui";
import {
  C,
  formatDate,
  Spinner,
  SectionLoader,
  Card,
} from "./shared";
import type { AuditPackageItem } from "./shared";

export function AuditTab({ audits, auditsLoading, auditMutation, selectedYear }: {
  audits: AuditPackagesResponse | undefined;
  auditsLoading: boolean;
  auditMutation: { mutate: (year?: number) => void; isPending: boolean };
  selectedYear: number;
}) {
  const [auditYear, setAuditYear] = useState(selectedYear);

  useEffect(() => { setAuditYear(selectedYear); }, [selectedYear]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Generate section */}
      <Card className="animate-slide-up stagger-1">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <h3 className="text-foreground" style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
              Audit Packages
            </h3>
            <p className="text-muted-foreground" style={{ margin: "4px 0 0", fontSize: 13 }}>
              Generate and download comprehensive audit documentation.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <select
              value={auditYear}
              onChange={(e) => setAuditYear(Number(e.target.value))}
              className="bg-card text-foreground border border-border"
              style={{
                padding: "8px 12px", borderRadius: 8, fontSize: 13, cursor: "pointer",
              }}
            >
              {[0, 1, 2, 3].map((offset) => {
                const y = new Date().getFullYear() - offset;
                return <option key={y} value={y}>{y}</option>;
              })}
            </select>
            <button
              onClick={() => auditMutation.mutate(auditYear)}
              disabled={auditMutation.isPending}
              className="bg-primary text-primary-foreground"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "8px 16px", borderRadius: 8, border: "none",
                fontSize: 13, fontWeight: 600,
                cursor: auditMutation.isPending ? "not-allowed" : "pointer",
                opacity: auditMutation.isPending ? 0.6 : 1,
              }}
            >
              {auditMutation.isPending && <Spinner size={14} />}
              Generate New Audit
            </button>
          </div>
        </div>
      </Card>

      {/* Audit list */}
      <Card noPadding className="animate-slide-up stagger-2">
        {auditsLoading ? (
          <SectionLoader label="Loading audit packages..." />
        ) : !audits?.packages?.length ? (
          <EmptyState
            title="No audit packages generated yet"
            description="Click Generate New Audit to create your first package"
            icon={
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
            }
          />
        ) : (
          <div>
            <div className="bg-muted border-b border-border" style={{
              display: "grid", gridTemplateColumns: "80px 80px 1fr 100px 100px",
              padding: "8px 20px",
              gap: 16,
            }}>
              {["Package", "Year", "Created", "Size", "Actions"].map((h) => (
                <span key={h} className="text-muted-foreground" style={{
                  fontSize: 11, fontWeight: 600, textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  textAlign: h === "Actions" ? "right" : "left",
                }}>
                  {h}
                </span>
              ))}
            </div>
            {audits.packages.map((pkg: AuditPackageItem) => (
              <div
                key={pkg.id}
                style={{
                  display: "grid", gridTemplateColumns: "80px 80px 1fr 100px 100px",
                  padding: "12px 20px", borderBottom: "1px solid var(--border)",
                  gap: 16, transition: "background 0.1s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = C.slate100)}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
<span className="text-foreground font-mono font-semibold text-sm">
                  #{pkg.id}
                </span>
<span className="text-sm text-muted-foreground">{pkg.year}</span>
                <span className="text-xs text-muted-foreground">{formatDate(pkg.created_at)}</span>
                <span className="text-xs text-muted-foreground">
                  {pkg.file_size_bytes ? `${(pkg.file_size_bytes / 1024).toFixed(1)} KB` : "\u2014"}
                </span>
                <span style={{ textAlign: "right" }}>
                  <button
                    type="button"
                    onClick={() =>
                      downloadAuditPackage(pkg.id).catch((err: unknown) => {
                        const e = err as { response?: { data?: { detail?: string } }; message?: string };
                        alert(e?.response?.data?.detail || e?.message || "Download failed");
                      })
                    }
                    className="text-primary"
                    style={{
                      display: "inline-flex", alignItems: "center", gap: 4,
                      fontSize: 12, fontWeight: 600,
                      background: "none", border: "none", padding: 0, cursor: "pointer",
                    }}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                    Download
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

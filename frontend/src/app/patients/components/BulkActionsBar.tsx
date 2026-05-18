"use client";

import { FocusTrap } from "@/components/ui/focus-trap";
import { tokens } from "@/styles/tokens";
import { C } from "@/lib/ui-utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EndpointStatus = "unknown" | "available" | "missing";

interface ReassignUser {
  id: number | string;
  full_name?: string;
  email?: string;
}

export interface BulkActionsBarProps {
  selectedCount: number;
  onClearSelection: () => void;

  // Request docs
  onRequestDocs: () => void;

  // Reassign
  reassignEndpointStatus: EndpointStatus;
  onOpenReassign: () => void;
  bulkReassignOpen: boolean;
  onCloseReassign: () => void;
  bulkReassignUsers: ReassignUser[] | null;
  bulkReassignUsersError: string | null;
  bulkReassignUserId: string;
  onReassignUserChange: (v: string) => void;
  bulkReassignSubmitting: boolean;
  onConfirmReassign: () => void;

  // Recalc
  recalcEndpointStatus: EndpointStatus;
  onOpenRecalc: () => void;
  bulkRecalcOpen: boolean;
  onCloseRecalc: () => void;
  bulkRecalcSubmitting: boolean;
  onConfirmRecalc: () => void;

  // Mark reviewed
  reviewedEndpointStatus: EndpointStatus;
  onOpenReviewed: () => void;
  bulkReviewedOpen: boolean;
  onCloseReviewed: () => void;
  bulkReviewedNote: string;
  onReviewedNoteChange: (v: string) => void;
  bulkReviewedSubmitting: boolean;
  onConfirmReviewed: () => void;

  // Request docs dialog
  bulkRequestOpen: boolean;
  onCloseRequestDocs: () => void;
  bulkRequestText: string;
  onRequestTextChange: (v: string) => void;
  bulkRequestSubmitting: boolean;
  onConfirmRequestDocs: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function BulkActionsBar({
  selectedCount,
  onClearSelection,
  onRequestDocs,
  reassignEndpointStatus,
  onOpenReassign,
  bulkReassignOpen,
  onCloseReassign,
  bulkReassignUsers,
  bulkReassignUsersError,
  bulkReassignUserId,
  onReassignUserChange,
  bulkReassignSubmitting,
  onConfirmReassign,
  recalcEndpointStatus,
  onOpenRecalc,
  bulkRecalcOpen,
  onCloseRecalc,
  bulkRecalcSubmitting,
  onConfirmRecalc,
  reviewedEndpointStatus,
  onOpenReviewed,
  bulkReviewedOpen,
  onCloseReviewed,
  bulkReviewedNote,
  onReviewedNoteChange,
  bulkReviewedSubmitting,
  onConfirmReviewed,
  bulkRequestOpen,
  onCloseRequestDocs,
  bulkRequestText,
  onRequestTextChange,
  bulkRequestSubmitting,
  onConfirmRequestDocs,
}: BulkActionsBarProps) {
  return (
    <>
      {/* Always-mounted aria-live region */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {selectedCount > 0
          ? `${selectedCount} patient${selectedCount === 1 ? "" : "s"} selected`
          : ""}
      </div>

      {selectedCount > 0 && (
        <div
          role="region"
          aria-label="Bulk actions"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            padding: "8px 16px",
            borderBottom: `1px solid ${C.borderSoft}`,
            background: C.brandSoft,
            fontSize: 13,
            fontWeight: 500,
            color: C.text,
          }}
        >
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: C.brand,
              color: tokens.white,
              borderRadius: 999,
              padding: "2px 10px",
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            {selectedCount} selected
          </span>
          <button
            type="button"
            onClick={onClearSelection}
            style={{
              padding: "4px 10px",
              borderRadius: 6,
              border: `1px solid ${C.border}`,
              background: tokens.white,
              color: C.text,
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Clear
          </button>
          <button
            type="button"
            onClick={onRequestDocs}
            style={{
              padding: "4px 12px",
              borderRadius: 6,
              border: `1px solid ${C.brand}`,
              background: C.brand,
              color: tokens.white,
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Bulk request docs
          </button>
          <button
            type="button"
            onClick={onOpenReassign}
            disabled={reassignEndpointStatus === "missing"}
            title={
              reassignEndpointStatus === "missing"
                ? "Endpoint not yet deployed"
                : "Reassign selected patients to another user"
            }
            style={{
              padding: "4px 12px",
              borderRadius: 6,
              border: `1px solid ${reassignEndpointStatus === "missing" ? C.border : C.brand}`,
              background:
                reassignEndpointStatus === "missing" ? tokens.slate100 : tokens.white,
              color:
                reassignEndpointStatus === "missing" ? tokens.slate400 : C.brand,
              fontSize: 12,
              fontWeight: 600,
              cursor:
                reassignEndpointStatus === "missing" ? "not-allowed" : "pointer",
            }}
          >
            Reassign
          </button>
          <button
            type="button"
            onClick={onOpenRecalc}
            disabled={recalcEndpointStatus === "missing"}
            title={
              recalcEndpointStatus === "missing"
                ? "Endpoint not yet deployed"
                : "Recalculate RAF scores for selected patients"
            }
            style={{
              padding: "4px 12px",
              borderRadius: 6,
              border: `1px solid ${recalcEndpointStatus === "missing" ? C.border : C.brand}`,
              background:
                recalcEndpointStatus === "missing" ? tokens.slate100 : tokens.white,
              color:
                recalcEndpointStatus === "missing" ? tokens.slate400 : C.brand,
              fontSize: 12,
              fontWeight: 600,
              cursor:
                recalcEndpointStatus === "missing" ? "not-allowed" : "pointer",
            }}
          >
            Recalc RAF
          </button>
          <button
            type="button"
            onClick={onOpenReviewed}
            disabled={reviewedEndpointStatus === "missing"}
            title={
              reviewedEndpointStatus === "missing"
                ? "Endpoint not yet deployed"
                : "Mark selected patients as reviewed with a note"
            }
            style={{
              padding: "4px 12px",
              borderRadius: 6,
              border: `1px solid ${reviewedEndpointStatus === "missing" ? C.border : C.brand}`,
              background:
                reviewedEndpointStatus === "missing" ? tokens.slate100 : tokens.white,
              color:
                reviewedEndpointStatus === "missing" ? tokens.slate400 : C.brand,
              fontSize: 12,
              fontWeight: 600,
              cursor:
                reviewedEndpointStatus === "missing" ? "not-allowed" : "pointer",
            }}
          >
            Mark reviewed
          </button>
          <span aria-hidden style={{ flex: 1, fontSize: 11, color: C.textMuted, fontStyle: "italic" }}>
            Hover any row to reveal selection checkboxes · Selection survives sort & filter changes
          </span>
        </div>
      )}

      {/* ---- Bulk request docs dialog ---- */}
      {bulkRequestOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Bulk request documentation"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 50,
            background: "rgba(0,0,0,0.75)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
          onClick={() => !bulkRequestSubmitting && onCloseRequestDocs()}
          onKeyDown={(e) => {
            if (e.key === "Escape" && !bulkRequestSubmitting) onCloseRequestDocs();
          }}
          tabIndex={-1}
        >
          <div
            style={{
              background: tokens.white,
              borderRadius: 10,
              boxShadow: "0 12px 40px rgba(15,23,42,0.25)",
              width: "100%",
              maxWidth: 480,
              padding: 20,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="m-0 text-base font-bold text-slate-900">
              Bulk request documentation
            </h3>
            <p className="mt-1.5 text-xs text-slate-600">
              Sends the same documentation request to{" "}
              <strong>{selectedCount}</strong> selected patient
              {selectedCount === 1 ? "" : "s"}.
            </p>
            <textarea
              value={bulkRequestText}
              onChange={(e) => onRequestTextChange(e.target.value)}
              placeholder="Describe the documentation needed"
              rows={4}
              autoFocus
              aria-label="Bulk documentation request"
              style={{
                width: "100%",
                marginTop: 12,
                resize: "none",
                borderRadius: 6,
                border: `1px solid ${C.border}`,
                padding: "8px 10px",
                fontSize: 13,
                fontFamily: "inherit",
              }}
            />
            <div style={{ marginTop: 6, fontSize: 11, color: C.textMuted }}>
              {bulkRequestText.trim().length < 10
                ? `${10 - bulkRequestText.trim().length} more character${
                    10 - bulkRequestText.trim().length === 1 ? "" : "s"
                  } required`
                : `Ready to fan out to ${selectedCount} patient${selectedCount === 1 ? "" : "s"}.`}
            </div>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button
                type="button"
                onClick={onCloseRequestDocs}
                disabled={bulkRequestSubmitting}
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: `1px solid ${C.border}`,
                  background: tokens.white,
                  color: C.text,
                  fontSize: 13,
                  cursor: bulkRequestSubmitting ? "not-allowed" : "pointer",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onConfirmRequestDocs}
                disabled={bulkRequestText.trim().length < 10 || bulkRequestSubmitting}
                style={{
                  padding: "6px 14px",
                  borderRadius: 6,
                  border: "none",
                  background:
                    bulkRequestText.trim().length < 10 || bulkRequestSubmitting
                      ? C.border
                      : C.brand,
                  color: tokens.white,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor:
                    bulkRequestText.trim().length < 10 || bulkRequestSubmitting
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                {bulkRequestSubmitting ? "Sending…" : `Send to ${selectedCount}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Bulk reassign dialog ---- */}
      {bulkReassignOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Bulk reassign patients"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 50,
            background: "rgba(0,0,0,0.75)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
          onClick={() => !bulkReassignSubmitting && onCloseReassign()}
          onKeyDown={(e) => {
            if (e.key === "Escape" && !bulkReassignSubmitting) onCloseReassign();
          }}
          tabIndex={-1}
        >
          <FocusTrap>
            <div
              style={{
                background: tokens.white,
                borderRadius: 10,
                boxShadow: "0 12px 40px rgba(15,23,42,0.25)",
                width: "100%",
                maxWidth: 480,
                padding: 20,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="m-0 text-base font-bold text-slate-900">
                Reassign selected patients
              </h3>
              <p className="mt-1.5 text-xs font-semibold text-amber-900">
                This will affect <strong>{selectedCount}</strong> patient
                {selectedCount === 1 ? "" : "s"}.
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Pick a reviewer below (or paste a user id).
              </p>
              {bulkReassignUsers && bulkReassignUsers.length > 0 ? (
                <select
                  value={bulkReassignUserId}
                  onChange={(e) => onReassignUserChange(e.target.value)}
                  aria-label="Reassign target user"
                  style={{
                    width: "100%",
                    marginTop: 12,
                    borderRadius: 6,
                    border: `1px solid ${C.border}`,
                    padding: "8px 10px",
                    fontSize: 13,
                    fontFamily: "inherit",
                    background: tokens.white,
                  }}
                >
                  <option value="">— Select a user —</option>
                  {bulkReassignUsers.map((u) => (
                    <option key={String(u.id)} value={String(u.id)}>
                      {u.full_name || u.email || `User ${u.id}`}
                      {u.email && u.full_name ? ` (${u.email})` : ""}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={bulkReassignUserId}
                  onChange={(e) => onReassignUserChange(e.target.value)}
                  placeholder={
                    bulkReassignUsersError
                      ? "Enter user id (user list unavailable)"
                      : "Enter user id"
                  }
                  aria-label="Reassign target user id"
                  autoFocus
                  style={{
                    width: "100%",
                    marginTop: 12,
                    borderRadius: 6,
                    border: `1px solid ${C.border}`,
                    padding: "8px 10px",
                    fontSize: 13,
                    fontFamily: "inherit",
                  }}
                />
              )}
              <div
                style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}
              >
                <button
                  type="button"
                  onClick={onCloseReassign}
                  disabled={bulkReassignSubmitting}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 6,
                    border: `1px solid ${C.border}`,
                    background: tokens.white,
                    color: C.text,
                    fontSize: 13,
                    cursor: bulkReassignSubmitting ? "not-allowed" : "pointer",
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={onConfirmReassign}
                  disabled={!bulkReassignUserId.trim() || bulkReassignSubmitting}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 6,
                    border: "none",
                    background:
                      !bulkReassignUserId.trim() || bulkReassignSubmitting
                        ? C.border
                        : C.brand,
                    color: tokens.white,
                    fontSize: 13,
                    fontWeight: 600,
                    cursor:
                      !bulkReassignUserId.trim() || bulkReassignSubmitting
                        ? "not-allowed"
                        : "pointer",
                  }}
                >
                  {bulkReassignSubmitting
                    ? "Reassigning…"
                    : `Confirm reassign (${selectedCount})`}
                </button>
              </div>
            </div>
          </FocusTrap>
        </div>
      )}

      {/* ---- Bulk recalc dialog ---- */}
      {bulkRecalcOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Bulk recalculate RAF"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 50,
            background: "rgba(0,0,0,0.75)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
          onClick={() => !bulkRecalcSubmitting && onCloseRecalc()}
          onKeyDown={(e) => {
            if (e.key === "Escape" && !bulkRecalcSubmitting) onCloseRecalc();
          }}
          tabIndex={-1}
        >
          <FocusTrap>
            <div
              style={{
                background: tokens.white,
                borderRadius: 10,
                boxShadow: "0 12px 40px rgba(15,23,42,0.25)",
                width: "100%",
                maxWidth: 460,
                padding: 20,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="m-0 text-base font-bold text-slate-900">
                Recalculate RAF scores
              </h3>
              <p className="mt-1.5 text-xs font-semibold text-amber-900">
                This will affect <strong>{selectedCount}</strong> patient
                {selectedCount === 1 ? "" : "s"}.
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Re-runs the CMS-HCC V28 model against the latest claims & encounter data.
                Existing scores will be overwritten.
              </p>
              <div
                style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}
              >
                <button
                  type="button"
                  onClick={onCloseRecalc}
                  disabled={bulkRecalcSubmitting}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 6,
                    border: `1px solid ${C.border}`,
                    background: tokens.white,
                    color: C.text,
                    fontSize: 13,
                    cursor: bulkRecalcSubmitting ? "not-allowed" : "pointer",
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={onConfirmRecalc}
                  disabled={bulkRecalcSubmitting}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 6,
                    border: "none",
                    background: bulkRecalcSubmitting ? C.border : C.brand,
                    color: tokens.white,
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: bulkRecalcSubmitting ? "not-allowed" : "pointer",
                  }}
                >
                  {bulkRecalcSubmitting
                    ? "Recalculating…"
                    : `Confirm recalc (${selectedCount})`}
                </button>
              </div>
            </div>
          </FocusTrap>
        </div>
      )}

      {/* ---- Bulk mark-reviewed dialog ---- */}
      {bulkReviewedOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Bulk mark patients reviewed"
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 50,
            background: "rgba(0,0,0,0.75)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
          onClick={() => !bulkReviewedSubmitting && onCloseReviewed()}
          onKeyDown={(e) => {
            if (e.key === "Escape" && !bulkReviewedSubmitting) onCloseReviewed();
          }}
          tabIndex={-1}
        >
          <FocusTrap>
            <div
              style={{
                background: tokens.white,
                borderRadius: 10,
                boxShadow: "0 12px 40px rgba(15,23,42,0.25)",
                width: "100%",
                maxWidth: 480,
                padding: 20,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="m-0 text-base font-bold text-slate-900">
                Mark patients as reviewed
              </h3>
              <p className="mt-1.5 text-xs font-semibold text-amber-900">
                This will affect <strong>{selectedCount}</strong> patient
                {selectedCount === 1 ? "" : "s"}.
              </p>
              <p className="mt-1 text-xs text-slate-600">
                Add a brief note that will be attached to each patient&apos;s review log entry.
              </p>
              <textarea
                value={bulkReviewedNote}
                onChange={(e) => onReviewedNoteChange(e.target.value)}
                placeholder="e.g., 'PY 2026 mid-year review — all suspects acknowledged'"
                rows={3}
                aria-label="Bulk review note"
                style={{
                  width: "100%",
                  marginTop: 12,
                  resize: "none",
                  borderRadius: 6,
                  border: `1px solid ${C.border}`,
                  padding: "8px 10px",
                  fontSize: 13,
                  fontFamily: "inherit",
                }}
              />
              <div
                style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}
              >
                <button
                  type="button"
                  onClick={onCloseReviewed}
                  disabled={bulkReviewedSubmitting}
                  style={{
                    padding: "6px 12px",
                    borderRadius: 6,
                    border: `1px solid ${C.border}`,
                    background: tokens.white,
                    color: C.text,
                    fontSize: 13,
                    cursor: bulkReviewedSubmitting ? "not-allowed" : "pointer",
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={onConfirmReviewed}
                  disabled={bulkReviewedSubmitting}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 6,
                    border: "none",
                    background: bulkReviewedSubmitting ? C.border : C.brand,
                    color: tokens.white,
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: bulkReviewedSubmitting ? "not-allowed" : "pointer",
                  }}
                >
                  {bulkReviewedSubmitting
                    ? "Saving…"
                    : `Confirm mark reviewed (${selectedCount})`}
                </button>
              </div>
            </div>
          </FocusTrap>
        </div>
      )}
    </>
  );
}

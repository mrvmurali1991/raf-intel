import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Audit Chain",
  description: "Review immutable audit chain logs for compliance and traceability.",
};

export default function AuditLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

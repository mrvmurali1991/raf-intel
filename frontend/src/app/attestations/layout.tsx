import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Attestations",
  description: "Manage provider attestations for risk adjustment documentation.",
};

export default function AttestationsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

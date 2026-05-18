import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Suspect Conditions",
  description: "Review and act on AI-surfaced suspect conditions for risk adjustment coding.",
};

export default function SuspectsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

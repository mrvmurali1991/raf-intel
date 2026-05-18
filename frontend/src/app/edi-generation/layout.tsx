import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "EDI Generation",
  description: "Generate and manage EDI 837 files for risk adjustment submissions.",
};

export default function EdiGenerationLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Quarterly Goals",
  description: "Track and manage quarterly risk adjustment performance goals.",
};

export default function GoalsLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

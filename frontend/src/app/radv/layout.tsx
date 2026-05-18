import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "RADV Audit Defense",
  description: "Prepare and manage Risk Adjustment Data Validation audit defense documentation.",
};

export default function RadvLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Pre-submission Validation",
  description: "Validate risk adjustment submissions before filing to catch errors early.",
};

export default function PreSubmissionLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

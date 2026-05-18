import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Recapture Gaps",
  description: "Identify and close recapture gaps to improve RAF score accuracy.",
};

export default function RecaptureLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

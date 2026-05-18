import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "V28 Impact",
  description: "Analyze the financial and coding impact of the CMS V28 HCC model transition.",
};

export default function V28ImpactLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

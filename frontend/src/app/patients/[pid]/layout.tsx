import type { Metadata } from "next";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ pid: string }>;
}): Promise<Metadata> {
  const { pid } = await params;
  // TODO: fetch the actual patient name server-side once auth-cookie
  // passthrough is wired up. For now, the PID is sufficient to
  // disambiguate browser tabs (currently all 27 routes share the same title).
  return { title: `Patient ${pid}` };
}

export default function PatientDetailLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}

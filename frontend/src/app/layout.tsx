import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/contexts/auth-context";
import { AuthLayout } from "@/components/auth-layout";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TMIAB-RAF - HCC Coding & Risk Adjustment",
  description:
    "Healthcare RAF score dashboard for patient HCC codes, RAF scores, suspect conditions, and MEAT compliance",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full bg-background text-foreground tracking-tight">
        <a href="#main-content" className="skip-to-content">
          Skip to main content
        </a>
        <AuthProvider>
          <AuthLayout>
            {children}
          </AuthLayout>
        </AuthProvider>
      </body>
    </html>
  );
}

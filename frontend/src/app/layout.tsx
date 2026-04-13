import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/contexts/auth-context";
import { AuthLayout } from "@/components/auth-layout";
import { ThemeProvider } from "@/providers/theme-provider";
import { QueryProvider } from "@/providers/query-provider";
import { ErrorBoundary } from "@/components/ErrorBoundary";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });

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
      className={`${inter.variable} ${mono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full bg-background text-foreground tracking-tight" suppressHydrationWarning>
        <a href="#main-content" className="skip-to-content">
          Skip to main content
        </a>
        {/*
          Provider ordering:
          1. ThemeProvider  — outermost; applies dark/light class to <html>, must wrap everything
          2. QueryProvider  — stable QueryClient for all pages, including prefetch on server components
          3. AuthProvider   — depends on axios (client-only); reads/writes sessionStorage tokens
          4. AuthLayout     — routing guard; renders Sidebar + main shell for authenticated pages
        */}
        <ThemeProvider>
          <QueryProvider>
            <AuthProvider>
              <AuthLayout>
                <ErrorBoundary>
                  {children}
                </ErrorBoundary>
              </AuthLayout>
            </AuthProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

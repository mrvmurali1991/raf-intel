import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/contexts/auth-context";
import { PaymentYearProvider } from "@/contexts/payment-year-context";
import { AuthLayout } from "@/components/auth-layout";
import { ThemeProvider } from "@/providers/theme-provider";
import { QueryProvider } from "@/providers/query-provider";
import { ErrorBoundary } from "@/components/error-boundary";
import { AuthedFeatureFlagProvider } from "@/components/FeatureFlagContext";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });

export const metadata: Metadata = {
  title: { default: "RAF Intelligence", template: "%s | RAF Intelligence" },
  description: "HCC coding and risk adjustment intelligence",
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
    >
      <body
        className="min-h-full bg-background text-foreground tracking-tight"
        suppressHydrationWarning
      >
        <a href="#main-content" className="skip-to-content">
          Skip to main content
        </a>
        {/*
          Provider ordering:
          1. ThemeProvider             — outermost; applies dark/light class to <html>
          2. QueryProvider             — stable QueryClient for all pages
          3. AuthProvider              — restores session token from refresh-token cookie
          4. AuthedFeatureFlagProvider — MUST be inside AuthProvider so it can gate
                                         the /api/feature-flags fetch until the access
                                         token is available. Mounting it outside AuthProvider
                                         (e.g. in QueryProvider) caused a 401 on every
                                         cold page-load before the session was restored.
          5. PaymentYearProvider
          6. AuthLayout                — routing guard + app shell
        */}
        <ThemeProvider>
          <QueryProvider>
            <AuthProvider>
              <AuthedFeatureFlagProvider>
                <PaymentYearProvider>
                  <AuthLayout>
                    <ErrorBoundary>
                      {children}
                    </ErrorBoundary>
                  </AuthLayout>
                </PaymentYearProvider>
              </AuthedFeatureFlagProvider>
            </AuthProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

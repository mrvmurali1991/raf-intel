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
import { TenantBrandingProvider } from "@/lib/TenantBrandingProvider";

// Inter with display:swap and variable font features for a 2025-caliber
// typographic baseline. The cv02/cv03/cv11 OpenType features (elegant Inter
// cuts) are applied in globals.css via font-feature-settings.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });

export const metadata: Metadata = {
  // "Acme Health" is the tenant name shown in the tab. The product name
  // "RAF Intelligence" is intentionally kept out of tenant-facing tab titles.
  title: { default: "Acme Health", template: "%s · Acme Health" },
  description: "HCC coding and risk adjustment intelligence for Acme Health",
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
      <head>
        {/* Blocking inline script — must run before any paint so the `dark`
            class is present on <html> on first render, preventing the
            light-mode flash on page navigation. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('raf-theme');if(t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches)){document.documentElement.classList.add('dark')}}catch(e){}})()`,
          }}
        />
      </head>
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
                {/* TenantBrandingProvider must sit inside AuthProvider so
                    the GET /api/tenant/branding fetch has a session token.
                    It gates rendering on the first response so widgets
                    never flash the default colors before the tenant
                    palette is applied. */}
                <TenantBrandingProvider>
                  <PaymentYearProvider>
                    <AuthLayout>
                      <ErrorBoundary>
                        {children}
                      </ErrorBoundary>
                    </AuthLayout>
                  </PaymentYearProvider>
                </TenantBrandingProvider>
              </AuthedFeatureFlagProvider>
            </AuthProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

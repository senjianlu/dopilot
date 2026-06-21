"use client";

import { useEffect } from "react";
import { ThemeProvider } from "next-themes";
import { I18nextProvider } from "react-i18next";
import { useRouter } from "next/navigation";
import i18n, { readStoredLocale } from "@/lib/i18n/config";
import { registerUnauthorizedHandler } from "@/lib/api/client";
import { Toaster } from "@/components/ui/sonner";

// Top-level client providers: class-based light/dark theme (persisted by
// next-themes), the i18next instance (default zh, persisted override applied
// after mount to avoid a hydration mismatch), and the global toast surface.
export function Providers({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  // Apply the persisted locale once on the client. The static HTML renders in
  // Chinese (DEFAULT_LOCALE); switching here happens after hydration.
  useEffect(() => {
    const stored = readStoredLocale();
    if (i18n.language !== stored) {
      void i18n.changeLanguage(stored);
    }
  }, []);

  // Wire the axios 401 handler to bounce to /login (replaces the old Vue
  // router.push hook). Client-side auth only, matching the static SPA model.
  useEffect(() => {
    registerUnauthorizedHandler(() => router.replace("/login"));
  }, [router]);

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <I18nextProvider i18n={i18n}>
        {children}
        <Toaster richColors position="top-right" />
      </I18nextProvider>
    </ThemeProvider>
  );
}

"use client";

import { useTranslation } from "react-i18next";
import { Languages } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type AppLocale, persistLocale } from "@/lib/i18n/config";

// Toggle between Chinese and English and persist the choice. The label shows the
// language the click will switch TO (matches the old Element Plus LocaleSwitch).
export function LocaleSwitch() {
  const { i18n } = useTranslation();
  const current = (i18n.language as AppLocale) === "en" ? "en" : "zh";

  function toggle() {
    const next: AppLocale = current === "zh" ? "en" : "zh";
    void i18n.changeLanguage(next);
    persistLocale(next);
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={toggle}
      data-testid="locale-switch"
      aria-label="language"
    >
      <Languages data-icon="inline-start" />
      {current === "zh" ? "EN" : "中文"}
    </Button>
  );
}

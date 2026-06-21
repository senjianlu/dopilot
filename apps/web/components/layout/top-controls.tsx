"use client";

import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LocaleSwitch } from "@/components/layout/locale-switch";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { clearToken } from "@/lib/api/token";

// Top-right header cluster: language switch + theme switch (together, as the
// brief requires) + logout.
export function TopControls() {
  const { t } = useTranslation();
  const router = useRouter();

  function onLogout() {
    clearToken();
    router.replace("/login");
  }

  return (
    <div className="flex items-center gap-1">
      <LocaleSwitch />
      <ThemeToggle />
      <Button
        variant="ghost"
        size="sm"
        onClick={onLogout}
        data-testid="logout"
      >
        <LogOut data-icon="inline-start" />
        {t("common.logout")}
      </Button>
    </div>
  );
}

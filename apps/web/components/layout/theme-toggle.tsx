"use client";

import * as React from "react";
import { useTheme } from "next-themes";
import { useTranslation } from "react-i18next";
import { Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

// Light / dark / system switch. next-themes persists the choice in localStorage
// and applies the `.dark` class on <html>, which drives the shadcn slate tokens.
export function ThemeToggle() {
  const { t } = useTranslation();
  const { setTheme } = useTheme();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          data-testid="theme-toggle"
          aria-label={t("common.theme")}
        >
          <Sun className="dark:hidden" />
          <Moon className="hidden dark:block" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuGroup>
          <DropdownMenuItem
            data-testid="theme-light"
            onClick={() => setTheme("light")}
          >
            <Sun />
            {t("common.themeLight")}
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid="theme-dark"
            onClick={() => setTheme("dark")}
          >
            <Moon />
            {t("common.themeDark")}
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid="theme-system"
            onClick={() => setTheme("system")}
          >
            <Monitor />
            {t("common.themeSystem")}
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

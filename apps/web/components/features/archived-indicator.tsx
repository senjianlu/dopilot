"use client";

import * as React from "react";
import { TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// Amber warning mark shown next to a template version (Templates page) or an
// execution-template name (Schedules page) when the referenced build artifact
// has been archived. Self-contained: it bundles its own TooltipProvider so it
// renders both under the app shell (which already provides one — nesting Radix
// providers is safe) and in the page test harness (which does not).
//
// The trigger is a real <button>, so the tooltip is reachable by keyboard/focus
// and not hover-only; the localized text is exposed as the button's accessible
// name and as the tooltip description.
export function ArchivedIndicator({ className }: { className?: string }) {
  const { t } = useTranslation();
  const label = t("artifacts.archivedWarning");
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={label}
            data-testid="archived-indicator"
            className={cn(
              "inline-flex items-center rounded-sm text-amber-500 outline-none focus-visible:ring-2 focus-visible:ring-ring",
              className,
            )}
          >
            <TriangleAlert className="size-4" aria-hidden />
          </button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

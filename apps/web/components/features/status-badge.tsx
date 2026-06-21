"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import type { NodeBadge } from "@/lib/api/types";

// Traffic-light tones. shadcn's slate palette has no green/amber semantic token,
// but node health genuinely needs a green/red/amber/gray signal, so these are
// the deliberate exception. e2e keys on `data-tone` (a stable contract) rather
// than on the colour classes, replacing the old Element Plus `el-tag--*` asserts.
export type Tone = "green" | "red" | "amber" | "gray";

const TONE_CLASS: Record<Tone, string> = {
  green:
    "border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  red: "border-transparent bg-destructive/15 text-destructive dark:text-red-400",
  amber:
    "border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-500",
  gray: "border-transparent bg-muted text-muted-foreground",
};

export const NODE_BADGE_TONE: Record<NodeBadge, Tone> = {
  deleted: "gray",
  offline: "red",
  healthy: "green",
  warning: "amber",
  unknown: "amber",
};

export function ToneBadge({
  tone,
  children,
  className,
  ...props
}: {
  tone: Tone;
} & React.ComponentProps<typeof Badge>) {
  return (
    <Badge
      variant="outline"
      data-tone={tone}
      className={cn(TONE_CLASS[tone], className)}
      {...props}
    >
      {children}
    </Badge>
  );
}

// Breathing health "light" used on the dashboard service table.
export function StatusLight({ tone }: { tone: Tone | "gray" }) {
  const colour: Record<Tone, string> = {
    green: "bg-emerald-500",
    red: "bg-red-500",
    amber: "bg-amber-500",
    gray: "bg-muted-foreground",
  };
  return (
    <span
      data-tone={tone}
      className={cn(
        "inline-block size-3 rounded-full",
        colour[tone],
        tone !== "gray" && "animate-pulse",
      )}
    />
  );
}

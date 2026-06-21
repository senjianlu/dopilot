"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { FileQuestion } from "lucide-react";

// Exported as 404.html by the static build; FastAPI serves it for unknown
// non-API static routes (replacing the old always-200 SPA fallback).
export default function NotFound() {
  return (
    <div className="flex min-h-svh w-full items-center justify-center p-6">
      <Empty>
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileQuestion />
          </EmptyMedia>
          <EmptyTitle>404</EmptyTitle>
          <EmptyDescription>Page not found</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button asChild>
            <Link href="/">dopilot</Link>
          </Button>
        </EmptyContent>
      </Empty>
    </div>
  );
}

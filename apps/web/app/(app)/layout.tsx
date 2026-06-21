"use client";

import { ConfirmProvider } from "@/hooks/use-confirm";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { TopControls } from "@/components/layout/top-controls";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";

// Authenticated app shell: sidebar-07 navigation + a top bar whose right side
// groups the language and theme switches with logout. Auth stays client-side
// (no Next middleware): a missing token surfaces as a 401 from the page's data
// fetch, which the registered handler turns into a /login redirect — matching
// the old SPA. Tolerant when web auth is off.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ConfirmProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset data-testid="app-shell">
          <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger className="-ml-1" />
            <Separator orientation="vertical" className="mr-2 h-4" />
            <div className="ml-auto flex items-center">
              <TopControls />
            </div>
          </header>
          <div className="flex flex-1 flex-col gap-4 p-4">{children}</div>
        </SidebarInset>
      </SidebarProvider>
    </ConfirmProvider>
  );
}

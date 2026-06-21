"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  CalendarClock,
  LayoutDashboard,
  ListChecks,
  Package,
  ScrollText,
  Server,
  Wrench,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";

// dopilot's flat navigation. `key` drives the stable `nav-<key>` testid the
// Playwright flow and the old Element Plus menu both relied on.
const NAV_ITEMS = [
  { key: "dashboard", href: "/dashboard", icon: LayoutDashboard },
  { key: "nodes", href: "/nodes", icon: Server },
  { key: "artifacts", href: "/artifacts", icon: Package },
  { key: "templates", href: "/templates", icon: ScrollText },
  { key: "schedules", href: "/schedules", icon: CalendarClock },
  { key: "tasks", href: "/tasks", icon: ListChecks },
  { key: "maintenance", href: "/maintenance", icon: Wrench },
] as const;

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  const { t } = useTranslation();
  const pathname = usePathname();

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <Link href="/dashboard">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  {/* Brand mark from the committed public asset. The logo is a
                      currentColor monochrome SVG, so we render it as a mask
                      tinted with the foreground color to stay legible in both
                      light and dark sidebars (a plain <img> would paint black). */}
                  <span
                    aria-hidden
                    className="size-4 bg-current"
                    style={{
                      maskImage: "url(/logo.svg)",
                      WebkitMaskImage: "url(/logo.svg)",
                      maskSize: "contain",
                      WebkitMaskSize: "contain",
                      maskRepeat: "no-repeat",
                      WebkitMaskRepeat: "no-repeat",
                      maskPosition: "center",
                      WebkitMaskPosition: "center",
                    }}
                  />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">
                    {t("common.appName")}
                  </span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>{t("common.appName")}</SidebarGroupLabel>
          <SidebarMenu>
            {NAV_ITEMS.map((item) => {
              // A nav item is active for its exact route or any nested route
              // (e.g. /tasks is active on /tasks/detail).
              const active =
                pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <SidebarMenuItem key={item.key}>
                  <SidebarMenuButton
                    asChild
                    isActive={active}
                    tooltip={t(`nav.${item.key}`)}
                  >
                    <Link href={item.href} data-testid={`nav-${item.key}`}>
                      <item.icon />
                      <span>{t(`nav.${item.key}`)}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              );
            })}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  );
}

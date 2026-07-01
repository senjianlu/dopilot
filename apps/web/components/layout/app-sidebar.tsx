"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Logo } from "@/components/logo";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { NAV_ITEMS } from "@/components/layout/nav";

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
                {/* shrink-0 keeps the brand mark square in the collapsed icon
                    rail: the menu button becomes size-8 with p-0, so without it
                    the flex row (gap + hidden label) would squash the box and
                    clip the logo. The Logo is a currentColor SVG, so it inherits
                    the box's foreground color and stays legible in both light
                    (dark box) and dark (light box) sidebars. */}
                <div className="flex aspect-square size-8 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <Logo className="size-4" />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">
                    {t("common.appName")}
                  </span>
                  <span className="truncate text-xs text-sidebar-foreground/70">
                    {t("common.console")}
                  </span>
                </div>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
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

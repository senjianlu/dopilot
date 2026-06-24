"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { activeNavItem } from "@/components/layout/nav";

// Header breadcrumb: the app root plus the current top-level nav page. Nested
// routes resolve to their parent nav item (e.g. /tasks/detail -> Tasks), so the
// crumb stays stable and never grows a per-detail leaf. min-w-0 + flex-nowrap +
// truncate let it shrink and ellipsize instead of colliding with the top
// controls (which are pinned far right by the header's ml-auto group).
export function AppBreadcrumb() {
  const pathname = usePathname();
  const { t } = useTranslation();
  const active = activeNavItem(pathname);

  return (
    <Breadcrumb className="min-w-0">
      <BreadcrumbList className="flex-nowrap">
        <BreadcrumbItem>
          <BreadcrumbLink asChild>
            <Link href="/dashboard">{t("common.appName")}</Link>
          </BreadcrumbLink>
        </BreadcrumbItem>
        {active && (
          <>
            <BreadcrumbSeparator />
            <BreadcrumbItem className="min-w-0">
              <BreadcrumbPage className="truncate" data-testid="breadcrumb-page">
                {t(`nav.${active.key}`)}
              </BreadcrumbPage>
            </BreadcrumbItem>
          </>
        )}
      </BreadcrumbList>
    </Breadcrumb>
  );
}

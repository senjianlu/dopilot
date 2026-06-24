import {
  CalendarClock,
  LayoutDashboard,
  ListChecks,
  Package,
  ScrollText,
  Server,
  Wrench,
  type LucideIcon,
} from "lucide-react";

// dopilot's flat top-level navigation. `key` drives the stable `nav-<key>`
// testid the Playwright flow and the old Element Plus menu both relied on, and
// the `nav.<key>` i18n label shared by the sidebar and the header breadcrumb.
export interface NavItem {
  key: string;
  href: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { key: "dashboard", href: "/dashboard", icon: LayoutDashboard },
  { key: "nodes", href: "/nodes", icon: Server },
  { key: "artifacts", href: "/artifacts", icon: Package },
  { key: "templates", href: "/templates", icon: ScrollText },
  { key: "schedules", href: "/schedules", icon: CalendarClock },
  { key: "tasks", href: "/tasks", icon: ListChecks },
  { key: "maintenance", href: "/maintenance", icon: Wrench },
] as const;

// The top-level nav item that owns a route, mapping nested routes to their
// parent (e.g. /tasks/detail -> tasks). Returns undefined for unmatched paths.
export function activeNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find(
    (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
  );
}

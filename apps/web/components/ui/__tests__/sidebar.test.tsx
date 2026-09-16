import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { SidebarInset } from "@/components/ui/sidebar";

describe("SidebarInset", () => {
  // TC-01. Regression guard for the app-wide horizontal overflow: as a flex
  // item the inset defaults to min-width:auto, whose automatic minimum size is
  // the SMALLER of the specified-size suggestion (w-full -> the whole viewport)
  // and the content-size suggestion. A wide table pushed the latter up, so the
  // minimum landed on the viewport width — and since the inset starts after the
  // sidebar, every page overflowed by exactly the sidebar width. min-w-0 zeroes
  // that minimum so the inset can shrink and Table's own overflow-x-auto takes
  // the scroll. See .ai/2026-09-16/fix-console-horizontal-overflow/.
  it("keeps min-w-0 so it can shrink below its content width", () => {
    render(<SidebarInset data-testid="inset" />);
    expect(screen.getByTestId("inset")).toHaveClass("min-w-0");
  });
});

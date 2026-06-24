import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/lib/test/render";
import { ArchivedIndicator } from "@/components/features/archived-indicator";

// renderWithProviders intentionally does NOT wrap a TooltipProvider — the shared
// component must bundle its own so it renders standalone in tests (a Radix
// Tooltip without a provider ancestor throws).
describe("ArchivedIndicator", () => {
  it("renders without an external TooltipProvider", () => {
    renderWithProviders(<ArchivedIndicator />);
    expect(screen.getByTestId("archived-indicator")).toBeInTheDocument();
  });

  it("exposes the localized label and uses a focusable trigger", () => {
    renderWithProviders(<ArchivedIndicator />);
    const trigger = screen.getByTestId("archived-indicator");
    // The accessible name (not hover-only) comes from the trigger itself.
    expect(trigger).toHaveAccessibleName("This build is archived");
    // A real enabled <button> is keyboard/focus reachable without opening the
    // Radix tooltip during the test.
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger).not.toBeDisabled();
  });
});

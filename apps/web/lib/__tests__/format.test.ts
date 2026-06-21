import { describe, expect, it } from "vitest";
import { formatBytes, formatDateTime } from "@/lib/format";

describe("formatDateTime", () => {
  it("returns '-' for null/empty input", () => {
    expect(formatDateTime(null)).toBe("-");
    expect(formatDateTime(undefined)).toBe("-");
    expect(formatDateTime("")).toBe("-");
  });

  it("falls back to the original string for unparseable input", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });

  it("formats a valid ISO timestamp to seconds precision (no milliseconds)", () => {
    const out = formatDateTime("2026-06-19T01:02:03.456Z");
    // Locale-dependent separators, but the seconds component must be present
    // and milliseconds must never leak into the output.
    expect(out).toMatch(/03/);
    expect(out).not.toMatch(/456/);
    expect(out).not.toBe("-");
    expect(out).not.toBe("2026-06-19T01:02:03.456Z");
  });
});

describe("formatBytes", () => {
  it("shows KB when under 1 MB", () => {
    expect(formatBytes(1024)).toBe("1.00 KB");
    expect(formatBytes(2048)).toBe("2.00 KB");
    // Just under 1 MB still renders as KB.
    expect(formatBytes(1024 * 1024 - 1)).toBe("1024.00 KB");
  });

  it("shows MB at and above 1 MB", () => {
    expect(formatBytes(1024 * 1024)).toBe("1.00 MB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.00 MB");
  });

  it("handles 0 and falsy sizes safely", () => {
    expect(formatBytes(0)).toBe("0.00 KB");
    expect(formatBytes(NaN)).toBe("0.00 KB");
  });
});

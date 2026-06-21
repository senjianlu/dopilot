import { describe, expect, it } from "vitest";
import type { BuildArtifact } from "@/lib/api/types";
import { commandCheckFor, defaultCommand } from "@/lib/templateCommand";

function art(overrides: Partial<BuildArtifact> = {}): BuildArtifact {
  return {
    id: "a",
    artifact_type: "scrapy",
    package_format: "egg",
    name: "demo",
    filename: "demo.egg",
    content_hash: "h",
    size_bytes: 1,
    project: "demo",
    version: "v1",
    spiders: ["phase1", "phase2"],
    fetch_path: null,
    runnable: true,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

describe("defaultCommand", () => {
  it("defaults a scrapy artifact to crawl the first spider", () => {
    expect(defaultCommand(art())).toBe("scrapy crawl phase1");
  });

  it("defaults a python_wheel artifact to a module run", () => {
    expect(
      defaultCommand(art({ artifact_type: "python_wheel", spiders: [] })),
    ).toBe("python -m main");
  });

  it("returns empty when no spider is available", () => {
    expect(defaultCommand(art({ spiders: [] }))).toBe("");
    expect(defaultCommand(undefined)).toBe("");
  });
});

describe("commandCheckFor", () => {
  it("validates a scrapy command with the scrapy parser", () => {
    expect(commandCheckFor(false, "scrapy crawl phase1")).toEqual({
      valid: true,
    });
    expect(commandCheckFor(false, "scrapy crawl phase1; rm -rf /").valid).toBe(
      false,
    );
  });

  it("treats a python_wheel command as free-form (non-empty only)", () => {
    // A shell command the scrapy parser would reject is allowed for a wheel.
    expect(commandCheckFor(true, "python -m main | tee out.log")).toEqual({
      valid: true,
    });
    expect(commandCheckFor(true, "   ")).toEqual({
      valid: false,
      reason: "empty",
    });
  });
});

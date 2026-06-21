import { describe, expect, it } from "vitest";
import { checkScrapyCommand, isValidScrapyCommand } from "@/lib/scrapyCommand";

describe("checkScrapyCommand", () => {
  it("accepts a bare crawl command", () => {
    expect(checkScrapyCommand("scrapy crawl phase1")).toEqual({ valid: true });
  });

  it("accepts -a and -s flags", () => {
    expect(
      isValidScrapyCommand("scrapy crawl phase1 -a k=v -s LOG_LEVEL=DEBUG"),
    ).toBe(true);
  });

  it("rejects an empty command", () => {
    expect(checkScrapyCommand("   ")).toEqual({ valid: false, reason: "empty" });
  });

  it("rejects a non scrapy-crawl command", () => {
    expect(checkScrapyCommand("python -m main").reason).toBe("not_scrapy_crawl");
  });

  it("rejects a missing spider", () => {
    expect(checkScrapyCommand("scrapy crawl").reason).toBe("missing_spider");
  });

  it("rejects shell metacharacters", () => {
    expect(checkScrapyCommand("scrapy crawl phase1; rm -rf /").reason).toBe(
      "shell_metacharacter",
    );
  });

  it("rejects unbalanced quotes", () => {
    expect(checkScrapyCommand("scrapy crawl phase1 -a k='v").reason).toBe(
      "unbalanced_quote",
    );
  });

  it("rejects unsupported flags", () => {
    expect(checkScrapyCommand("scrapy crawl phase1 -x y").reason).toBe(
      "unsupported_flag",
    );
  });

  it("rejects a malformed key=value pair", () => {
    expect(checkScrapyCommand("scrapy crawl phase1 -a kv").reason).toBe(
      "malformed_pair",
    );
  });
});

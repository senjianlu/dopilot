// Pure command helpers for the execution-template create dialog. Extracted so
// the scrapy-vs-wheel branch logic is unit-testable without the shadcn form.
import type { BuildArtifact } from "@/lib/api/types";
import { checkScrapyCommand, type CommandCheck } from "@/lib/scrapyCommand";

// Default the command from the artifact: scrapy -> first spider; python_wheel ->
// a module-run hint (no console scripts under `pip install --target`).
export function defaultCommand(art: BuildArtifact | undefined): string {
  if (art?.artifact_type === "python_wheel") return "python -m main";
  const spider = art?.spiders?.[0];
  return spider ? `scrapy crawl ${spider}` : "";
}

// For a python_wheel the only client-side rule is non-empty (the scrapy parser
// must NOT run against a free-form shell command); otherwise validate as scrapy.
export function commandCheckFor(isWheel: boolean, command: string): CommandCheck {
  if (isWheel) {
    return command.trim().length > 0
      ? { valid: true }
      : { valid: false, reason: "empty" };
  }
  return checkScrapyCommand(command);
}

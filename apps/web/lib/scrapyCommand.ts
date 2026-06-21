// UX-only mirror of the authoritative Python parser in
// packages/protocol/dopilot_protocol/scrapy_command.py. The BACKEND remains
// authoritative; this only blocks an obviously-invalid command before submit and
// gives the user an inline reason. Grammar:
//
//   scrapy crawl <spider> [-a key=value]... [-s KEY=VALUE]...

const UNQUOTED_META = new Set([
  ";", "&", "|", "<", ">", "`", "$", "(", ")", "{", "}", "\\", "!", "*", "?",
  "[", "]", "#", "~", "\n", "\r",
]);
const SPIDER_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const KEY_RE = /^[A-Za-z_][A-Za-z0-9_.-]*$/;

export interface CommandCheck {
  valid: boolean;
  reason?: string;
}

// Tokenize honoring single/double quotes; reject unquoted shell metacharacters.
function tokenize(command: string): string[] {
  const tokens: string[] = [];
  let cur = "";
  let quote: '"' | "'" | null = null;
  let has = false;
  for (const ch of command) {
    if (quote) {
      if (ch === quote) {
        quote = null;
      } else {
        cur += ch;
      }
      has = true;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      has = true;
      continue;
    }
    if (ch === " " || ch === "\t") {
      if (has) {
        tokens.push(cur);
        cur = "";
        has = false;
      }
      continue;
    }
    if (UNQUOTED_META.has(ch)) {
      throw new Error("shell_metacharacter");
    }
    cur += ch;
    has = true;
  }
  if (quote) {
    throw new Error("unbalanced_quote");
  }
  if (has) {
    tokens.push(cur);
  }
  return tokens;
}

export function checkScrapyCommand(command: string): CommandCheck {
  const trimmed = (command ?? "").trim();
  if (!trimmed) {
    return { valid: false, reason: "empty" };
  }
  let tokens: string[];
  try {
    tokens = tokenize(trimmed);
  } catch (e) {
    return { valid: false, reason: (e as Error).message };
  }
  if (tokens.length < 2 || tokens[0] !== "scrapy" || tokens[1] !== "crawl") {
    return { valid: false, reason: "not_scrapy_crawl" };
  }
  if (tokens.length < 3) {
    return { valid: false, reason: "missing_spider" };
  }
  const spider = tokens[2];
  if (spider.startsWith("-") || !SPIDER_RE.test(spider)) {
    return { valid: false, reason: "missing_spider" };
  }
  let i = 3;
  while (i < tokens.length) {
    const flag = tokens[i];
    if (flag !== "-a" && flag !== "-s") {
      return { valid: false, reason: "unsupported_flag" };
    }
    i += 1;
    if (i >= tokens.length) {
      return { valid: false, reason: "missing_value" };
    }
    const pair = tokens[i];
    const eq = pair.indexOf("=");
    if (eq < 0) {
      return { valid: false, reason: "malformed_pair" };
    }
    const key = pair.slice(0, eq);
    if (!key || !KEY_RE.test(key)) {
      return { valid: false, reason: "invalid_key" };
    }
    i += 1;
  }
  return { valid: true };
}

export function isValidScrapyCommand(command: string): boolean {
  return checkScrapyCommand(command).valid;
}

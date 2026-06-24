// Shared client-side name search semantics for list/table pages.
//
// Templates and Schedules both filter rows by a name PREFIX: the query is
// trimmed, matched case-insensitively, and compared with `startsWith`. An empty
// (or whitespace-only) query matches everything. A substring that is not a
// prefix does NOT match. Keeping this in one place guarantees both pages behave
// identically.
export function matchesPrefix(name: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return name.toLowerCase().startsWith(q);
}

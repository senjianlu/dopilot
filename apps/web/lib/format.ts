// Shared display formatters. Timestamps render in the user's current
// browser/page locale (Intl with locale `undefined`) to seconds precision;
// byte sizes adapt between KB and MB. Kept framework-free and unit-testable.

// Locale-aware date+time to SECONDS precision (no milliseconds). Returns "-"
// for null/empty and falls back to the original string for unparseable input.
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(d);
}

// Adaptive byte size across KB/MB/GB/TB (bytes under 1 KB round up to KB, so
// the smallest unit shown is KB). Handles 0/NaN safely.
export function formatBytes(sizeBytes: number): string {
  const bytes = sizeBytes || 0;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(2)} ${units[unit]}`;
}

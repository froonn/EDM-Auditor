const OFFSET_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

/**
 * Parses a date from the API. SQLite keeps no time zone, so the API sends UTC times without an
 * offset; `new Date()` would read them as local time and shift them by the local offset.
 */
export function parseApiDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  const hasTime = value.includes("T");
  return new Date(hasTime && !OFFSET_SUFFIX.test(value) ? `${value}Z` : value);
}

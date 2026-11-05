import { SEVERITIES, isSeverity, type Severity } from "@/api/types";

/**
 * Converts offsets counted in code points (Python strings) into UTF-16 indexes (JavaScript
 * strings). Characters outside the Basic Multilingual Plane, such as emoji, take two UTF-16 units.
 */
export function codePointToUtf16(text: string): (offset: number) => number {
  if (!/[\uD800-\uDBFF]/.test(text)) return (offset) => Math.min(Math.max(offset, 0), text.length);
  const indexes: number[] = [0];
  let unit = 0;
  for (const char of text) {
    unit += char.length;
    indexes.push(unit);
  }
  const last = indexes.length - 1;
  return (offset) => indexes[Math.min(Math.max(offset, 0), last)] as number;
}

export interface HighlightRange {
  id: number;
  severity: string;
  /** Code point offsets from the API. */
  start: number | null | undefined;
  end: number | null | undefined;
}

export interface Segment {
  /** UTF-16 offsets into the text. */
  start: number;
  end: number;
  text: string;
  /** Findings covering the whole segment; empty for plain text. */
  findingIds: number[];
  /** The highest severity among the findings, which defines the color. */
  severity: Severity | null;
}

export function severityRank(severity: string): number {
  const index = (SEVERITIES as readonly string[]).indexOf(severity);
  return index === -1 ? SEVERITIES.length : index;
}

export function hasPosition(range: Pick<HighlightRange, "start" | "end">): boolean {
  return typeof range.start === "number" && typeof range.end === "number" && range.end > range.start;
}

/**
 * Cuts the text at every finding boundary. Each segment knows all findings covering it, so
 * overlapping findings stay visible and clickable.
 */
export function buildSegments(text: string, ranges: readonly HighlightRange[]): Segment[] {
  const toUtf16 = codePointToUtf16(text);
  const spans = ranges
    .filter(hasPosition)
    .map((range) => ({ ...range, from: toUtf16(range.start as number), to: toUtf16(range.end as number) }))
    .filter((span) => span.to > span.from);

  const boundaries = new Set<number>([0, text.length]);
  for (const span of spans) {
    boundaries.add(span.from);
    boundaries.add(span.to);
  }
  const points = [...boundaries].sort((a, b) => a - b);

  const segments: Segment[] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index] as number;
    const end = points[index + 1] as number;
    const covering = spans.filter((span) => span.from <= start && span.to >= end);
    covering.sort((a, b) => severityRank(a.severity) - severityRank(b.severity) || a.id - b.id);
    const top = covering[0]?.severity;
    segments.push({
      start,
      end,
      text: text.slice(start, end),
      findingIds: covering.map((span) => span.id),
      severity: top !== undefined && isSeverity(top) ? top : covering.length > 0 ? "low" : null,
    });
  }
  return segments;
}

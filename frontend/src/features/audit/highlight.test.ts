import { describe, expect, it } from "vitest";

import { buildSegments, codePointToUtf16 } from "./highlight";

const plain = (segments: ReturnType<typeof buildSegments>) =>
  segments.map(({ text, findingIds, severity }) => ({ text, findingIds, severity }));

describe("codePointToUtf16", () => {
  it("keeps offsets of text without astral characters", () => {
    const convert = codePointToUtf16("Срок 10 дней");
    expect(convert(5)).toBe(5);
    expect(convert(99)).toBe(12);
  });

  it("shifts offsets after an emoji", () => {
    // "😀" is one code point in Python and two UTF-16 units in JavaScript.
    const text = "😀 Срок 10 дней";
    const convert = codePointToUtf16(text);
    expect(text.slice(convert(7), convert(9))).toBe("10");
  });
});

describe("buildSegments", () => {
  it("returns the whole text without findings", () => {
    expect(plain(buildSegments("Текст", []))).toEqual([{ text: "Текст", findingIds: [], severity: null }]);
  });

  it("highlights a finding by its code point offsets", () => {
    const text = "Срок 😀 составляет 4 дня.";
    // Python offsets: "4 дня" starts at code point 18.
    const start = [...text].indexOf("4");
    const segments = buildSegments(text, [{ id: 1, severity: "high", start, end: start + 5 }]);
    expect(plain(segments)).toEqual([
      { text: "Срок 😀 составляет ", findingIds: [], severity: null },
      { text: "4 дня", findingIds: [1], severity: "high" },
      { text: ".", findingIds: [], severity: null },
    ]);
  });

  it("splits overlapping findings and colors them by the highest severity", () => {
    const segments = buildSegments("abcdefgh", [
      { id: 1, severity: "low", start: 1, end: 5 },
      { id: 2, severity: "critical", start: 3, end: 7 },
    ]);
    expect(plain(segments)).toEqual([
      { text: "a", findingIds: [], severity: null },
      { text: "bc", findingIds: [1], severity: "low" },
      { text: "de", findingIds: [2, 1], severity: "critical" },
      { text: "fg", findingIds: [2], severity: "critical" },
      { text: "h", findingIds: [], severity: null },
    ]);
  });

  it("skips findings without a position and clamps ranges to the text", () => {
    const segments = buildSegments("abc", [
      { id: 1, severity: "high", start: null, end: null },
      { id: 2, severity: "medium", start: 2, end: 50 },
      { id: 3, severity: "medium", start: 2, end: 2 },
    ]);
    expect(plain(segments)).toEqual([
      { text: "ab", findingIds: [], severity: null },
      { text: "c", findingIds: [2], severity: "medium" },
    ]);
  });

  it("keeps the text intact", () => {
    const text = "Строка 1\n\nСтрока 2 😀 конец";
    const segments = buildSegments(text, [
      { id: 1, severity: "high", start: 3, end: 12 },
      { id: 2, severity: "low", start: 10, end: 20 },
    ]);
    expect(segments.map((segment) => segment.text).join("")).toBe(text);
  });
});

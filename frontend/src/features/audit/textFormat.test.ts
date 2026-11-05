import { describe, expect, it } from "vitest";

import { asOneLine, editableText, hasOnlyParagraphBreaks } from "./textFormat";

const stored = "Положение.\n\nПункт 1.\n\nПункт 2.";

describe("editableText", () => {
  it("shows paragraphs on separate lines and restores them unchanged", () => {
    const { text, toStored } = editableText(stored);
    expect(text).toBe("Положение.\nПункт 1.\nПункт 2.");
    expect(toStored(text)).toBe(stored);
  });

  it("turns new lines into paragraphs and drops empty lines", () => {
    const { toStored } = editableText(stored);
    expect(toStored("Положение.\n\n\nПункт 1.\r\nПункт 3.\n")).toBe("Положение.\n\nПункт 1.\n\nПункт 3.");
  });

  it("edits text with other line breaks as is", () => {
    const own = "Строка 1\nСтрока 2\n\nАбзац";
    expect(hasOnlyParagraphBreaks(own)).toBe(false);
    const { text, toStored } = editableText(own);
    expect(text).toBe(own);
    expect(toStored("x\ny")).toBe("x\ny");
  });
});

describe("asOneLine", () => {
  it("joins a wrapped quote", () => {
    expect(asOneLine("не позднее\n\n10 дней ")).toBe("не позднее 10 дней");
  });
});

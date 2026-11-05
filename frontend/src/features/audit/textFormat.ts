/**
 * The parser joins paragraphs with a blank line ("\n\n"), and every line of a TXT file becomes a
 * paragraph. Shown as is, each line would be followed by an empty one, so a paragraph break is shown
 * as a plain line break. Only the display changes: the offsets refer to the stored text.
 */
export function withParagraphBreaks(text: string): string {
  return text.replaceAll("\n\n", "\n");
}

/**
 * A norm quote is an exact piece of the legal act, so it keeps the line wrapping of the act file,
 * often in the middle of a sentence. The quote is shown as one line of text.
 */
export function asOneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/** True when every line break is a paragraph break, which is what the parser produces. */
export function hasOnlyParagraphBreaks(text: string): boolean {
  return !/(^|[^\n])\n([^\n]|$)/.test(text) && !text.includes("\n\n\n");
}

/**
 * Converts parser text for editing: one line per paragraph instead of a blank line between them.
 * Text with other line breaks, for example one created through the API, is edited as is.
 */
export function editableText(stored: string): { text: string; toStored: (edited: string) => string } {
  if (!hasOnlyParagraphBreaks(stored)) return { text: stored, toStored: (edited) => edited };
  return {
    text: withParagraphBreaks(stored),
    // Each line becomes a paragraph again; empty lines are dropped, as the parser drops them.
    toStored: (edited) => edited.replace(/\r\n?/g, "\n").replace(/\n+/g, "\n\n").replace(/^\n+|\n+$/g, ""),
  };
}

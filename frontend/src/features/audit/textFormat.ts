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

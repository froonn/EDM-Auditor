const UPPERCASE = "ABCDEFGHJKLMNPQRSTUVWXYZ";
const LOWERCASE = "abcdefghijkmnopqrstuvwxyz";
const DIGITS = "23456789";
const SYMBOLS = "!@#$%^&*-_+=";
const ALL_CHARS = UPPERCASE + LOWERCASE + DIGITS + SYMBOLS;

export const DEFAULT_TEMP_PASSWORD_LENGTH = 16;

function randomIndex(max: number): number {
  if (max <= 1) return 0;
  const limit = Math.floor(0x1_0000_0000 / max) * max;
  const buf = new Uint32Array(1);
  while (true) {
    globalThis.crypto.getRandomValues(buf);
    const value = buf[0]!;
    if (value < limit) return value % max;
  }
}

function pickChar(alphabet: string): string {
  return alphabet[randomIndex(alphabet.length)]!;
}

/**
 * Generate a cryptographically strong temporary password containing uppercase,
 * lowercase, digits, and symbols (excluding visually ambiguous characters).
 */
export function generateTemporaryPassword(length = DEFAULT_TEMP_PASSWORD_LENGTH): string {
  const targetLength = Math.max(8, Math.floor(length));
  const chars = [pickChar(UPPERCASE), pickChar(LOWERCASE), pickChar(DIGITS), pickChar(SYMBOLS)];
  while (chars.length < targetLength) {
    chars.push(pickChar(ALL_CHARS));
  }
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randomIndex(i + 1);
    const tmp = chars[i]!;
    chars[i] = chars[j]!;
    chars[j] = tmp;
  }
  return chars.join("");
}

/** Copy text to the system clipboard with a fallback for non-HTTPS contexts. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall back to execCommand below.
  }

  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}

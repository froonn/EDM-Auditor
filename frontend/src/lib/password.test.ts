import { describe, expect, it } from "vitest";

import { DEFAULT_TEMP_PASSWORD_LENGTH, generateTemporaryPassword } from "./password";

describe("generateTemporaryPassword", () => {
  it("generates a strong password of the default length with all character classes", () => {
    const pwd = generateTemporaryPassword();
    expect(pwd).toHaveLength(DEFAULT_TEMP_PASSWORD_LENGTH);
    expect(pwd).toMatch(/[A-Z]/);
    expect(pwd).toMatch(/[a-z]/);
    expect(pwd).toMatch(/[0-9]/);
    expect(pwd).toMatch(/[!@#$%^&*\-_+=]/);
    // Visually ambiguous characters are excluded.
    expect(pwd).not.toMatch(/[01OIl]/);
  });

  it("enforces at least 8 characters even if a shorter length is requested", () => {
    expect(generateTemporaryPassword(4)).toHaveLength(8);
    expect(generateTemporaryPassword(20)).toHaveLength(20);
  });

  it("produces distinct values across consecutive calls", () => {
    const samples = new Set(Array.from({ length: 20 }, () => generateTemporaryPassword()));
    expect(samples.size).toBe(20);
  });
});

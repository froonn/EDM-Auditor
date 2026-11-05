import { describe, expect, it } from "vitest";

import { parseApiDate } from "./dates";

describe("parseApiDate", () => {
  it("reads API times without an offset as UTC", () => {
    expect(parseApiDate("2026-11-05T09:01:07.540440").toISOString()).toBe("2026-11-05T09:01:07.540Z");
  });

  it("keeps an explicit offset", () => {
    expect(parseApiDate("2026-11-05T12:00:00+03:00").toISOString()).toBe("2026-11-05T09:00:00.000Z");
    expect(parseApiDate("2026-11-05T09:00:00Z").toISOString()).toBe("2026-11-05T09:00:00.000Z");
  });
});

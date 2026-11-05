import { describe, expect, it } from "vitest";

import { InvalidNumber, toForm, toParameters } from "./ruleParameters";

describe("rule parameters", () => {
  it("round-trips keyword parameters", () => {
    const form = toForm({ keywords: ["дистанционная", "удалённая"], mode: "required", match: "stem" });
    expect(form.keywords).toBe("дистанционная\nудалённая");
    expect(toParameters("keyword", { ...form, keywords: " дистанционная \n\nудалённая" })).toEqual({
      keywords: ["дистанционная", "удалённая"],
      mode: "required",
      match: "stem",
    });
  });

  it("sends only the fields of the chosen check type", () => {
    const form = toForm({ min_days: 10, keywords: ["x"], recommendation: "Уведомляйте за 10 дней" });
    expect(toParameters("duration", form)).toEqual({ min_days: 10, recommendation: "Уведомляйте за 10 дней" });
  });

  it("reads decimal commas and skips empty bounds", () => {
    expect(toParameters("numeric", { ...toForm({}), entity: "money", min: "50,5", max: "" })).toEqual({
      entity: "money",
      min: 50.5,
    });
  });

  it("rejects a value that is not a number", () => {
    expect(() => toParameters("duration", { ...toForm({}), minDays: "десять" })).toThrow(InvalidNumber);
    expect(() => toParameters("duration", { ...toForm({}), minDays: "1.5" })).toThrow(InvalidNumber);
  });

  it("keeps dates as ISO strings", () => {
    expect(toParameters("date", { ...toForm({}), before: "2027-03-01" })).toEqual({ before: "2027-03-01" });
  });
});

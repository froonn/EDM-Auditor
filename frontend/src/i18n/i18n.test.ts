import { describe, expect, it } from "vitest";

import { describeError } from "@/components/errorMessage";
import { ApiError } from "@/api/client";

import { createI18n } from "./index";
import { ru } from "./ru";

const i18n = createI18n("ru-RU", ru);

describe("i18n", () => {
  it("fills parameters", () => {
    expect(i18n.t("table.range", { from: 1, to: 50, total: 120 })).toBe("1–50 из 120");
  });

  it("returns nothing for a missing optional key", () => {
    expect(i18n.tOptional("error.not_a_code")).toBeUndefined();
  });

  it("formats numbers with the locale", () => {
    // The group separator is a no-break space.
    expect(i18n.formatNumber(1234.5)).toMatch(/^1\s234,5$/u);
  });
});

describe("describeError", () => {
  it("uses the Russian text for a known code and hides the server message", () => {
    const view = describeError(new ApiError(429, "model_rate_limited", "Rate limited"), i18n);
    expect(view.message).toBe(ru["error.model_rate_limited"]);
    expect(view.details).toBeUndefined();
  });

  it("shows the server message as details for an unknown code", () => {
    const view = describeError(new ApiError(500, "brand_new_code", "Something new"), i18n);
    expect(view.message).toBe(ru["error.unknown"]);
    expect(view.details).toBe("Something new");
  });

  it("treats a saved change with a stale index as a warning", () => {
    expect(describeError(new ApiError(503, "rag_index_error"), i18n).isWarning).toBe(true);
  });
});

import type { CheckType } from "@/api/types";

/** Form values of the rule parameters; every field is text, as the inputs hold it. */
export interface ParameterForm {
  keywords: string;
  mode: "forbidden" | "required";
  match: "literal" | "stem" | "regex";
  pattern: string;
  entity: "number" | "duration" | "money" | "percent";
  min: string;
  max: string;
  before: string;
  after: string;
  minDays: string;
  maxDays: string;
  recommendation: string;
}

type Json = Record<string, unknown>;

const asText = (value: unknown) => (value === undefined || value === null ? "" : String(value));
const pick = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
  allowed.includes(value as T) ? (value as T) : fallback;

export function toForm(parameters: Json): ParameterForm {
  return {
    keywords: Array.isArray(parameters.keywords) ? parameters.keywords.map(String).join("\n") : "",
    mode: pick(parameters.mode, ["forbidden", "required"], "forbidden"),
    match: pick(parameters.match, ["literal", "stem", "regex"], "literal"),
    pattern: asText(parameters.pattern),
    entity: pick(parameters.entity, ["number", "duration", "money", "percent"], "number"),
    min: asText(parameters.min),
    max: asText(parameters.max),
    before: asText(parameters.before),
    after: asText(parameters.after),
    minDays: asText(parameters.min_days),
    maxDays: asText(parameters.max_days),
    recommendation: asText(parameters.recommendation),
  };
}

export class InvalidNumber extends Error {
  constructor(readonly field: keyof ParameterForm) {
    super(`Invalid number in ${field}`);
  }
}

function number(form: ParameterForm, field: keyof ParameterForm, integer = false): number | undefined {
  const raw = String(form[field]).trim().replace(",", ".");
  if (!raw) return undefined;
  const value = Number(raw);
  if (!Number.isFinite(value) || (integer && !Number.isInteger(value))) throw new InvalidNumber(field);
  return value;
}

/**
 * Builds the `parameters` of a check type. Only the fields of that type are sent: the API rejects
 * unknown parameters. The API validates the values itself and explains what is wrong.
 */
export function toParameters(checkType: CheckType, form: ParameterForm): Json {
  const result: Json = {};
  const set = (key: string, value: unknown) => {
    if (value !== undefined && value !== "") result[key] = value;
  };
  switch (checkType) {
    case "keyword":
      result.keywords = form.keywords
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean);
      result.mode = form.mode;
      result.match = form.match;
      break;
    case "regex":
      set("pattern", form.pattern.trim());
      break;
    case "numeric":
      result.entity = form.entity;
      set("min", number(form, "min"));
      set("max", number(form, "max"));
      break;
    case "date":
      set("before", form.before);
      set("after", form.after);
      break;
    case "duration":
      set("min_days", number(form, "minDays", true));
      set("max_days", number(form, "maxDays", true));
      break;
  }
  set("recommendation", form.recommendation.trim());
  return result;
}

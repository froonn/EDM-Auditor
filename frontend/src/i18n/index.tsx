import { createContext, useContext, type ReactNode } from "react";

import { parseApiDate } from "@/lib/dates";

import { ru, type MessageKey, type Messages } from "./ru";

export type { MessageKey } from "./ru";

export type MessageParams = Record<string, string | number>;

export interface I18n {
  locale: string;
  t: (key: MessageKey, params?: MessageParams) => string;
  /** Returns the text if the key exists, for keys built from server values such as error codes. */
  tOptional: (key: string, params?: MessageParams) => string | undefined;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatDateTime: (value: string | Date) => string;
  formatDate: (value: string | Date) => string;
}

function interpolate(template: string, params?: MessageParams): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}

export function createI18n(locale: string, messages: Messages): I18n {
  const lookup = (key: string, params?: MessageParams) => {
    const template = (messages as Record<string, string>)[key];
    return template === undefined ? undefined : interpolate(template, params);
  };
  const dateTime = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });
  const date = new Intl.DateTimeFormat(locale, { dateStyle: "medium" });
  return {
    locale,
    t: (key, params) => lookup(key, params) ?? key,
    tOptional: lookup,
    formatNumber: (value, options) => new Intl.NumberFormat(locale, options).format(value),
    formatDateTime: (value) => dateTime.format(parseApiDate(value)),
    formatDate: (value) => date.format(parseApiDate(value)),
  };
}

const defaultI18n = createI18n("ru-RU", ru);
const I18nContext = createContext<I18n>(defaultI18n);

/** The only place that picks the language. A language switch replaces the value here. */
export function I18nProvider({ children }: { children: ReactNode }) {
  return <I18nContext.Provider value={defaultI18n}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  return useContext(I18nContext);
}

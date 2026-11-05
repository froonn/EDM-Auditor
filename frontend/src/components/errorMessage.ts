import { asApiError, type ApiError } from "@/api/client";
import type { I18n } from "@/i18n";

/** Codes that report a saved change with a side problem rather than a failure. */
const WARNING_CODES = new Set(["rag_index_error"]);

export interface ErrorView {
  error: ApiError;
  message: string;
  /** The server text for codes the interface does not know. */
  details: string | undefined;
  isWarning: boolean;
}

export function describeError(error: unknown, i18n: Pick<I18n, "t" | "tOptional">): ErrorView {
  const apiError = asApiError(error);
  const known = i18n.tOptional(`error.${apiError.code}`);
  return {
    error: apiError,
    message: known ?? i18n.t("error.unknown"),
    details: known ? undefined : (apiError.serverMessage ?? apiError.code),
    isWarning: WARNING_CODES.has(apiError.code),
  };
}

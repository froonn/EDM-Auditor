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

/** `withServerMessage` also shows the server text for a known code, when it names the problem. */
export function describeError(
  error: unknown,
  i18n: Pick<I18n, "t" | "tOptional">,
  withServerMessage = false,
): ErrorView {
  const apiError = asApiError(error);
  const known = i18n.tOptional(`error.${apiError.code}`);
  return {
    error: apiError,
    message: known ?? i18n.t("error.unknown"),
    details: known && !withServerMessage ? undefined : (apiError.serverMessage ?? apiError.code),
    isWarning: WARNING_CODES.has(apiError.code),
  };
}

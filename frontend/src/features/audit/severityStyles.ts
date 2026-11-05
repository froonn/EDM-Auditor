import type { Severity } from "@/api/types";

/** Highlight colors in the document text; selection adds a ring in the same tone. */
export const MARK_CLASSES: Record<Severity, string> = {
  critical: "bg-severity-critical-bg border-severity-critical-border",
  high: "bg-severity-high-bg border-severity-high-border",
  medium: "bg-severity-medium-bg border-severity-medium-border",
  low: "bg-severity-low-bg border-severity-low-border",
};

export const ACCENT_CLASSES: Record<Severity, string> = {
  critical: "border-l-severity-critical-border",
  high: "border-l-severity-high-border",
  medium: "border-l-severity-medium-border",
  low: "border-l-severity-low-border",
};
